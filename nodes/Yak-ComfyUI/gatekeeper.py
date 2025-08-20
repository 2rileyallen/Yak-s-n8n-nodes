import asyncio
import json
import uuid
import websockets
import httpx
import random
import os
import base64
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func
import uvicorn

# --- Configuration ---
# The gatekeeper needs to know where the ComfyUI instance is saving its output files.
# This path should be the absolute path to the ComfyUI/output directory inside the shared volume/environment.
COMFYUI_OUTPUT_DIR = os.getenv("COMFYUI_OUTPUT_DIR", str(Path(__file__).parent.parent.parent / "Software" / "ComfyUI" / "output"))
DB_FILE = "gatekeeper_db.sqlite"
COMFYUI_ADDRESS = "127.0.0.1:8188"
GATEKEEPER_PORT = 8189
CLIENT_ID = str(uuid.uuid4())
JOB_HISTORY_DAYS = 30
COMPLETED_JOB_HISTORY_DAYS = 7

# --- State Tracking (DO NOT MODIFY) ---
# This logic is critical for correctly identifying completed jobs from ComfyUI's websocket.
last_queue_remaining = None
last_prompt_id = None

# --- Database Setup (SQLAlchemy) ---
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True, index=True)
    n8n_execution_id = Column(String, index=True)
    comfy_prompt_id = Column(String, index=True, nullable=True)
    status = Column(String, default="pending")
    callback_type = Column(String)
    callback_url = Column(String, nullable=True)
    output_format = Column(String, default="binary")
    # New field to store the final destination path for webhook file moves
    output_path = Column(String, nullable=True)
    result_data = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(bind=engine)

# --- WebSocket Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, job_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[job_id] = websocket
        print(f"[WS-CONN] WebSocket connected for job_id: {job_id}")

    def disconnect(self, job_id: str):
        if job_id in self.active_connections:
            del self.active_connections[job_id]
            print(f"[WS-DCONN] WebSocket disconnected for job_id: {job_id}")

    async def send_result(self, job_id: str, data: dict):
        if job_id in self.active_connections:
            websocket = self.active_connections[job_id]
            try:
                print(f"[WS-SEND] Sending result to job {job_id}: {data}")
                await websocket.send_json(data)
            except Exception as e:
                print(f"[ERROR] Failed to send WebSocket message for job {job_id}: {e}")

manager = ConnectionManager()

# --- DB Cleanup Function ---
def cleanup_old_jobs():
    db = SessionLocal()
    try:
        completed_cutoff = datetime.now() - timedelta(days=COMPLETED_JOB_HISTORY_DAYS)
        db.query(Job).filter(Job.status == 'completed', Job.created_at < completed_cutoff).delete()
        all_cutoff = datetime.now() - timedelta(days=JOB_HISTORY_DAYS)
        db.query(Job).filter(Job.created_at < all_cutoff).delete()
        db.commit()
        print("[INFO] Old jobs cleaned up.")
    finally:
        db.close()

# --- Lifespan Event Handler ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"[INFO] Gatekeeper starting up.")
    print(f"[INFO] ComfyUI output directory set to: {COMFYUI_OUTPUT_DIR}")
    if not os.path.isdir(COMFYUI_OUTPUT_DIR):
        print(f"[WARNING] ComfyUI output directory does not exist. Please check the path.")
    cleanup_old_jobs()
    task = asyncio.create_task(listen_to_comfyui())
    yield
    print("[INFO] Gatekeeper server shutting down.")
    task.cancel()

# --- FastAPI Application ---
app = FastAPI(title="Yak ComfyUI Gatekeeper", lifespan=lifespan)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def randomize_seed(workflow):
    for node in workflow.values():
        # Check for both KSampler and KSamplerAdvanced
        if "KSampler" in node.get("class_type", ""):
            if "seed" in node.get("inputs", {}):
                node["inputs"]["seed"] = random.randint(0, 999999999999999)
    return workflow

# --- API Endpoints ---
@app.post("/execute")
async def execute_workflow(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    new_job = Job(
        job_id=str(uuid.uuid4()),
        n8n_execution_id=payload['n8n_execution_id'],
        callback_type=payload['callback_type'],
        callback_url=payload.get('callback_url'),
        # Read new fields from the node payload
        output_format=payload.get('output_format'),
        output_path=payload.get('output_path'),
        status="pending_submission"
    )
    db.add(new_job)
    db.commit()

    try:
        randomized_workflow = randomize_seed(payload['workflow_json'])
        comfy_payload = {"prompt": randomized_workflow, "client_id": CLIENT_ID}
        async with httpx.AsyncClient() as client:
            response = await client.post(f"http://{COMFYUI_ADDRESS}/prompt", json=comfy_payload, timeout=120)
            response.raise_for_status()
            comfy_response = response.json()

        new_job.comfy_prompt_id = comfy_response['prompt_id']
        new_job.status = "queued"
        db.commit()
        db.refresh(new_job)
        print(f"[INFO] Job {new_job.job_id} submitted to ComfyUI. Prompt ID: {new_job.comfy_prompt_id}")
        return {"status": "success", "job_id": new_job.job_id}
    except Exception as e:
        new_job.status = "submission_failed"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to communicate with ComfyUI: {e}")

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id)

# --- ComfyUI WebSocket Listener (DO NOT MODIFY CORE LOGIC) ---
async def listen_to_comfyui():
    global last_queue_remaining, last_prompt_id
    ws_url = f"ws://{COMFYUI_ADDRESS}/ws?clientId={CLIENT_ID}"

    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                print(f"[INFO] WebSocket connection to ComfyUI established.")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        if not isinstance(data, dict):
                            continue

                        # This logic for tracking job completion is preserved as requested
                        if data.get('type') == 'status':
                            status_data = data.get('data', {}).get('status', {})
                            exec_info = status_data.get('exec_info', {})
                            current_queue = exec_info.get('queue_remaining')

                            if current_queue is not None:
                                if last_queue_remaining is not None and current_queue < last_queue_remaining and last_prompt_id:
                                    print(f"[COMPLETED] Job finished! Queue went from {last_queue_remaining} to {current_queue}")
                                    await handle_job_completion(last_prompt_id)
                                last_queue_remaining = current_queue

                        elif data.get('type') == 'executing':
                            prompt_id = data.get('data', {}).get('prompt_id')
                            if prompt_id:
                                last_prompt_id = prompt_id

                    except Exception as e:
                        print(f"[ERROR] Error processing WebSocket message: {e}")
        except Exception as e:
            print(f"[ERROR] WebSocket listener error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

async def handle_job_completion(prompt_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.comfy_prompt_id == prompt_id).first()
        if not job or job.status == 'completed':
            print(f"[SKIP] Job not found or already completed for prompt_id: {prompt_id}")
            return

        async with httpx.AsyncClient() as client:
            history_response = await client.get(f"http://{COMFYUI_ADDRESS}/history/{prompt_id}")
            history_response.raise_for_status()
            history_data = history_response.json()

        if prompt_id not in history_data:
            print(f"[ERROR] No history found for prompt_id: {prompt_id}")
            return

        output_data = history_data[prompt_id].get('outputs', {})
        job.status = "completed"
        job.result_data = json.dumps(output_data)
        db.commit()
        print(f"[DB] Job {job.job_id} marked as completed.")

        # --- New File Handling and Payload Formatting ---
        final_payload = await format_and_handle_files(job, output_data)

        if job.callback_type == 'websocket':
            await manager.send_result(job.job_id, final_payload)
            print(f"[WS-PUSH] Pushed result for job {job.job_id}.")
        elif job.callback_type == 'webhook' and job.callback_url:
            print(f"[WEBHOOK] Sending result for job {job.job_id} to {job.callback_url}")
            async with httpx.AsyncClient() as client:
                # For binary, we send data directly, not as JSON
                if job.output_format == 'binary' and 'data' in final_payload:
                    binary_data = base64.b64decode(final_payload['data'])
                    files = {'file': (final_payload.get('filename', 'output'), binary_data, final_payload.get('mime_type', 'application/octet-stream'))}
                    await client.post(job.callback_url, files=files, timeout=300)
                else:
                    await client.post(job.callback_url, json=final_payload, timeout=300)

    except Exception as e:
        print(f"[ERROR] Error handling job completion for {prompt_id}: {e}")
    finally:
        db.close()

async def format_and_handle_files(job: Job, output_data: dict) -> dict:
    """
    Prepares the final payload based on the job's requested output format
    and handles moving files for webhook file path requests.
    """
    files = []
    for node_output in output_data.values():
        for file_type in ['images', 'videos', 'audio', 'files']:
            if file_type in node_output:
                files.extend(node_output[file_type])

    if not files:
        return {"format": "text", "data": json.dumps(output_data)}

    results = []
    for file_info in files:
        filename = file_info.get('filename')
        if not filename:
            continue

        # This is the path where ComfyUI saved the file
        source_path = Path(COMFYUI_OUTPUT_DIR) / filename

        if not source_path.is_file():
            print(f"[ERROR] Output file not found at source: {source_path}")
            continue

        # --- WEBSOCKET LOGIC ---
        # Always return the temporary file path. The n8n node will handle it.
        if job.callback_type == 'websocket':
            results.append({
                "format": "filePath",
                "data": str(source_path),
                "filename": filename
            })

        # --- WEBHOOK LOGIC ---
        elif job.callback_type == 'webhook':
            if job.output_format == 'filePath':
                # Move the file to the final destination requested by the user
                dest_path_str = job.output_path
                if not dest_path_str:
                    print(f"[ERROR] Webhook job {job.job_id} requested filePath but no output_path was provided.")
                    continue
                
                try:
                    dest_path = Path(dest_path_str)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source_path), str(dest_path))
                    print(f"[FILE-MOVE] Moved {source_path} to {dest_path}")
                    results.append({
                        "format": "filePath",
                        "data": str(dest_path),
                        "filename": dest_path.name
                    })
                except Exception as e:
                    print(f"[ERROR] Failed to move file for webhook job {job.job_id}: {e}")

            elif job.output_format == 'binary':
                try:
                    with open(source_path, 'rb') as f:
                        binary_data = f.read()
                    base64_data = base64.b64encode(binary_data).decode('utf-8')

                    # Determine MIME type
                    ext = filename.lower().split('.')[-1]
                    mime_map = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp', 'mp4': 'video/mp4', 'webm': 'video/webm', 'mp3': 'audio/mpeg', 'wav': 'audio/wav'}
                    mime_type = mime_map.get(ext, 'application/octet-stream')
                    
                    results.append({
                        "format": "binary",
                        "data": base64_data,
                        "filename": filename,
                        "mime_type": mime_type
                    })
                    # Clean up the temp file after reading
                    os.remove(source_path)
                except Exception as e:
                    print(f"[ERROR] Failed to read binary data for {filename}: {e}")

    return results[0] if len(results) == 1 else {"format": "multiple", "results": results}

# --- Main Execution ---
if __name__ == "__main__":
    uvicorn.run("gatekeeper:app", host="0.0.0.0", port=GATEKEEPER_PORT, reload=True)
