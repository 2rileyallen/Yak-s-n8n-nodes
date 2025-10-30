import sys
import json
import subprocess
import os

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Expected a single argument: the path to the parameters JSON file."}))
        sys.exit(1)
    
    params_path = sys.argv[1]
    command = [] # Define command list early for error logging
    try:
        with open(params_path, 'r') as f:
            params = json.load(f)
    except Exception as e:
        print(json.dumps({"error": f"Failed to read or parse parameters file: {e}"}))
        sys.exit(1)

    try:
        mode = params.get('mode', 'show')
        
        # TS Node guarantees 'inputFilePath' exists, either from user or temp file
        input_path = params.get('inputFilePath')
        if not input_path or not os.path.exists(input_path):
            raise ValueError(f"Input file not found at path: {input_path}")

        # --- MODE: Show Metadata ---
        if mode == 'show':
            command = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', input_path
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
            metadata = json.loads(result.stdout)
            
            # (FIX) The TS node *always* expects an output_file_path.
            # For 'show' mode, we return the original path and the metadata.
            print(json.dumps({"metadata": metadata, "output_file_path": input_path}))
            sys.exit(0)

        # --- MODE: Edit Metadata ---
        elif mode == 'edit':
            media_type = params.get('mediaType', 'video')
            metadata_args = []
            
            # Gather metadata tags based on media type
            prefix = media_type
            tags_to_check = ['Title', 'Artist', 'Album', 'Genre', 'Track', 'Author', 'Copyright', 'Comment', 'Year', 'Description']
            for tag in tags_to_check:
                param_key = f"{prefix}{tag}"
                if param_key in params and params[param_key]:
                    metadata_args.extend([f'-metadata', f'{tag.lower()}={params[param_key]}'])

            if not metadata_args:
                raise ValueError("No metadata values were provided to edit.")

            # Get output path details from n8n node
            output_dir = params.get('outputDirectory')
            output_base_name = params.get('outputBaseName')
            if not output_dir or not output_base_name:
                 raise ValueError("Output directory or base name not provided by n8n node.")
            
            _, ext = os.path.splitext(input_path)
            if not ext:
                ext = ".mp4" # Default if input somehow has no extension
            
            output_path = os.path.join(output_dir, f"{output_base_name}{ext}")

            # FFmpeg command to copy streams and add metadata
            command = [
                'ffmpeg', '-y', '-i', input_path,
                '-c', 'copy', # Copy all streams without re-encoding
            ] + metadata_args + [output_path]

            subprocess.run(command, check=True, capture_output=True, text=True)
            
            print(json.dumps({"status": "Metadata edited successfully.", "output_file_path": output_path}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command)}))
        sys.exit(1)

if __name__ == '__main__':
    main()

