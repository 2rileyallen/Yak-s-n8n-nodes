# Yak-Wan2GP Gatekeeper (FINAL WORKING VERSION - Fully Assembled)

import asyncio
import sys
import os
import shutil
import uuid
import json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
import traceback

import uvicorn
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.sql import func

# --- FIX for Windows Asyncio Subprocess ---
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ==============================================================================
# Configuration
# ==============================================================================
GATEKEEPER_PORT = 7862
DB_FILE = "wan2gp_gatekeeper.sqlite"

NODE_DIR = Path(__file__).parent.resolve()
ROOT_DIR = NODE_DIR.parent.parent.resolve()
WAN2GP_DIR = (ROOT_DIR / "Software" / "Wan2GP").resolve()
TEMP_DIR = (ROOT_DIR / "temp").resolve()
TEMP_INPUT_DIR = TEMP_DIR / "input"
TEMP_OUTPUT_DIR = TEMP_DIR / "output"
MANIFEST_PATH = NODE_DIR / "manifest.json"

# --- CRITICAL: Executor is located inside the WAN2GP_DIR for CWD fix ---
DRIVER_SCRIPT_PATH = WAN2GP_DIR / "wan2gp_executor.py"
# -----------------------------------------------------------------------

CONDA_ENV = "wan2gp"

# --- CORRECTED PATH LOGIC ---
# Read the base Conda path from the environment variable set by local_config.bat
CONDA_BASE_PATH = os.getenv("CONDA_PATH")
if not CONDA_BASE_PATH:
    raise ValueError("CRITICAL: CONDA_PATH environment variable not set. Please ensure local_config.bat is being called.")
# Construct the full, correct path to the conda executable (using the reliable condabin path)
CONDA_EXECUTABLE = str(Path(CONDA_BASE_PATH) / "condabin" / "conda.bat")
# --- END CORRECTION ---

# ==============================================================================
# Data Models and DB setup
# ==============================================================================
PROCESSING_LOCK = asyncio.Lock()
MANIFEST_DATA = {}
Base = declarative_base()
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
class Job(Base):
    __tablename__ = "jobs"
    job_id = Column(String, primary_key=True, index=True)
    status = Column(String, default="pending")
    parameters = Column(Text)
    result_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
Base.metadata.create_all(bind=engine)
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
class GenerationRequest(BaseModel):
    workflow: str
    profileName: str = ""
    user_inputs: dict = Field(default_factory=dict)

# --- JSON COMPILATION FUNCTION ---
def compile_job_parameters(request: GenerationRequest) -> dict:
    workflow_id = request.workflow
    profile_name = request.profileName
    user_inputs = request.user_inputs
    
    workflow_info = next((w for w in MANIFEST_DATA.get("workflows", []) if w["value"] == workflow_id), None)
    
    if not workflow_info:
        raise HTTPException(status_code=400, detail=f"Workflow '{workflow_id}' not found in manifest.json")
        
    final_params = {}
    gatekeeper_def_path = NODE_DIR / workflow_info['gatekeeperDefinition']
    
    # 1. Load Workflow Base (CRITICAL: Guarantees all 50+ keys are present)
    with open(gatekeeper_def_path, 'r') as f:
        base_params = json.load(f)
        final_params = base_params.copy()
        
    # 2. Load Profile Overrides
    if profile_name and profile_name != "None (Default Settings)":
        family_id = workflow_info.get('family')
        family_info = MANIFEST_DATA.get("modelFamilies", {}).get(family_id)
        profile_info = next((p for p in family_info.get("profiles", []) if p["value"] == profile_name), None)
        
        if profile_info and profile_info['value']:
            # CRITICAL FIX: Add the 'profiles/' subdirectory prefix to the path lookup
            profile_path = WAN2GP_DIR / "profiles" / profile_info['value']
            
            if profile_path.exists():
                with open(profile_path, 'r') as f:
                    profile_settings = json.load(f)
                    final_params.update(profile_settings)
                    
                    # CRITICAL FIX: Clean up the LoRA filename from URL to filename
                    if 'activated_loras' in final_params and final_params['activated_loras']:
                        cleaned_loras = []
                        for lora_url in final_params['activated_loras']:
                            if isinstance(lora_url, str):
                                # Extract only the filename from the end of the URL
                                cleaned_loras.append(Path(lora_url).name)
                            else:
                                cleaned_loras.append(lora_url)
                        final_params['activated_loras'] = cleaned_loras
                    
    # 3. Apply User Inputs (Final overrides)
    final_params.update(user_inputs)
    
    return final_params

# --- RUN INFERENCE TASK (Orchestration) ---
async def run_inference_task(job: Job) -> str:
    print(f"\n[WORKER] Starting job {job.job_id}")
    
    # Re-compile parameters to ensure the most current state is used (from DB)
    request_data = GenerationRequest(**json.loads(job.parameters))
    final_params = compile_job_parameters(request_data)
    
    # 1. Save temporary job file
    job_file_path = TEMP_INPUT_DIR / f"{job.job_id}.json"
    with open(job_file_path, 'w') as f:
        json.dump(final_params, f)
        
    # 2. Construct Command (Execution)
    
    job_file_path_absolute = str(job_file_path.resolve())
    driver_script_path_absolute = str(DRIVER_SCRIPT_PATH.resolve())
    
    command = [
        CONDA_EXECUTABLE, 'run', '-n', CONDA_ENV,
        'python', driver_script_path_absolute, 
        '--job-file', job_file_path_absolute
    ]
    
    # --- DEBUGGING OUTPUT ---
    print("-" * 50)
    print(f"[DEBUG] Execution CMD: {' '.join(command)}")
    print(f"[DEBUG] Subprocess CWD: {WAN2GP_DIR}") 
    print("-" * 50)
    # ------------------------
    
    print("[WORKER] Executing command...")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # FINAL FIX: Set the Current Working Directory of the subprocess
        cwd=str(WAN2GP_DIR) 
    )
    
    stdout, stderr = await process.communicate()
    stdout_str = stdout.decode('utf-8', errors='ignore')
    stderr_str = stderr.decode('utf-8', errors='ignore')
    print(f"[WORKER] Subprocess finished with exit code: {process.returncode}")
    
    # 3. Process Output and Clean Up
    if process.returncode != 0:
        print("[STDERR]:\n" + stderr_str)
        print("[STDOUT]:\n" + stdout_str)
        raise Exception(f"Executor script failed. See logs for details.")
        
    output_path = None
    for line in stdout_str.splitlines():
        if line.startswith("[YAK-RESULT-PATH]"):
            output_path = line.replace("[YAK-RESULT-PATH]", "").replace("[/YAK-RESULT-PATH]", "").strip()
            break
            
    # CRITICAL FIX: Combine WAN2GP_DIR with the RELATIVE output path
    if output_path:
        # Resolve the output path relative to the WAN2GP_DIR
        full_output_path = WAN2GP_DIR / Path(output_path)
    
    if not output_path or not full_output_path.exists():
        print("[STDERR]:\n" + stderr_str)
        print("[STDOUT]:\n" + stdout_str)
        raise Exception("Executor script finished, but the result file path was not found or accessible.")
        
    # Use the full_output_path for the move operation
    final_output_path = TEMP_OUTPUT_DIR / f"{job.job_id}{full_output_path.suffix}"
    shutil.move(str(full_output_path), final_output_path)
    os.remove(job_file_path)
    
    print(f"[WORKER] Job {job.job_id} finished. Output: {final_output_path}")
    return str(final_output_path)

# ==============================================================================
# FastAPI Setup and Worker Loop
# ==============================================================================
async def worker_loop():
    while True:
        async with PROCESSING_LOCK:
            db = SessionLocal()
            job = None
            try:
                job = db.query(Job).filter(Job.status == "pending").order_by(Job.created_at).first()
                if job:
                    job.status = "processing"
                    db.commit()
                    try:
                        result_path = await run_inference_task(job)
                        job.status = "completed"
                        job.result_path = result_path
                    except Exception:
                        error_str = traceback.format_exc()
                        print(f"[WORKER-ERROR] Job {job.job_id} failed:\n{error_str}")
                        job.status = "failed"
                        job.result_path = error_str
                    db.commit()
            finally:
                db.close()
        await asyncio.sleep(1)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global MANIFEST_DATA
    print("[INFO] Wan2GP Gatekeeper is starting up.")
    with open(MANIFEST_PATH, 'r') as f:
        MANIFEST_DATA = json.load(f)
    print("[INFO] manifest.json loaded successfully.")
    TEMP_INPUT_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    worker_task = asyncio.create_task(worker_loop())
    yield
    print("[INFO] Wan2GP Gatekeeper is shutting down.")
    worker_task.cancel()

app = FastAPI(title="Yak-Wan2GP Gatekeeper", lifespan=lifespan)

@app.post("/generate")
async def execute_generation(request: GenerationRequest, db: Session = Depends(get_db)):
    # Compile parameters first to check for errors before creating a Job entry
    try:
        # Pre-check compilation to catch manifest/base JSON errors early
        compile_job_parameters(request) 
    except HTTPException as e:
        # Re-raise compilation errors before job creation
        raise e
        
    # If compilation is okay, create the job and send it to the queue
    new_job = Job(job_id=str(uuid.uuid4()), status="pending", parameters=request.model_dump_json(by_alias=True))
    db.add(new_job)
    db.commit()
    print(f"[API] Job {new_job.job_id} enqueued for workflow '{request.workflow}'.")
    
    # Start polling for the result
    while True:
        await asyncio.sleep(2)
        db.refresh(new_job)
        if new_job.status in ["completed", "failed"]:
            break
    if new_job.status == "failed":
        raise HTTPException(status_code=500, detail=new_job.result_path)
    return {"status": "completed", "job_id": new_job.job_id, "filePath": new_job.result_path}

if __name__ == "__main__":
    uvicorn.run("gatekeeper:app", host="0.0.0.0", port=GATEKEEPER_PORT)