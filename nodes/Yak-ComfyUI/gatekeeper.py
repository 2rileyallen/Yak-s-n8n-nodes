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
import copy

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func
import uvicorn

# --- Configuration ---
REPO_ROOT = Path(__file__).parent.parent.parent
COMFYUI_OUTPUT_DIR = os.getenv("COMFYUI_OUTPUT_DIR", str(REPO_ROOT / "Software" / "ComfyUI" / "output"))
COMFYUI_INPUT_DIR = os.getenv("COMFYUI_INPUT_DIR", str(REPO_ROOT / "Software" / "ComfyUI" / "input"))

DB_FILE = "gatekeeper_db.sqlite"
COMFYUI_ADDRESS = "127.0.0.1:8188"
GATEKEEPER_PORT = 8189
CLIENT_ID = str(uuid.uuid4())
JOB_HISTORY_DAYS = 30
COMPLETED_JOB_HISTORY_DAYS = 7

# --- State Tracking (DO NOT MODIFY) ---
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
    # Store the user's output preferences for webhook jobs
    output_format = Column(String, nullable=True)
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
    os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)
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

# --- Workflow Processing Logic ---

def set_by_path(obj, path_str, value):
    """Sets a value in a nested dictionary using a dot-notation path."""
    parts = path_str.split('.')
    ref = obj
    for part in parts[:-1]:
        if part not in ref:
            ref[part] = {}
        ref = ref[part]
    ref[parts[-1]] = value

def process_and_apply_inputs(workflow_template, user_inputs, mappings):
    """
    Processes media files and applies all user inputs to the workflow template
    based on the explicit instructions in the mappings object.
    Returns the finalized workflow.
    """
    processed_inputs = copy.deepcopy(user_inputs)
    final_workflow = copy.deepcopy(workflow_template)

    # Step 1: Explicitly identify and process only media inputs
    for mapping_key, mapping_info in mappings.items():
        if mapping_info.get("is_media_input") and mapping_key in processed_inputs:
            source_path = processed_inputs[mapping_key]
            if isinstance(source_path, str) and os.path.isabs(source_path) and os.path.isfile(source_path):
                try:
                    file_ext = os.path.splitext(source_path)[1].lower()
                    new_filename = f"n8n-input-{uuid.uuid4()}{file_ext}"
                    dest_path = os.path.join(COMFYUI_INPUT_DIR, new_filename)
                    shutil.copy(source_path, dest_path)
                    print(f"[INFO] Copied input file '{os.path.basename(source_path)}' to '{new_filename}'")
                    # Update the value to be the simple filename for injection
                    processed_inputs[mapping_key] = new_filename
                except Exception as e:
                    print(f"[ERROR] Failed to copy input file '{source_path}': {e}")
    
    # Step 2: Apply all processed inputs (including the new media filenames) to the workflow
    for mapping_key, mapping_info in mappings.items():
        if mapping_key in processed_inputs:
            node_id = mapping_info.get("nodeId")
            path_str = mapping_info.get("path")
            if node_id and path_str and node_id in final_workflow:
                set_by_path(final_workflow[node_id], path_str, processed_inputs[mapping_key])

    return final_workflow

def randomize_seed(workflow):
    for node in workflow.values():
        if "KSampler" in node.get("class_type", ""):
            if "seed" in node.get("inputs", {}):
                node["inputs"]["seed"] = random.randint(0, 999999999999999)
    return workflow

# --- API Endpoints ---
@app.post("/execute")
async def execute_workflow(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    
    user_inputs = payload.get('user_inputs', {})
    output_as_file_path = user_inputs.get('outputAsFilePath', False)
    output_format = 'filePath' if output_as_file_path else 'binary'
    output_path = user_inputs.get('outputFilePath') if output_as_file_path else None

    new_job = Job(
        job_id=str(uuid.uuid4()),
        n8n_execution_id=payload['n8n_execution_id'],
        callback_type=payload['callback_type'],
        callback_url=payload.get('callback_url'),
        output_format=output_format,
        output_path=output_path,
        status="pending_submission"
    )
    db.add(new_job)
    db.commit()

    try:
        final_workflow = process_and_apply_inputs(
            payload['workflow_template'],
            payload['user_inputs'],
            payload['mappings']
        )
        
        randomized_workflow = randomize_seed(final_workflow)
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
        print(f"[ERROR] Execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process and execute workflow: {e}")

@app.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await manager.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(job_id)

# --- ComfyUI WebSocket Listener ---
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

                        if data.get('type') == 'status':
                            status_data = data.get('data', {}).get('status', {})
                            exec_info = status_data.get('exec_info', {})
                            current_queue = exec_info.get('queue_remaining')

                            if current_queue is not None:
                                if last_queue_remaining is not None and current_queue < last_queue_remaining and last_prompt_id:
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
            return

        async with httpx.AsyncClient() as client:
            history_response = await client.get(f"http://{COMFYUI_ADDRESS}/history/{prompt_id}")
            history_response.raise_for_status()
            history_data = history_response.json()

        if prompt_id not in history_data:
            return

        output_data = history_data[prompt_id].get('outputs', {})
        job.status = "completed"
        job.result_data = json.dumps(output_data)
        db.commit()
        print(f"[DB] Job {job.job_id} marked as completed.")

        final_payload = await format_and_handle_files(job, output_data)

        if job.callback_type == 'websocket':
            await manager.send_result(job.job_id, final_payload)
        elif job.callback_type == 'webhook' and job.callback_url:
            async with httpx.AsyncClient() as client:
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

        source_path = Path(COMFYUI_OUTPUT_DIR) / filename

        if not source_path.is_file():
            print(f"[ERROR] Output file not found at source: {source_path}")
            continue

        if job.callback_type == 'websocket':
            results.append({
                "format": "filePath",
                "data": str(source_path),
                "filename": filename
            })

        elif job.callback_type == 'webhook':
            if job.output_format == 'filePath':
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
                    ext = filename.lower().split('.')[-1]
                    mime_map = {'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif', 'webp': 'image/webp', 'mp4': 'video/mp4', 'webm': 'video/webm', 'mp3': 'audio/mpeg', 'wav': 'audio/wav'}
                    mime_type = mime_map.get(ext, 'application/octet-stream')
                    results.append({
                        "format": "binary",
                        "data": base64_data,
                        "filename": filename,
                        "mime_type": mime_type
                    })
                    os.remove(source_path)
                except Exception as e:
                    print(f"[ERROR] Failed to read binary data for {filename}: {e}")

    return results[0] if len(results) == 1 else {"format": "multiple", "results": results}

# --- Main Execution ---
if __name__ == "__main__":
    uvicorn.run("gatekeeper:app", host="0.0.0.0", port=GATEKEEPER_PORT, reload=True)
