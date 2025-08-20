import os
import json
import requests
from tqdm import tqdm
import hashlib

# --- Configuration ---
# The script assumes it's located in the /nodes/Yak-ComfyUI/ directory.
# It calculates paths relative to its own location.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS_DIR = os.path.join(SCRIPT_DIR, 'workflows')
MANAGED_MODELS_DIR = os.path.join(SCRIPT_DIR, 'managed_models')

def get_required_models():
    """Scans all workflow directories to find dependencies.json files and builds a set of required models."""
    required = set()
    print(f"Scanning for workflows in: {WORKFLOWS_DIR}")
    if not os.path.isdir(WORKFLOWS_DIR):
        print(f"[ERROR] Workflows directory not found.")
        return required

    for root, _, files in os.walk(WORKFLOWS_DIR):
        if 'dependencies.json' in files:
            dep_path = os.path.join(root, 'dependencies.json')
            try:
                with open(dep_path, 'r') as f:
                    data = json.load(f)
                    for model in data.get('models', []):
                        # The install_path from JSON is like "models/checkpoints/"
                        # We need to extract the subfolder name, e.g., "checkpoints"
                        model_type_folder = model.get('install_path', '').split('/')[1]
                        if model.get('name') and model_type_folder and model.get('download_url'):
                            # Store as a tuple: (model_type_folder, filename, download_url)
                            required.add((model_type_folder, model['name'], model['download_url']))
            except json.JSONDecodeError:
                print(f"[WARNING] Could not parse {dep_path}")
            except Exception as e:
                print(f"[ERROR] An error occurred processing {dep_path}: {e}")

    return required

def get_existing_models():
    """Scans the managed_models directory to see what's already downloaded."""
    existing = set()
    print(f"Scanning for existing models in: {MANAGED_MODELS_DIR}")
    if not os.path.isdir(MANAGED_MODELS_DIR):
        print(f"[ERROR] Managed models directory not found. Creating it.")
        os.makedirs(MANAGED_MODELS_DIR)
        return existing

    for root, _, files in os.walk(MANAGED_MODELS_DIR):
        for filename in files:
            # The root path will be like ".../managed_models/checkpoints"
            # We want to get the "checkpoints" part.
            model_type_folder = os.path.basename(root)
            existing.add((model_type_folder, filename))
    return existing

def download_file(url, dest_path):
    """Downloads a file from a URL to a destination, with a progress bar."""
    print(f"Downloading '{os.path.basename(dest_path)}'...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        total_size = int(response.headers.get('content-length', 0))
        
        with open(dest_path, 'wb') as f, tqdm(
            desc=os.path.basename(dest_path),
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as bar:
            for data in response.iter_content(chunk_size=1024):
                size = f.write(data)
                bar.update(size)
        print("Download complete.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"\n[ERROR] Failed to download from {url}. Reason: {e}")
        # Clean up partially downloaded file
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False

def main():
    """Main function to synchronize models."""
    print("--- Starting Model Synchronization ---")
    
    required_models_full = get_required_models()
    if not required_models_full:
        print("No required models found in any dependencies.json file.")
    else:
        print(f"Found {len(required_models_full)} required model(s).")

    existing_models = get_existing_models()
    print(f"Found {len(existing_models)} existing model(s).")

    # Create a simplified set of required models for easy comparison (folder, name)
    required_models_simple = {(m[0], m[1]) for m in required_models_full}

    # --- Step 1: Download missing models ---
    models_to_download = required_models_full - {(m[0], m[1], "dummy_url") for m in existing_models}
    
    for model_type, filename, url in models_to_download:
        # Check if the model file is already present before attempting to download
        if (model_type, filename) in existing_models:
            continue

        dest_folder = os.path.join(MANAGED_MODELS_DIR, model_type)
        os.makedirs(dest_folder, exist_ok=True)
        dest_path = os.path.join(dest_folder, filename)
        download_file(url, dest_path)

    # --- Step 2: Delete obsolete models ---
    models_to_delete = existing_models - required_models_simple
    if models_to_delete:
        print("\n--- Cleaning up obsolete models ---")
        for model_type, filename in models_to_delete:
            file_path = os.path.join(MANAGED_MODELS_DIR, model_type, filename)
            try:
                os.remove(file_path)
                print(f"Deleted obsolete model: {filename}")
            except OSError as e:
                print(f"[ERROR] Could not delete {file_path}: {e}")
    
    print("\n--- Model Synchronization Complete ---")


if __name__ == "__main__":
    main()

