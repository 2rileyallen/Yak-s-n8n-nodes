import sys
import json
import subprocess
import tempfile
import os
import base64

def get_media_duration(file_path):
    """Get the duration of a media file using ffprobe."""
    command = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', file_path
    ]
    try:
        is_windows = sys.platform == "win32"
        result = subprocess.run(command, capture_output=True, text=True, check=True, shell=is_windows)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        sys.stderr.write(f"Error getting duration for {file_path}: {e}\n")
        return None

def run_ffmpeg_command(command):
    """Runs an FFmpeg command and handles errors."""
    is_windows = sys.platform == "win32"
    subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows)

def main():
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

    output_path = None
    output_as_file_path = params.get('outputAsFilePath', True)
    keep_segments = params.get('keepTrimmedSegments', False)
    
    if keep_segments:
        output_as_file_path = True

    try:
        input_path = params.get('inputFilePath')
        if not input_path:
            raise ValueError("Input file path is missing from the parameters.")
            
        start_time = float(params.get('startTime', 0))
        end_time = float(params.get('endTime', 10))
        
        if not os.path.exists(input_path):
            raise ValueError(f"Input file not found at path: {input_path}")

        duration = get_media_duration(input_path)
        if duration is None:
            raise ValueError("Could not determine the duration of the input file.")
        if start_time >= end_time or start_time > duration:
            raise ValueError("Start time must be less than end time and within the media's duration.")

        if output_as_file_path:
            output_path = params.get('outputFilePath')
            if not output_path: raise ValueError("Output file path is required.")
        else:
            temp_dir = tempfile.gettempdir()
            _, ext = os.path.splitext(input_path)
            if not ext: ext = ".mp4"
            output_path = os.path.join(temp_dir, f"ffmpeg_trim_output{ext}")

        # --- MODIFICATION START ---
        # Re-encode for accuracy instead of using '-c copy'
        main_command = [
            'ffmpeg', '-y', '-i', input_path,
            '-ss', str(start_time),
            '-to', str(end_time),
            '-c:v', 'libx264', '-preset', 'ultrafast', # Re-encode video
            '-c:a', 'aac', # Re-encode audio
            output_path
        ]
        # --- MODIFICATION END ---
        run_ffmpeg_command(main_command)

        json_response = {}

        if keep_segments:
            path_parts = os.path.splitext(output_path)
            
            if start_time > 0:
                before_path = f"{path_parts[0]}_before{path_parts[1]}"
                # --- MODIFICATION START ---
                before_command = [
                    'ffmpeg', '-y', '-i', input_path, 
                    '-to', str(start_time), 
                    '-c:v', 'libx264', '-preset', 'ultrafast', 
                    '-c:a', 'aac', before_path
                ]
                # --- MODIFICATION END ---
                run_ffmpeg_command(before_command)
                json_response['before_segment_path'] = before_path

            if end_time < duration:
                after_path = f"{path_parts[0]}_after{path_parts[1]}"
                # --- MODIFICATION START ---
                after_command = [
                    'ffmpeg', '-y', '-i', input_path, 
                    '-ss', str(end_time), 
                    '-c:v', 'libx264', '-preset', 'ultrafast', 
                    '-c:a', 'aac', after_path
                ]
                # --- MODIFICATION END ---
                run_ffmpeg_command(after_command)
                json_response['after_segment_path'] = after_path

        json_response['output_file_path'] = output_path
        print(json.dumps(json_response))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message}))
        sys.exit(1)
    finally:
        pass

if __name__ == '__main__':
    main()