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
        # --- Get Parameters ---
        # TS Node guarantees 'inputFilePath' exists, either from user or temp file
        input_path = params.get('inputFilePath')
        if not input_path or not os.path.exists(input_path):
            raise ValueError(f"Input file not found at path: {input_path}")

        out_w = int(params.get('outputWidth', 1920))
        out_h = int(params.get('outputHeight', 1080))
        method = params.get('resizeMethod', 'stretch')
        
        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')
        if not output_dir or not output_base_name:
             raise ValueError("Output directory or base name not provided by n8n node.")

        video_filter = ""
        output_ext = ".mp4" # Default
        codec_args = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']

        # --- Build Filter Based on Method ---
        if method == 'stretch':
            video_filter = f"scale={out_w}:{out_h},setsar=1"
        
        elif method == 'crop':
            anchor = params.get('cropAnchor', 'center')
            scale_filter = f"scale='max({out_w}/iw,{out_h}/ih)*iw':'max({out_w}/iw,{out_h}/ih)*ih',setsar=1"
            
            x, y = '0', '0'
            if 'left' in anchor.lower(): x = '0'
            elif 'right' in anchor.lower(): x = '(iw-ow)'
            else: x = '(iw-ow)/2' # Center
            
            if 'top' in anchor.lower(): y = '0'
            elif 'bottom' in anchor.lower(): y = '(ih-oh)'
            else: y = '(ih-oh)/2' # Center

            crop_filter = f"crop={out_w}:{out_h}:{x}:{y}"
            video_filter = f"{scale_filter},{crop_filter}"

        elif method == 'pad':
            anchor = params.get('placementAnchor', 'center')
            color = params.get('padColor', 'black')
            scale_filter = f"scale='min({out_w}/iw,{out_h}/ih)*iw':'min({out_w}/iw,{out_h}/ih)*ih',setsar=1"
            
            x, y = '0', '0'
            if 'left' in anchor.lower(): x = '0'
            elif 'right' in anchor.lower(): x = f"({out_w}-iw)"
            else: x = f"({out_w}-iw)/2" # Center
            
            if 'top' in anchor.lower(): y = '0'
            elif 'bottom' in anchor.lower(): y = f"({out_h}-ih)"
            else: y = f"({out_h}-ih)/2" # Center

            pad_filter = f"pad={out_w}:{out_h}:{x}:{y}:color={color}"
            video_filter = f"{scale_filter},{pad_filter}"
            
            if color.lower() == 'transparent':
                output_ext = ".mov"
                codec_args = ['-c:v', 'qtrle', '-pix_fmt', 'yuva444p'] # qtrle supports alpha

        # --- Determine Output Path and Execute ---
        output_path = os.path.join(output_dir, f"{output_base_name}{output_ext}")

        command = ['ffmpeg', '-y', '-i', input_path, '-vf', video_filter]
        command.extend(codec_args)
        command.extend(['-c:a', 'copy', output_path])

        subprocess.run(command, check=True, capture_output=True, text=True)
        
        print(json.dumps({"output_file_path": output_path}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command)}))
        sys.exit(1)

if __name__ == '__main__':
    main()
