# yak_wgp_driver.py
# This script executes a single Wan2GP job from a JSON file.

import sys
import os
import json
import traceback
from types import SimpleNamespace
from pathlib import Path
import torch
import gc
import argparse

# --- Path Setup ---
DRIVER_NODE_DIR = Path(__file__).parent
WAN2GP_DIR = (DRIVER_NODE_DIR.parent.parent / "Software" / "Wan2GP").resolve()
sys.path.append(str(WAN2GP_DIR))

# --- FIX 1: Argument Handling to prevent wgp's argparse from crashing ---
original_argv = sys.argv.copy()
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--job-file', type=str, required=True, help="Path to the JSON job file.")

job_file_path = None
try:
    args, remaining_args = parser.parse_known_args()
    job_file_path = args.job_file
    
    # Rebuild sys.argv for the wgp import
    sys.argv = [sys.argv[0]] + [arg for arg in remaining_args if arg not in ['--job-file', job_file_path]]

except SystemExit:
    print("[DRIVER-ERROR] Failed to parse --job-file argument.")
    sys.exit(1)

# --- The Workaround to suppress sys.exit during import ---
_original_exit = sys.exit
def _patched_exit(code=0):
    pass 
sys.exit = _patched_exit

try:
    # This imports and runs wgp's initial configuration code
    import wgp
    
    # --- FIX 3: Force Model Definitions to Load Immediately ---
    # This is the line missing from the previous scripts that causes the 'NoneType' error.
    # It ensures the model dictionary (wgp.md) is fully populated before any function 
    # attempts to look up model_type definitions (like get_lora_dir).
    if hasattr(wgp, 'set_model_defaults'):
        wgp.set_model_defaults()
    
finally:
    sys.exit = _original_exit
# --- End of Workaround ---


def run_job_from_file(job_file_path: str):
    """Loads parameters from a JSON file and runs a single Wan2GP generation."""
    
    print(f"[DRIVER] Received job file: {job_file_path}")
    with open(job_file_path, 'r') as f:
        final_params = json.load(f)

    # --- Setup and Initialization ---
    
    # Mock arguments are required for wgp's internal logic
    mock_args = SimpleNamespace(
        lora_dir_qwen=str(WAN2GP_DIR / "loras_qwen"),
        lora_dir=str(WAN2GP_DIR / "loras"),
        lora_dir_i2v=str(WAN2GP_DIR / "loras_i2v"),
        lora_dir_hunyuan=str(WAN2GP_DIR / "loras_hunyuan"),
        lora_dir_hunyuan_i2v=str(WAN2GP_DIR / "loras_hunyuan_i2v"),
        lora_dir_ltxv=str(WAN2GP_DIR / "loras_ltxv"),
        lora_dir_flux=str(WAN2GP_DIR / "loras_flux"),
        settings=str(WAN2GP_DIR / "settings"),
        profile="-1", seed=-1, frames=0, steps=0, advanced=False,
        fp16=False, bf16=False, attention="", vae_config="", compile=False,
        save_masks=False, save_speakers=False, debug_gen_form=False, betatest=False,
        vram_safety_coefficient=0.8, share=False, lock_config=False, lock_model=False,
        save_quantized=False, preload="0", multiple_images=False, check_loras=False, 
        lora_preset="", verbose=1, server_port=0, theme="", perc_reserved_mem_max=0, 
        server_name="", gpu="", open_browser=False, t2v=False, i2v=False, t2v_14B=False, 
        t2v_1_3B=False, vace_1_3B=False, i2v_1_3B=False, i2v_14B=False, listen=False, 
        flow_reverse=True
    )
    wgp.args = mock_args
    
    # Set the checkpoint paths for model loading
    if hasattr(wgp, 'fl'):
        wgp.fl.set_checkpoints_paths([str(WAN2GP_DIR / "ckpts"), str(WAN2GP_DIR)])
    
    # The model defaults are now loaded in the try/finally block above.

    model_name = final_params.pop('model', None)
    if not model_name:
         raise Exception("Job file is missing the required 'model' parameter.")

    state = {
        "gen": {"queue": []}, "all_settings": {}, "loras": [], "loras_presets": [],
        "last_model_per_family": {}, "last_resolution_per_group": {}
    }
    state["model_type"] = model_name
    
    model_filename = wgp.get_model_filename(model_type=model_name, quantization="int8", dtype_policy="")
    state["model_filename"] = model_filename

    loras, _, _, _, _, _ = wgp.setup_loras(model_name, None, wgp.get_lora_dir(model_name), "", None)
    state["loras"] = loras

    wgp.set_model_settings(state, model_name, final_params)
    state["validate_success"] = 1
    wgp.process_prompt_and_add_tasks(state, model_name)

    if not state["gen"]["queue"]:
        raise Exception("Failed to add job to the internal wgp queue. Check prompt/settings validation.")

    print(f"[DRIVER] Starting Wan2GP generation...")
    
    wgp.download_models()

    def dummy_send_cmd(cmd, data):
        pass 

    task = state['gen']['queue'][0]
    params = task['params']
    
    wgp.generate_video(task, dummy_send_cmd, **params)
    
    output_files = state["gen"].get("file_list", [])
    if not output_files:
        raise Exception("Generation finished, but no output file was found.")
    
    output_file = output_files[-1]
    
    print(f"[YAK-RESULT-PATH]{output_file}[/YAK-RESULT-PATH]")

    if wgp.wan_model is not None:
        wgp.release_model()
    gc.collect()
    torch.cuda.empty_cache()


if __name__ == "__main__":
    if job_file_path:
        try:
            run_job_from_file(job_file_path)
        except Exception as e:
            print(f"[DRIVER-ERROR] Failed to run job from file: {e}")
            traceback.print_exc()
            sys.exit(1)
    else:
        print("[DRIVER-INFO] This script is a driver for the Yak-Wan2GP gatekeeper and must be run with --job-file.")
        sys.exit(1)