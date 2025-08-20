import os
import json
import subprocess
import sys

# --- Configuration ---
# This script assumes it's located in the /nodes/Yak-ComfyUI/ directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Path to the root of the repository
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
# Path to the workflows directory to scan for dependencies
WORKFLOWS_DIR = os.path.join(SCRIPT_DIR, 'workflows')
# Path to the ComfyUI installation's custom_nodes directory
CUSTOM_NODES_DIR = os.path.join(REPO_ROOT, 'Software', 'ComfyUI', 'custom_nodes')

def get_required_nodes():
    """Scans all workflow directories for dependencies.json files and builds a dictionary of required nodes."""
    required = {}
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
                    for node in data.get('custom_nodes', []):
                        if node.get('name') and node.get('git_url'):
                            # Use the name as the key to avoid duplicates
                            required[node['name']] = node['git_url']
            except Exception as e:
                print(f"[ERROR] An error occurred processing {dep_path}: {e}")
    return required

def run_command(command, cwd=None):
    """Runs a command in the shell and prints its output."""
    try:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, shell=True)
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())
        return process.poll() == 0
    except Exception as e:
        print(f"[ERROR] Failed to run command '{' '.join(command)}': {e}")
        return False

def main():
    """Main function to synchronize custom nodes."""
    print("--- Starting Custom Node Synchronization ---")

    if not os.path.isdir(CUSTOM_NODES_DIR):
        print(f"[ERROR] ComfyUI custom_nodes directory not found at: {CUSTOM_NODES_DIR}")
        print("Please ensure ComfyUI is installed in the /Software/ folder.")
        return

    required_nodes = get_required_nodes()
    if not required_nodes:
        print("No required custom nodes found in any dependencies.json file.")
    else:
        print(f"Found {len(required_nodes)} required custom node(s).")

    for name, url in required_nodes.items():
        # The folder name is usually the last part of the git URL without the .git
        folder_name = url.split('/')[-1].replace('.git', '')
        node_path = os.path.join(CUSTOM_NODES_DIR, folder_name)

        print("-" * 40)
        print(f"Processing: {name} ({folder_name})")

        if os.path.isdir(node_path):
            # Node exists, so update it
            print("Node already exists. Checking for updates...")
            if not run_command('git pull', cwd=node_path):
                print(f"[WARNING] 'git pull' failed for {name}. It might have local changes.")
        else:
            # Node doesn't exist, so clone it
            print("Node not found. Cloning from repository...")
            if not run_command(f'git clone {url}', cwd=CUSTOM_NODES_DIR):
                 print(f"[ERROR] Failed to clone {name}.")
                 continue # Skip to the next node if cloning fails

        # After cloning or updating, check for and install dependencies
        requirements_path = os.path.join(node_path, 'requirements.txt')
        if os.path.exists(requirements_path):
            print("Found requirements.txt. Installing dependencies...")
            # Get the path to the python executable in the current environment
            python_exe = sys.executable
            if not run_command(f'"{python_exe}" -m pip install -r "{requirements_path}"', cwd=node_path):
                 print(f"[ERROR] Failed to install requirements for {name}.")

    print("\n--- Custom Node Synchronization Complete ---")


if __name__ == "__main__":
    main()
