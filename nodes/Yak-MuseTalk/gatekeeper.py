# Yak-MuseTalk Gatekeeper (Local, Direct Import)
# This script is a self-contained server that manages a queue for MuseTalk,
# dynamically loads/unloads models to conserve VRAM, and handles callbacks.

import asyncio
import sys
import os
import shutil
import uuid
import subprocess
import json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import traceback

# --- FastAPI & Web Server ---
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect

# --- Database for Queuing ---
from sqlalchemy import create_engine, Column, String, Text, DateTime, Float, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func

# --- For Webhooks ---
import httpx

# --- For Unloading Models ---
import torch
import gc

# ==============================================================================
# Configuration
# ==============================================================================
# This section contains all the user-configurable settings.

# -- Server Settings --
GATEKEEPER_PORT = 7861
# How long to wait after the last job before unloading models to free VRAM.
IDLE_TIMEOUT_SECONDS = 20
DB_FILE = "musetalk_gatekeeper.sqlite"
JOB_HISTORY_DAYS = 7 # How long to keep job records in the database.

# -- Path Configuration --
# Assumes a specific directory structure:
# /
# |- nodes/
# |  |- Yak-MuseTalk/
# |  |  |- gatekeeper.py  (This file)
# |- Software/
# |  |- MuseTalk/
# |  |  |- app.py
# |- temp/
#    |- input/
#    |- output/
ROOT_DIR = Path(__file__).parent.parent.parent.resolve()
MUSETALK_DIR = (ROOT_DIR / "Software" / "MuseTalk").resolve()
TEMP_DIR = (ROOT_DIR / "temp").resolve()
TEMP_INPUT_DIR = (TEMP_DIR / "input").resolve()
TEMP_OUTPUT_DIR = (TEMP_DIR / "output").resolve()

# -- Environment Configuration --
CONDA_ENV = "yak_musetalk_env" # The name of your Conda environment

# Add MuseTalk directory to Python path to allow direct import
sys.path.append(str(MUSETALK_DIR))

# ==============================================================================
# Global State (In-Memory)
# ==============================================================================
# These variables manage the state of the models and processing.

MODELS = {}  # Dictionary to hold the loaded model functions
PROCESSING_LOCK = asyncio.Lock()  # Ensures only one job runs at a time
LAST_JOB_TIMESTAMP = None # Tracks the last time a job was completed

# ==============================================================================
# Database Setup (SQLAlchemy)
# ==============================================================================
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True, index=True)
    status = Column(String, default="pending")  # pending | processing | completed | failed
    
    # Callback info
    callback_type = Column(String)  # websocket | webhook
    callback_url = Column(String, nullable=True)
    webhook_binary_output = Column(Boolean, default=False)

    # File paths
    audio_path = Column(String)
    video_path = Column(String)
    # This is the temporary path the Gatekeeper will write to.
    gatekeeper_output_path = Column(String)
    # ** NEW **: This is the final path the user wants for webhook jobs.
    user_final_output_path = Column(String, nullable=True)

    # Inference params
    bbox_shift = Column(Float, default=0.0)
    extra_margin = Column(Float, default=10.0)
    parsing_mode = Column(String, default="jaw")
    left_cheek_width = Column(Float, default=90.0)
    right_cheek_width = Column(Float, default=90.0)

    result_data = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==============================================================================
# WebSocket Connection Manager
# ==============================================================================
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[job_id] = websocket

    def disconnect(self, job_id: str):
        if job_id in self.active_connections:
            del self.active_connections[job_id]

    async def send_json(self, job_id: str, data: dict):
        if job_id in self.active_connections:
            try:
                await self.active_connections[job_id].send_json(data)
            except Exception as e:
                print(f"[ERROR] WebSocket send failed for job {job_id}: {e}")

manager = ConnectionManager()

# ==============================================================================
# Core MuseTalk Logic (Model Loading, Inference, Unloading)
# ==============================================================================
async def load_models():
    """Dynamically imports app.py and loads models into memory."""
    global MODELS
    if not MODELS:
        print("[INFO] Loading MuseTalk models into VRAM (cold start)...")
        try:
            # The working directory is now managed by the calling function (run_inference_task)
            import app
            MODELS['check_video'] = app.check_video
            MODELS['inference'] = app.inference
            print("[INFO] Models loaded successfully.")
        except Exception as e:
            print(f"[ERROR] Failed to load models: {e}")
            raise

async def unload_models():
    """Removes models from memory and clears VRAM."""
    global MODELS
    if MODELS:
        print(f"[INFO] Idle timeout of {IDLE_TIMEOUT_SECONDS}s reached. Unloading models.")
        try:
            MODELS.clear()
            # Aggressively clean up references
            if 'app' in sys.modules:
                del sys.modules['app']
            gc.collect()
            torch.cuda.empty_cache()
            print("[INFO] Models unloaded and VRAM cleared.")
        except Exception as e:
            print(f"[ERROR] Error during model unloading: {e}")

async def run_inference_task(job: Job) -> str:
    """The main processing function for a single job. Returns the path to the temp output file."""
    print(f"[WORKER] Starting job {job.job_id}")
    
    original_cwd = os.getcwd()
    try:
        # ** FIX **: Change to the MuseTalk directory for the entire duration of the task.
        # This ensures all relative paths for models and configs resolve correctly.
        os.chdir(MUSETALK_DIR)
        print(f"[INFO] Temporarily changed CWD to: {MUSETALK_DIR}")
        
        await load_models()
        
        audio_input_path = Path(job.audio_path)
        video_input_path = Path(job.video_path)
        
        converted_audio_path = TEMP_INPUT_DIR / f"{job.job_id}_{audio_input_path.stem}.wav"
        print(f"[WORKER] Converting audio to WAV: {converted_audio_path}")
        subprocess.run([
            "ffmpeg", "-i", str(audio_input_path), "-y", "-acodec", "pcm_s16le", "-ar", "16000", str(converted_audio_path)
        ], check=True, capture_output=True)

        print(f"[WORKER] Pre-processing video...")
        processed_video_path_str = MODELS['check_video'](str(video_input_path))
        
        print(f"[WORKER] Running MuseTalk inference...")
        # ** FIX **: Cast float parameters to integers to prevent OpenCV error.
        result_video_path, _ = MODELS['inference'](
            audio_path=str(converted_audio_path),
            video_path=processed_video_path_str,
            bbox_shift=job.bbox_shift,
            extra_margin=int(job.extra_margin),
            parsing_mode=job.parsing_mode,
            left_cheek_width=int(job.left_cheek_width),
            right_cheek_width=int(job.right_cheek_width)
        )
        
        gatekeeper_temp_output = Path(job.gatekeeper_output_path)
        gatekeeper_temp_output.parent.mkdir(parents=True, exist_ok=True)
        
        # result_video_path is relative to MUSETALK_DIR, resolve it before moving
        absolute_result_path = MUSETALK_DIR / result_video_path
        shutil.move(absolute_result_path, gatekeeper_temp_output)
            
        print(f"[WORKER] Job {job.job_id} finished. Temp output at: {gatekeeper_temp_output}")
        
        converted_audio_path.unlink(missing_ok=True)
        processed_video_path = Path(processed_video_path_str)
        if processed_video_path.exists() and "outputxxx_" in processed_video_path.name:
            processed_video_path.unlink(missing_ok=True)

        return str(gatekeeper_temp_output)
    finally:
        # ** FIX **: Always change the directory back, no matter what happens.
        os.chdir(original_cwd)
        print(f"[INFO] Restored CWD to: {original_cwd}")


# ==============================================================================
# Background Worker (The Heart of the Gatekeeper)
# ==============================================================================
async def worker_loop():
    """Continuously polls the DB for jobs and processes them."""
    global LAST_JOB_TIMESTAMP
    while True:
        async with PROCESSING_LOCK:
            db = SessionLocal()
            job = None
            try:
                job = db.query(Job).filter(Job.status == "pending").order_by(Job.created_at).first()

                if job:
                    # A job is found, so reset any pending shutdown timer.
                    LAST_JOB_TIMESTAMP = None 
                    job.status = "processing"
                    db.commit()
                    
                    temp_result_path_str = ""
                    try:
                        temp_result_path_str = await run_inference_task(job)
                        
                        final_path_for_callback = Path(temp_result_path_str)
                        if job.user_final_output_path:
                            final_path_for_callback = Path(job.user_final_output_path)
                            print(f"[WORKER] Moving temp result to final user path: {final_path_for_callback}")
                            final_path_for_callback.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(temp_result_path_str, final_path_for_callback)
                        
                        job.status = "completed"
                        job.result_data = json.dumps({"filePath": str(final_path_for_callback)})
                        
                        if job.callback_type == "webhook":
                            if job.webhook_binary_output:
                                with open(final_path_for_callback, "rb") as f:
                                    files = {'file': (final_path_for_callback.name, f.read(), 'video/mp4')}
                                    async with httpx.AsyncClient(timeout=60) as c:
                                        await c.post(job.callback_url, files=files)
                            else:
                                async with httpx.AsyncClient(timeout=60) as c:
                                    await c.post(job.callback_url, json={"filePath": str(final_path_for_callback)})
                        else: # WebSocket
                            await manager.send_json(job.job_id, {"filePath": str(final_path_for_callback)})

                    except Exception:
                        error_str = traceback.format_exc()
                        print(f"[WORKER-ERROR] Job {job.job_id} failed:\n{error_str}")
                        job.status = "failed"
                        job.result_data = error_str
                        if job.callback_type == "webhook":
                             async with httpx.AsyncClient(timeout=60) as c:
                                await c.post(job.callback_url, json={"error": error_str})
                        else:
                            await manager.send_json(job.job_id, {"error": error_str})
                    
                    db.commit()
                    # ** FIX **: Set the timestamp AFTER the job is fully complete.
                    LAST_JOB_TIMESTAMP = datetime.now()
                
                else: # No job found
                    # ** FIX **: Only check for shutdown if a timestamp is set (meaning we just finished a job)
                    if MODELS and LAST_JOB_TIMESTAMP and (datetime.now() - LAST_JOB_TIMESTAMP).total_seconds() > IDLE_TIMEOUT_SECONDS:
                        await unload_models()
                        LAST_JOB_TIMESTAMP = None # Reset timestamp after unloading

            finally:
                db.close()
        
        await asyncio.sleep(1)

# ==============================================================================
# FastAPI Application
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[INFO] Gatekeeper is starting up.")
    TEMP_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    worker_task = asyncio.create_task(worker_loop())
    yield
    print("[INFO] Gatekeeper is shutting down.")
    worker_task.cancel()

app = FastAPI(title="MuseTalk Gatekeeper", lifespan=lifespan)

@app.post("/execute")
async def execute_musetalk(request: Request, db: Session = Depends(get_db)):
    """Endpoint to receive a new job from N8N."""
    params = await request.json()
    
    required = ["audio_path", "video_path", "gatekeeper_output_path"]
    if not all(key in params for key in required):
        raise HTTPException(status_code=400, detail=f"Missing required keys. Need: {required}")

    new_job = Job(
        job_id=str(uuid.uuid4()),
        status="pending",
        callback_type=params.get("callback_type", "websocket"),
        callback_url=params.get("callback_url"),
        webhook_binary_output=params.get("webhook_binary_output", False),
        audio_path=str(Path(params["audio_path"]).resolve()),
        video_path=str(Path(params["video_path"]).resolve()),
        gatekeeper_output_path=str(Path(params["gatekeeper_output_path"]).resolve()),
        user_final_output_path=str(Path(params["user_final_output_path"]).resolve()) if params.get("user_final_output_path") else None,
        bbox_shift=params.get("bbox_shift", 0),
        extra_margin=params.get("extra_margin", 10),
        parsing_mode=params.get("parsing_mode", "jaw"),
        left_cheek_width=params.get("left_cheek_width", 90),
        right_cheek_width=params.get("right_cheek_width", 90),
    )
    
    db.add(new_job)
    db.commit()

    print(f"[API] Job {new_job.job_id} successfully enqueued.")
    return {"status": "enqueued", "job_id": new_job.job_id}

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id)

@app.get("/status")
async def get_status(db: Session = Depends(get_db)):
    pending = db.query(Job).filter(Job.status == "pending").count()
    processing = db.query(Job).filter(Job.status == "processing").count()
    return {
        "models_loaded": bool(MODELS),
        "jobs_in_queue": pending,
        "jobs_processing": processing,
    }

if __name__ == "__main__":
    print(f"ROOT Directory: {ROOT_DIR}")
    print(f"MUSETALK Directory: {MUSETALK_DIR}")
    uvicorn.run("gatekeeper:app", host="0.0.0.0", port=GATEKEEPER_PORT, reload=True)
