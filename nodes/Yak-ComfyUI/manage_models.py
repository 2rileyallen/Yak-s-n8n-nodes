import os
import json
import requests
from tqdm import tqdm
import gdown

# --- New Dependency: PyYAML for reading the config file ---
try:
    import yaml
except ImportError:
    print("\n[ERROR] PyYAML is not installed. Please install it to enable custom model paths.")
    print("In your activated conda environment, run: pip install PyYAML")
    exit(1)


# --- Configuration ---
# The script calculates paths relative to its own location.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
WORKFLOWS_DIR = os.path.join(SCRIPT_DIR, 'workflows')
EXTRA_PATHS_CONFIG = os.path.join(REPO_ROOT, 'Software', 'ComfyUI', 'extra_model_paths.yaml')
DEFAULT_MANAGED_MODELS_DIR = os.path.join(SCRIPT_DIR, 'managed_models')

# --- New Function: Determine the correct directory for managed models ---
def get_managed_models_dir():
    """
    Reads the extra_model_paths.yaml to find the user-defined base path for models.
    If the file or path is not found, it falls back to the default local directory.
    """
    print("--- Checking for custom model directory configuration ---")
    if not os.path.exists(EXTRA_PATHS_CONFIG):
        print(f"[INFO] Configuration file not found at '{EXTRA_PATHS_CONFIG}'.")
        print(f"[INFO] Using default model directory: {DEFAULT_MANAGED_MODELS_DIR}\n")
        return DEFAULT_MANAGED_MODELS_DIR

    try:
        with open(EXTRA_PATHS_CONFIG, 'r') as f:
            config = yaml.safe_load(f)

        # Look for the 'yak' section and its 'base_path'
        yak_config = config.get('yak', {})
        base_path = yak_config.get('base_path')

        if not base_path or not os.path.isabs(base_path):
            print("[WARNING] 'base_path' in 'yak' section of config is missing or not an absolute path.")
            print(f"[INFO] Using default model directory: {DEFAULT_MANAGED_MODELS_DIR}\n")
            return DEFAULT_MANAGED_MODELS_DIR

        # The final directory is the 'managed_models' folder inside the user's specified base_path
        custom_dir = os.path.join(base_path, 'managed_models')
        print(f"[INFO] Found custom model directory in config: {custom_dir}\n")
        return custom_dir

    except Exception as e:
        print(f"[ERROR] Failed to read or parse '{EXTRA_PATHS_CONFIG}': {e}")
        print(f"[INFO] Using default model directory: {DEFAULT_MANAGED_MODELS_DIR}\n")
        return DEFAULT_MANAGED_MODELS_DIR


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
                        model_type_folder = model.get('install_path', '').split('/')[1]
                        download_url = model.get('download_url') or model.get('google_download_url')
                        if model.get('name') and model_type_folder and download_url:
                            required.add((model_type_folder, model['name'], download_url))
            except Exception as e:
                print(f"[ERROR] An error occurred processing {dep_path}: {e}")

    return required

def get_existing_models(managed_models_dir):
    """Scans the specified managed_models directory to see what's already downloaded."""
    existing = set()
    print(f"Scanning for existing models in: {managed_models_dir}")
    if not os.path.isdir(managed_models_dir):
        print(f"[INFO] Managed models directory not found. Creating it.")
        os.makedirs(managed_models_dir)
        return existing

    for root, _, files in os.walk(managed_models_dir):
        for filename in files:
            model_type_folder = os.path.basename(root)
            existing.add((model_type_folder, filename))
    return existing

def download_file(url, dest_path):
    """Downloads a file from a URL to a destination, with a progress bar."""
    filename = os.path.basename(dest_path)
    print(f"Downloading '{filename}'...")
    try:
        if 'drive.google.com' in url:
            gdown.download(url, dest_path, quiet=False)
        else:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))

            with open(dest_path, 'wb') as f, tqdm(
                desc=filename, total=total_size, unit='iB', unit_scale=True, unit_divisor=1024,
            ) as bar:
                for data in response.iter_content(chunk_size=1024):
                    size = f.write(data)
                    bar.update(size)
        print(f"Download of '{filename}' complete.")
        return True
    except Exception as e:
        print(f"\n[ERROR] Failed to download from {url}. Reason: {e}")
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return False

def main():
    """Main function to synchronize models."""
    print("--- Starting Model Synchronization ---")

    # --- MODIFIED: Use the new function to determine the target directory ---
    MANAGED_MODELS_DIR = get_managed_models_dir()

    required_models_full = get_required_models()
    if not required_models_full:
        print("No required models found in any dependencies.json file.")
    else:
        print(f"Found {len(required_models_full)} required model(s).")

    existing_models = get_existing_models(MANAGED_MODELS_DIR)
    print(f"Found {len(existing_models)} existing model(s).")

    required_models_simple = {(m[0], m[1]) for m in required_models_full}

    # --- Step 1: Download missing models ---
    url_map = {(m[0], m[1]): m[2] for m in required_models_full}
    models_to_download = required_models_simple - existing_models

    for model_type, filename in models_to_download:
        url = url_map.get((model_type, filename))
        if not url:
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
