import sys
import json
import subprocess
import os

def hex_to_ffmpeg_color(hex_color):
    """Converts a #RRGGBB hex color to FFmpeg's 0xRRGGBB format."""
    if hex_color.startswith('#'):
        return f"0x{hex_color[1:]}"
    return hex_color

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Expected a single argument: the path to the parameters JSON file."}))
        sys.exit(1)

    params_path = sys.argv[1]
    try:
        with open(params_path, 'r', encoding='utf-8') as f:
            params = json.load(f)
    except Exception as e:
        print(json.dumps({"error": f"Failed to read or parse parameters file: {e}"}))
        sys.exit(1)

    command = ['ffmpeg', '-y']
    try:
        # --- Get Core Parameters ---
        is_transparent = params.get('outputAsTransparentOverlay', True)
        text_content = params.get('textContent', '')
        if not text_content:
            raise ValueError("Text Content cannot be empty.")
        
        start_time = params.get('startTime', 0)
        end_time = params.get('endTime', 5)
        if start_time >= end_time:
            raise ValueError("End Time must be greater than Start Time.")

        # --- Determine Output Path ---
        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')
        if not output_dir or not output_base_name:
            raise ValueError("'outputDirectory' or 'outputBaseName' not provided by the node.")

        if is_transparent:
            output_path = os.path.join(output_dir, f"{output_base_name}.mov")
        else:
            output_path = os.path.join(output_dir, f"{output_base_name}.mp4")

        # --- Build Input Stage ---
        if is_transparent:
            duration = end_time
            width = params.get('videoWidth', 1080)
            height = params.get('videoHeight', 1920)
            command.extend([
                '-f', 'lavfi',
                '-i', f'color=c=black@0.0:s={width}x{height}:d={duration}'
            ])
        else:
            input_video = params.get('inputVideo')
            if not input_video or not os.path.exists(input_video):
                raise ValueError("Input video path is required for burn-in mode.")
            command.extend(['-i', input_video])

        # --- FONT LOGIC (FIXED) ---
        # Get the absolute path of the directory where this script is located.
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct the absolute path to the shared fonts directory.
        shared_fonts_dir = os.path.abspath(os.path.join(script_dir, '..', '_shared', 'text_effects', 'fonts'))

        font_map = {
            "Anton": "Anton-Regular.ttf",
            "Asimovian": "Asimovian-Regular.ttf",
            "Bebas Neue": "BebasNeue-Regular.ttf",
            "Caprasimo": "Caprasimo-Regular.ttf",
            "Libertinus Keyboard": "LibertinusKeyboard-Regular.ttf",
            "Libre Barcode 39 Text": "LibreBarcode39Text-Regular.ttf",
            "Roboto": "Roboto-Black.ttf",
            "Silkscreen": "Silkscreen-Regular.ttf",
            "Story Script": "StoryScript-Regular.ttf",
            "Trade Winds": "TradeWinds-Regular.ttf"
        }
        font_family = params.get('fontFamily', 'Roboto')
        font_filename = font_map.get(font_family, "Roboto-Black.ttf")
        # Create the full, absolute path to the font file.
        font_file_path = os.path.join(shared_fonts_dir, font_filename)
        
        if not os.path.exists(font_file_path):
             raise FileNotFoundError(f"Font file not found at calculated path: {font_file_path}")
        
        # Escape the absolute font path for the FFmpeg filter.
        escaped_font_path = font_file_path.replace('\\', '/').replace(':', '\\:')

        # --- Build Filter Stage (-vf) for drawtext ---
        escaped_text = text_content.replace("'", "'\\''").replace(":", "\\:")

        position_map = {
            "topLeft": "x=10:y=10", "topCenter": "x=(w-text_w)/2:y=10", "topRight": "x=w-text_w-10:y=10",
            "middleLeft": "x=10:y=(h-text_h)/2", "middleCenter": "x=(w-text_w)/2:y=(h-text_h)/2", "middleRight": "x=w-text_w-10:y=(h-text_h)/2",
            "bottomLeft": "x=10:y=h-text_h-10", "bottomCenter": "x=(w-text_w)/2:y=h-text_h-10", "bottomRight": "x=w-text_w-10:y=h-text_h-10",
            "top": "x=(w-text_w)/2:y=h*0.1", "middle": "x=(w-text_w)/2:y=(h-text_h)/2", "bottom": "x=(w-text_w)/2:y=h*0.9-text_h"
        }
        
        aspect_ratio = params.get('aspectRatio', '9:16')
        use_custom_coords = params.get('useCustomCoordinates', False)

        if use_custom_coords:
            x = params.get('xCoordinate', 0)
            y = params.get('yCoordinate', 0)
            position_expr = f"x={x}:y={y}"
        else:
            position_key = params.get('presetPositionPortrait', 'middle') if aspect_ratio == '9:16' else params.get('presetPositionLandscape', 'middleCenter')
            position_expr = position_map.get(position_key, "x=(w-text_w)/2:y=(h-text_h)/2")

        drawtext_filter = (
            f"drawtext="
            f"fontfile='{escaped_font_path}':" # Use the absolute path here
            f"text='{escaped_text}':"
            f"enable='between(t,{start_time},{end_time})':"
            f"fontcolor={hex_to_ffmpeg_color(params.get('fontColor', '#FFFFFF'))}:"
            f"fontsize={params.get('fontSize', 72)}:"
            f"bordercolor={hex_to_ffmpeg_color(params.get('fontOutlineColor', '#000000'))}:"
            f"borderw={params.get('outlineThickness', 3)}:"
            f"{position_expr}"
        )
        
        command.extend(['-vf', drawtext_filter])

        # --- Build Output Stage ---
        if is_transparent:
            command.extend(['-c:v', 'qtrle'])
        else:
            command.extend(['-c:v', 'libx264', '-c:a', 'copy', '-pix_fmt', 'yuv420p'])

        command.append(output_path)

        # --- Execute Command ---
        is_windows = sys.platform == "win32"
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows)
        
        print(json.dumps({"output_file_path": output_path, "stdout": result.stdout}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command)}))
        sys.exit(1)

if __name__ == '__main__':
    main()
