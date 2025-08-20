import sys
import json
import subprocess
import os

def get_file_path(params, base_name):
    """
    Extracts the file path from the parameters.
    The n8n node should have already converted any binary input to a temporary file,
    so we can expect a FilePath parameter to always be present for inputs.
    """
    path = params.get(f"{base_name}FilePath")
    if not path:
        raise ValueError(f"File path for input '{base_name}' is missing. The n8n node should have provided a temp file path.")
    return path

def main():
    """
    Main execution function that reads parameters, builds and runs the
    FFmpeg command, and returns the path to the output file.
    """
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Expected a single argument: the path to the parameters JSON file."}))
        sys.exit(1)

    params_path = sys.argv[1]
    try:
        with open(params_path, 'r') as f:
            params = json.load(f)
    except Exception as e:
        print(json.dumps({"error": f"Failed to read or parse parameters file: {e}"}))
        sys.exit(1)

    command = []
    try:
        input_path = get_file_path(params, 'input')
        media_type = params.get('mediaType', 'video')

        if not os.path.exists(input_path):
            raise ValueError(f"Input file not found at path: {input_path}")

        command = ['ffmpeg', '-y', '-i', input_path]
        extension = ""

        # --- VIDEO NORMALIZATION ---
        if media_type == 'video':
            extension = params.get('videoFormat', 'mp4')
            video_filters = []
            resolution = params.get('videoResolution', 'original')
            aspect_ratio = params.get('videoAspectRatio', 'original')
            frame_rate = params.get('videoFrameRate', 'original')

            if resolution != 'original':
                video_filters.append(f"scale={resolution}")
            if aspect_ratio != 'original':
                video_filters.append(f"setdar={aspect_ratio.replace(':', '/')}")
            
            video_filters.append("setsar=1")

            if video_filters:
                command.extend(['-vf', ",".join(video_filters)])
            
            if frame_rate != 'original':
                command.extend(['-r', frame_rate])

            command.extend(['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'])

        # --- AUDIO NORMALIZATION ---
        elif media_type == 'audio':
            extension = params.get('audioFormat', 'mp3')
            loudness = params.get('audioLoudness', '-14')
            
            audio_filter = f"loudnorm=I={loudness}:LRA=7:tp=-2"
            command.extend(['-af', audio_filter])
            
            # Add the correct audio codec based on the chosen format
            if extension == 'wav':
                command.extend(['-c:a', 'pcm_s16le'])
            elif extension == 'mp3':
                command.extend(['-c:a', 'libmp3lame'])
            elif extension == 'aac':
                 command.extend(['-c:a', 'aac'])
            # Add other audio formats as needed
            
            command.extend(['-ar', '48000'])

        # --- IMAGE NORMALIZATION ---
        elif media_type == 'image':
            extension = params.get('imageFormat', 'png')
            quality = params.get('imageQuality', 92)
            
            command.extend(['-vf', 'colorspace=all=srgb:iall=srgb:fast=1'])

            if extension in ['jpg', 'jpeg']:
                # Convert 1-100 scale to ffmpeg's 2-31 qscale
                command.extend(['-q:v', str(int(31 * (100 - quality) / 99))])
            elif extension == 'webp':
                command.extend(['-quality', str(quality)])

        # --- CONSTRUCT THE FINAL OUTPUT PATH ---
        # The node provides the directory and a base name (without extension)
        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')
        if not output_dir or not output_base_name:
            raise ValueError("'outputDirectory' or 'outputBaseName' not provided by the node.")
        
        # The script is now responsible for creating the full path with the correct extension
        output_path = os.path.join(output_dir, f"{output_base_name}.{extension}")

        command.append(output_path)

        is_windows = sys.platform == "win32"
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows)
        
        # Return the full path of the file we successfully created
        print(json.dumps({"output_file_path": output_path, "stdout": result.stdout}))

    except subprocess.CalledProcessError as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}"
        print(json.dumps({"error": error_message, "command": " ".join(command)}))
        sys.exit(1)
    except (ValueError, FileNotFoundError) as e:
        error_message = str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command if 'command' in locals() else [])}))
        sys.exit(1)

if __name__ == '__main__':
    main()
