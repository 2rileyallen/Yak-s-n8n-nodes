import sys
import json
import subprocess
import os

def main():
    """
    Main execution function that reads a list of media files,
    concatenates them using FFmpeg, and returns the path to the output file.
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
    temp_list_file_path = None
    try:
        # --- ROBUST FIX ---
        # Instead of looking for a specific key like 'audio' or 'mediaFiles',
        # we will iterate through the parameters and find the first value that is a list.
        # This makes the script independent of the parameter name in the n8n UI.
        media_files_list = None
        for key, value in params.items():
            if isinstance(value, list):
                media_files_list = value
                break # Found the list, no need to look further

        if not media_files_list:
            raise ValueError("Could not find a valid list of media files in the input parameters.")

        # FFmpeg's concat demuxer works best by reading from a text file.
        output_dir = params.get('outputDirectory')
        if not output_dir:
            raise ValueError("'outputDirectory' not provided by the node.")

        temp_list_file_path = os.path.join(output_dir, f"concat_list_{params.get('outputBaseName', 'temp')}.txt")
        
        # Write the list of files to the temporary text file for FFmpeg to read
        with open(temp_list_file_path, 'w', encoding='utf-8') as f:
            for item in media_files_list:
                # The input is an array of objects like [{"outputFilePath": "path/to/file.mp3"}]
                if isinstance(item, dict) and 'outputFilePath' in item:
                    file_path = item['outputFilePath']
                    f.write(f"file '{file_path.replace(os.sep, '/')}'\n")
                # Or it can be a simple list of strings
                else:
                    file_path = str(item)
                    f.write(f"file '{file_path.replace(os.sep, '/')}'\n")

        # Determine the output extension from the user parameters
        # This part needs to know if we're dealing with audio or video.
        # We can infer this from the user's format choice.
        audio_formats = ['mp3', 'wav', 'aac', 'm4a']
        video_formats = ['mp4', 'mov', 'avi']
        
        output_format = params.get('videoFormat') or params.get('audioFormat', 'mp3')
        
        # Construct the final output path
        output_base_name = params.get('outputBaseName')
        if not output_base_name:
            raise ValueError("'outputBaseName' not provided by the node.")
        
        output_path = os.path.join(output_dir, f"{output_base_name}.{output_format}")

        # Base command structure
        command = [
            'ffmpeg',
            '-y',
            '-f', 'concat',
            '-safe', '0',
            '-i', temp_list_file_path,
        ]

        # Apply the correct codec and quality/bitrate settings based on the output format.
        if output_format in audio_formats:
             if output_format == 'mp3':
                command.extend(['-c:a', 'libmp3lame', '-q:a', '2'])
             elif output_format in ['aac', 'm4a']:
                command.extend(['-c:a', 'aac', '-b:a', '192k'])
             elif output_format == 'wav':
                command.extend(['-c:a', 'pcm_s16le'])
        elif output_format in video_formats:
            # For video, we copy both video and audio streams
            command.extend(['-c', 'copy'])
        else:
            # Fallback for other formats
            command.extend(['-c', 'copy'])

        command.append(output_path)

        is_windows = sys.platform == "win32"
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows)
        
        # Return the full path of the file we successfully created
        print(json.dumps({"output_file_path": output_path, "stdout": result.stdout}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        # This will now provide a much more detailed error message to n8n
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command if 'command' in locals() else [])}))
        sys.exit(1)
    finally:
        # Clean up the temporary list file we created
        if temp_list_file_path and os.path.exists(temp_list_file_path):
            try:
                os.remove(temp_list_file_path)
            except OSError as e:
                sys.stderr.write(f"Error cleaning up temporary file {temp_list_file_path}: {e}\n")

if __name__ == '__main__':
    main()
