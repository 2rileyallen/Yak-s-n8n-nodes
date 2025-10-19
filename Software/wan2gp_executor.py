# wan2gp_executor.py
# DEBUGGING VERSION: Traces the image_start parameter.

import sys
import os
import json
import torch
import gc
import argparse
from types import SimpleNamespace
from pathlib import Path
import traceback
from PIL import Image

# --- Path Setup (Define the current directory, which is WAN2GP/) ---
WAN2GP_DIR = Path(__file__).parent

# --- 1. Argument Hiding Setup ---
original_sys_argv = sys.argv[:]
job_file_path = None

if '--job-file' in sys.argv:
    try:
        job_file_index = sys.argv.index('--job-file')
        job_file_path = sys.argv[job_file_index + 1]
        sys.argv = [sys.argv[0]]
    except IndexError:
        print("[EXECUTOR-ERROR] Missing path after --job-file flag.")
        sys.exit(1)
# -----------------------------------

# --- The Workaround to suppress sys.exit during import ---
_original_exit = sys.exit
def _patched_exit(code=0):
    pass
sys.exit = _patched_exit

try:
    import wgp
finally:
    sys.exit = _original_exit
# --- End of Workaround ---


def run_job(job_file_path: str):
    """Loads parameters from a JSON file and runs a single Wan2GP generation."""

    sys.argv = original_sys_argv

    print(f"[EXECUTOR] Received job file: {job_file_path}")

    try:
        with open(job_file_path, 'r') as f:
            all_params = json.load(f)
    except FileNotFoundError:
        raise Exception(f"Job file not found at expected path: {job_file_path}")

    # --- Phase 1: Setting up the environment ---
    mock_args = SimpleNamespace(
        save_masks=False, save_speakers=False, debug_gen_form=False, betatest=False,
        vram_safety_coefficient=0.8, share=False, lock_config=False, lock_model=False,
        save_quantized=False, preload="0", multiple_images=False, lora_dir_i2v="",
        lora_dir="loras", lora_dir_hunyuan="loras_hunyuan", lora_dir_hunyuan_i2v="loras_hunyuan_i2v",
        lora_dir_ltxv="loras_ltxv", lora_dir_flux="loras_flux", lora_dir_qwen="loras_qwen",
        check_loras=False, lora_preset="", settings="settings", profile="-1", verbose=1, steps=0,
        frames=0, seed=-1, advanced=False, fp16=False, bf16=False, server_port=0, theme="",
        perc_reserved_mem_max=0, server_name="", gpu="", open_browser=False, t2v=False,
        i2v=False, t2v_14B=False, t2v_1_3B=False, vace_1_3B=False, i2v_1_3B=False,
        i2v_14B=False, compile=False, listen=False, attention="", vae_config="", flow_reverse=True
    )
    wgp.args = mock_args
    if hasattr(wgp, 'set_model_defaults'): wgp.set_model_defaults()
    if hasattr(wgp, 'fl'): wgp.fl.set_checkpoints_paths([str(WAN2GP_DIR / "ckpts"), str(WAN2GP_DIR)])

    state = {
        "gen": {"queue": []}, "all_settings": {}, "loras": [], "loras_presets": [],
        "last_model_per_family": {}, "last_resolution_per_group": {}
    }
    model_choice = all_params.get('model')
    if not model_choice: raise Exception("Job parameters missing required 'model' field.")
    state["model_type"] = model_choice
    if 'model' in all_params: all_params.pop('model')
    state["model_filename"] = wgp.get_model_filename(model_type=model_choice, quantization="int8", dtype_policy="")
    print(f"Target model: {model_choice}")

    # --- Phase 1.5: Explicit Lora Environment Setup ---
    lora_dir = wgp.get_lora_dir(model_choice)
    loras_to_register = all_params.get("activated_loras", [])
    if loras_to_register: wgp.update_loras_url_cache(lora_dir, loras_to_register)
    loras, _, _, _, _, _ = wgp.setup_loras(model_choice, None, lora_dir, "", None)
    state["loras"] = loras
    if loras_to_register: print(f"Loras registered: {', '.join(loras_to_register)}")

    # --- Phase 2: Apply loaded parameters ---
    wgp.set_model_settings(state, model_choice, all_params)

    # --- Phase 2.5: Pre-process Image File Paths (DEBUGGING VERSION) ---
    print("\n--- DEBUG: Checking for image file paths to pre-load ---")
    image_keys_to_process = ['image_start', 'image_mask', 'image_refs', 'image_guide']
    model_settings = wgp.get_model_settings(state, model_choice)
    for key in image_keys_to_process:
        if key in model_settings and isinstance(model_settings[key], str):
            file_path = model_settings[key]
            if file_path and os.path.exists(file_path):
                print(f"DEBUG: Found path for '{key}': {file_path}")
                try:
                    image_obj = Image.open(file_path)
                    model_settings[key] = image_obj
                    print(f"DEBUG: Successfully loaded '{key}'. Object is now a {type(image_obj)}.")
                except Exception as e:
                    print(f"DEBUG: FAILED to load image for '{key}'. Error: {e}")
                    model_settings[key] = None
            elif file_path:
                print(f"DEBUG: WARNING! Image file NOT FOUND for '{key}': {file_path}")
                model_settings[key] = None
    print("--- END DEBUG ---\n")
    # --- END OF DEBUG SECTION ---

    # --- Phase 3: Add job to queue ---
    state["validate_success"] = 1
    print("Adding the generation job to the queue...")
    wgp.process_prompt_and_add_tasks(state, model_choice)

    # --- DEBUG: Inspecting Queue Task ---
    print("\n--- DEBUG: Inspecting Queue Task ---")
    if state["gen"]["queue"]:
        task_params = state["gen"]["queue"][0]['params']
        image_start_in_queue = task_params.get('image_start')
        if image_start_in_queue:
            print(f"DEBUG: 'image_start' in queue is of type: {type(image_start_in_queue)}")
            if not isinstance(image_start_in_queue, Image.Image):
                print("DEBUG: CRITICAL WARNING! 'image_start' in the queue is NOT an Image object!")
        else:
            print("DEBUG: CRITICAL ERROR! 'image_start' is missing or null in the queued task!")
    else:
        print("DEBUG: CRITICAL ERROR! Queue is empty after processing.")
    print("--- END DEBUG ---\n")
    # --- END DEBUG BLOCK ---

    if not state["gen"]["queue"]: raise Exception("Failed to add the task to the queue. Check parameters.")
    task_params = state["gen"]["queue"][0]['params']
    keys_to_remove = ['outputAsFilePath', 'outputAsFile', 'outputBinaryPropertyName', 'inputImageBinaryProperty']
    for key in keys_to_remove:
        if key in task_params: task_params.pop(key)

    print(f"Job successfully added. Queue size: {len(state['gen']['queue'])}")

    # --- Phase 4: Running the generation ---
    print("--- Starting generation process... ---")
    try:
        print("Checking for and downloading required models...")
        wgp.download_models()
        for _ in wgp.process_tasks(state): pass
        print("--- Generation process finished! ---")
        output_files = state["gen"].get("file_list", [])
        if not output_files: raise Exception("Generation finished, but no output file was found.")
        output_file = output_files[-1]
        print(f"[YAK-RESULT-PATH]{output_file}[/YAK-RESULT-PATH]")
    except Exception as e:
        raise e
    finally:
        print("Cleaning up and releasing model from memory...")
        if wgp.wan_model is not None: wgp.release_model()
        gc.collect()
        torch.cuda.empty_cache()

if __name__ == "__main__":
    if job_file_path:
        try:
            run_job(job_file_path)
            sys.exit(0)
        except Exception as e:
            traceback.print_exc()
            sys.exit(1)
    else:
        print("[EXECUTOR-ERROR] The --job-file argument is required.")
        sys.exit(1)