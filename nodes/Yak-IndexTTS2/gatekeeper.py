# Yak-IndexTTS2 Gatekeeper
# A self-contained server to manage a job queue for IndexTTS2,
# dynamically load/unload models, and handle advanced script parsing.

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
import xml.etree.ElementTree as ET
import warnings
import io
from contextlib import redirect_stdout, redirect_stderr
import tempfile
import re # Import the regular expression module

# --- FastAPI & Web Server ---
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect

# --- Database for Queuing ---
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func

# --- For VRAM Management ---
import torch
import gc

# ==============================================================================
# Configuration
# ==============================================================================
GATEKEEPER_PORT = 7863
IDLE_TIMEOUT_SECONDS = 20 # Unload models after 20 seconds of inactivity
DB_FILE = "indextts2_gatekeeper.sqlite"

# --- Path Configuration ---
ROOT_DIR = Path(__file__).parent.parent.parent.resolve()
SOFTWARE_DIR = (ROOT_DIR / "Software" / "IndexTTS2").resolve()
TEMP_OUTPUT_DIR = (ROOT_DIR / "temp" / "output").resolve()

# Add IndexTTS2 software directory to Python path
sys.path.append(str(SOFTWARE_DIR))

# Suppress library warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# Now, we can import the engine
from indextts.infer_v2 import IndexTTS2

# ==============================================================================
# Global State
# ==============================================================================
MODELS = {}
PROCESSING_LOCK = asyncio.Lock()
LAST_JOB_TIMESTAMP = None

# ==============================================================================
# Database Setup
# ==============================================================================
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True, index=True)
    status = Column(String, default="pending")
    payload = Column(Text)
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
# WebSocket Manager
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
# Core Audio Processing Engine (Blocking functions)
# ==============================================================================
def parse_script_recursively(element, jobs, parent_settings):
    """Recursively traverses the XML tree to handle nested tags."""
    current_settings = parent_settings.copy()
    if element.tag not in ['root', 'break']:
        tag_settings = current_settings.setdefault(element.tag, {})
        current_settings[element.tag] = {**tag_settings, **element.attrib}


    if element.text and element.text.strip():
        jobs.append({'type': 'text', 'content': element.text.strip(), 'settings': current_settings})

    for child in element:
        if child.tag == 'break':
            jobs.append({'type': 'break', 'duration': child.attrib.get('time', '0.5s')})
        else:
            parse_script_recursively(child, jobs, current_settings)

        if child.tail and child.tail.strip():
            jobs.append({'type': 'text', 'content': child.tail.strip(), 'settings': parent_settings})

def parse_script(tagged_text: str) -> list:
    """
    Parses a string with custom XML-like tags into a list of processing jobs.
    If no tags are found, it automatically wraps each sentence in a neutral <p> tag
    to force segmentation and improve TTS stability.
    """
    
    # --- NEW PRE-PROCESSING LOGIC ---
    # Check for the presence of any XML-like tags.
    # A simple check for '<' and '>' is sufficient for this purpose.
    if '<' not in tagged_text and '>' not in tagged_text:
        print("[INFO] No tags detected. Pre-emptively segmenting by sentence.")
        # Split the text into sentences using regex.
        sentences = list(filter(None, re.split(r'(?<=[.?!:;])\s+', tagged_text)))
        
        # Wrap each sentence in a neutral <p> tag and join them back together.
        # This will force the XML parser to treat each sentence as a separate element.
        if len(sentences) > 1:
            tagged_text = "".join(f"<p>{s.strip()}</p>" for s in sentences)
        else:
            # If it's just one sentence, no need to wrap it.
            tagged_text = sentences[0] if sentences else ""

    # --- ORIGINAL LOGIC (Now processes the potentially modified text) ---
    jobs = []
    sanitized_text = "".join(c for c in tagged_text if c.isprintable() or c in '\n\r\t')
    
    # We add a custom <root> tag to ensure the XML is always well-formed.
    xml_string = f"<root>{sanitized_text}</root>"
    
    try:
        root = ET.fromstring(xml_string.encode('utf-8'))
        # This recursive function will now correctly segment the auto-tagged text.
        parse_script_recursively(root, jobs, {})
        return jobs
    except ET.ParseError as e:
        # This is a fallback for any severe syntax errors in user-provided tags.
        raise ValueError(f"Failed to parse script tags. Check for syntax errors. Error: {e}")


def generate_silence(duration_str: str, temp_files: list) -> str:
    """Generates a silent audio clip of a specified duration using FFmpeg."""
    # --- FIX: Make duration parsing more robust ---
    try:
        # Use regex to find the number and the unit (ms or s)
        match = re.match(r"^\s*(\d+\.?\d*)\s*(ms|s)?\s*$", duration_str, re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid time format: '{duration_str}'")
        
        value = float(match.group(1))
        unit = match.group(2)
        
        if unit and unit.lower() == 'ms':
            duration_in_seconds = value / 1000.0
        else: # Default to seconds if unit is 's' or not specified
            duration_in_seconds = value
    except (ValueError, TypeError) as e:
         raise ValueError(f"Could not parse duration '{duration_str}'. Please use formats like '1s' or '500ms'. Error: {e}")
    # --- END FIX ---

    output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=TEMP_OUTPUT_DIR).name
    temp_files.append(output_path)
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=22050:cl=mono", "-t", str(duration_in_seconds), output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_path

def apply_effects(input_wav: str, settings: dict, temp_files: list) -> str:
    filters = []
    if 'prosody' in settings:
        p = settings['prosody']
        if 'rate' in p: filters.append(f"atempo={float(p['rate'].replace('%', '')) / 100.0}")
        if 'pitch' in p:
            pitch_mult = 1.0 + (float(p['pitch'].replace('%', '')) / 100.0)
            filters.append(f"asetrate=22050*{pitch_mult},aresample=22050")
        if 'volume' in p:
            vol = p['volume']
            vol_map = {"soft": 0.8, "moderate": 1.0, "loud": 1.5, "x-loud": 2.0}
            volume_val = vol_map.get(vol.lower(), vol)
            filters.append(f"volume={volume_val}")
    if 'emphasis' in settings:
        level = settings['emphasis'].get('level', 'moderate')
        if level == 'strong': filters.append("atempo=0.95,volume=1.2")
        elif level == 'moderate': filters.append("volume=1.1")
        elif level == 'reduced': filters.append("volume=0.85")
    
    if not filters: return input_wav
    
    output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=TEMP_OUTPUT_DIR).name
    temp_files.append(output_path)
    cmd = ["ffmpeg", "-y", "-i", input_wav, "-af", ",".join(filters), output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return output_path

def stitch_audio_chunks(chunk_paths: list, temp_files: list) -> str:
    if not chunk_paths: raise ValueError("No audio chunks to stitch.")
    if len(chunk_paths) == 1: return chunk_paths[0]

    list_file_path = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w', dir=TEMP_OUTPUT_DIR, encoding='utf-8').name
    temp_files.append(list_file_path)
    with open(list_file_path, 'w', encoding='utf-8') as f:
        for path in chunk_paths: f.write(f"file '{Path(path).as_posix()}'\n")
    
    final_output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=TEMP_OUTPUT_DIR).name
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file_path, "-c", "copy", final_output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return final_output_path

def convert_to_mp3(input_wav: str, temp_files: list) -> str:
    """Converts the final WAV to MP3."""
    output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3", dir=TEMP_OUTPUT_DIR).name
    cmd = ["ffmpeg", "-y", "-i", input_wav, "-codec:a", "libmp3lame", "-qscale:a", "2", output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    temp_files.append(input_wav)
    return output_path

# ==============================================================================
# Model and Worker Logic
# ==============================================================================
async def load_models():
    global MODELS
    if not MODELS:
        print("[INFO] Loading IndexTTS2 models into VRAM (cold start)...")
        original_cwd = os.getcwd()
        try:
            os.chdir(SOFTWARE_DIR)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                tts_engine = IndexTTS2(
                    model_dir="./checkpoints",
                    cfg_path="./checkpoints/config.yaml",
                    use_fp16=True, use_cuda_kernel=True
                )
            MODELS['tts'] = tts_engine
            print("[INFO] Models loaded successfully.")
        finally:
            os.chdir(original_cwd)

async def unload_models():
    global MODELS
    if MODELS:
        print(f"[INFO] Idle timeout of {IDLE_TIMEOUT_SECONDS}s reached. Unloading models.")
        MODELS.clear()
        gc.collect()
        torch.cuda.empty_cache()
        print("[INFO] Models unloaded and VRAM cleared.")

def run_inference_blocking(payload: dict) -> str:
    """The main, long-running, blocking function that will be run in a separate thread."""
    print(f"[WORKER] Starting blocking inference task...")
    temp_files = []
    try:
        job_list = parse_script(payload.get("text", ""))
        
        global_emotion_settings = {}
        if payload.get("global_emotion_type") == 'vector':
            global_emotion_settings['emo_vector'] = payload.get("global_emotion_value")
        elif payload.get("global_emotion_type") == 'text':
            global_emotion_settings['use_emo_text'] = True
            global_emotion_settings['emo_text'] = payload.get("global_emotion_value")
        
        audio_chunks = []
        for job in job_list:
            if job['type'] == 'break':
                audio_chunks.append(generate_silence(job['duration'], temp_files))
            elif job['type'] == 'text':
                chunk_out = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=TEMP_OUTPUT_DIR).name
                temp_files.append(chunk_out)
                
                kwargs = global_emotion_settings.copy()
                local_emo = job['settings'].get('emotion', {})
                if local_emo:
                    kwargs = {}
                    if local_emo.get('type') == 'vector':
                        kwargs['emo_vector'] = [float(local_emo.get(e,0.0)) for e in ['happy','angry','sad','afraid','disgusted','melancholic','surprised','calm']]
                    elif local_emo.get('type') == 'text':
                        kwargs['use_emo_text'] = True
                        kwargs['emo_text'] = local_emo.get('prompt', '')
                
                MODELS['tts'].infer(
                    spk_audio_prompt=payload['voice_ref_path'],
                    text=job['content'],
                    output_path=chunk_out,
                    **kwargs
                )
                processed_chunk = apply_effects(chunk_out, job['settings'], temp_files)
                audio_chunks.append(processed_chunk)
        
        final_wav_path = stitch_audio_chunks(audio_chunks, temp_files)
        final_mp3_path = convert_to_mp3(final_wav_path, temp_files)
        print("[WORKER] Blocking task finished successfully.")
        return final_mp3_path
    finally:
        for f in temp_files:
            if os.path.exists(f):
                try: os.unlink(f)
                except: pass

async def worker_loop():
    global LAST_JOB_TIMESTAMP
    while True:
        async with PROCESSING_LOCK:
            db = SessionLocal()
            job = None
            try:
                job = db.query(Job).filter(Job.status == "pending").order_by(Job.created_at).first()
                if job:
                    LAST_JOB_TIMESTAMP = None
                    job.status = "processing"
                    db.commit()
                    
                    result_path, error_str = "", ""
                    try:
                        await load_models()
                        payload = json.loads(job.payload)
                        
                        loop = asyncio.get_event_loop()
                        result_path = await loop.run_in_executor(None, run_inference_blocking, payload)
                        
                        job.status = "completed"
                        job.result_data = json.dumps({"filePath": result_path})
                    except Exception:
                        error_str = traceback.format_exc()
                        print(f"[WORKER-ERROR] Job {job.job_id} failed:\n{error_str}")
                        job.status = "failed"
                        job.result_data = error_str
                    
                    db.commit()
                    
                    if job.status == "completed":
                        await manager.send_json(job.job_id, {"filePath": result_path})
                    else:
                        await manager.send_json(job.job_id, {"error": error_str})
                        
                    LAST_JOB_TIMESTAMP = datetime.now()
                
                elif MODELS and LAST_JOB_TIMESTAMP and (datetime.now() - LAST_JOB_TIMESTAMP).total_seconds() > IDLE_TIMEOUT_SECONDS:
                    await unload_models()
                    LAST_JOB_TIMESTAMP = None
            finally:
                db.close()
        await asyncio.sleep(1)

# ==============================================================================
# FastAPI Application
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[INFO] IndexTTS2 Gatekeeper is starting up.")
    TEMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    worker_task = asyncio.create_task(worker_loop())
    yield
    print("[INFO] IndexTTS2 Gatekeeper is shutting down.")
    worker_task.cancel()

app = FastAPI(title="IndexTTS2 Gatekeeper", lifespan=lifespan)

@app.post("/execute")
async def execute_task(request: Request, db: Session = Depends(get_db)):
    params = await request.json()
    if not all(k in params for k in ["text", "voice_ref_path"]):
        raise HTTPException(status_code=400, detail="Missing 'text' or 'voice_ref_path'")
    
    new_job = Job(job_id=str(uuid.uuid4()), payload=json.dumps(params))
    db.add(new_job)
    db.commit()
    print(f"[API] Job {new_job.job_id} successfully enqueued.")
    return {"status": "enqueued", "job_id": new_job.job_id}

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id)

if __name__ == "__main__":
    print("[INFO] Starting server directly via __main__...")
    uvicorn.run(
        "gatekeeper:app",
        host="127.0.0.1",
        port=GATEKEEPER_PORT,
        reload=True
    )