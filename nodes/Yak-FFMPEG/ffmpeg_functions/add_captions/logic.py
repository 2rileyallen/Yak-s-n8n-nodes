import sys
import json
import subprocess
import os
import re

def hex_to_ass_bgr(hex_color):
    """Converts a #RRGGBB hex color to &HBBGGRR format for ASS subtitles."""
    if hex_color.startswith('#'):
        hex_color = hex_color[1:]
    r = hex_color[0:2]
    g = hex_color[2:4]
    b = hex_color[4:6]
    # ASS format is &H00BBGGRR (Alpha=00 for opaque)
    return f"&H00{b}{g}{r}".upper()

def get_srt_duration(file_path):
    """Parses an SRT file to find the end time of the last subtitle in seconds."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Find all end timestamps (e.g., 00:01:23,456)
        timestamps = re.findall(r'\d{2}:\d{2}:\d{2},\d{3}', content)
        if not timestamps:
            raise ValueError("No valid timestamps found in the subtitle file.")

        last_timestamp = timestamps[-1]
        h, m, s, ms = map(int, re.split('[:,]', last_timestamp))
        return h * 3600 + m * 60 + s + ms / 1000.0
    except FileNotFoundError:
        raise ValueError(f"Subtitle file not found at path: {file_path}")
    except Exception as e:
        raise ValueError(f"Failed to parse subtitle file duration: {e}")


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

    command = ['ffmpeg', '-y']
    try:
        # --- Get Core Parameters ---
        is_transparent = params.get('outputAsTransparentOverlay', True)
        subtitle_file = params.get('subtitleFile')
        if not subtitle_file or not os.path.exists(subtitle_file):
            raise ValueError("Subtitle file path is required and must exist.")

        # --- Determine Output Path ---
        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')
        if not output_dir or not output_base_name:
            raise ValueError("'outputDirectory' or 'outputBaseName' not provided by the node.")

        if is_transparent:
            # Transparency requires a .mov container. We enforce this.
            output_path = os.path.join(output_dir, f"{output_base_name}.mov")
        else:
            # For burn-in, we can use a standard format like mp4.
            output_path = os.path.join(output_dir, f"{output_base_name}.mp4")

        # --- Build Input Stage ---
        if is_transparent:
            duration = get_srt_duration(subtitle_file)
            width = params.get('videoWidth', 1080)
            height = params.get('videoHeight', 1920)
            # Create a blank, transparent canvas
            command.extend([
                '-f', 'lavfi',
                '-i', f'color=c=black@0.0:s={width}x{height}:d={duration}'
            ])
        else:
            input_video = params.get('inputVideo')
            if not input_video or not os.path.exists(input_video):
                raise ValueError("Input video path is required for burn-in mode.")
            command.extend(['-i', input_video])

        # --- FONT LOGIC ---
        script_dir = os.path.dirname(os.path.abspath(__file__))
        shared_dir = os.path.join(script_dir, '..', '_shared', 'text_effects', 'fonts')

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
        font_name = font_map.get(font_family, "Roboto-Black.ttf")
        # For the subtitles filter, we just need the font name, not the full path if it's handled correctly by fontconfig.
        # However, to be robust, we will pass the font directory to FFmpeg.
        
        # --- Build Filter Stage (-vf) ---
        # Map UI position names to ASS alignment codes (numpad layout)
        position_map = {
            "topLeft": 7, "topCenter": 8, "topRight": 9,
            "middleLeft": 4, "middleCenter": 5, "middleRight": 6,
            "bottomLeft": 1, "bottomCenter": 2, "bottomRight": 3,
            "top": 8, "middle": 5, "bottom": 2
        }
        
        aspect_ratio = params.get('aspectRatio', '9:16')
        use_custom_coords = params.get('useCustomCoordinates', False)

        style_parts = []
        if use_custom_coords:
            # For custom coords, we anchor to top-left and use margins
            alignment = 7
            x = params.get('xCoordinate', 0)
            y = params.get('yCoordinate', 0)
            style_parts.extend([f'Alignment={alignment}', f'MarginL={x}', f'MarginV={y}'])
        else:
            # Use preset positions
            if aspect_ratio == '9:16':
                position_key = params.get('presetPositionPortrait', 'bottom')
            else: # 16:9
                position_key = params.get('presetPositionLandscape', 'bottomCenter')
            alignment = position_map.get(position_key, 2) # Default to bottom center
            style_parts.append(f'Alignment={alignment}')

        # Add style overrides
        style_parts.append(f"Fontname={font_family}")
        style_parts.append(f"Fontsize={params.get('fontSize', 48)}")
        style_parts.append(f"PrimaryColour={hex_to_ass_bgr(params.get('fontColor', '#FFFFFF'))}")
        style_parts.append(f"OutlineColour={hex_to_ass_bgr(params.get('fontOutlineColor', '#000000'))}")
        style_parts.append(f"Outline={params.get('outlineThickness', 2)}")
        style_parts.append("BorderStyle=1") # Enable outline

        style_string = ",".join(style_parts)
        
        # Escape characters for FFmpeg filtergraph
        subtitle_file_escaped = subtitle_file.replace('\\', '/').replace(':', '\\:')
        
        # Set the FONTCONFIG_PATH environment variable to ensure FFmpeg finds the custom fonts
        env = os.environ.copy()
        font_dir_escaped = shared_dir.replace('\\', '/')
        env['FONTCONFIG_PATH'] = font_dir_escaped

        command.extend(['-vf', f"subtitles='{subtitle_file_escaped}':force_style='{style_string}'"])

        # --- Build Output Stage ---
        if is_transparent:
            # Use a codec that supports alpha channel (transparency)
            command.extend(['-c:v', 'qtrle'])
        else:
            # Use a standard codec and copy the audio from the source
            command.extend(['-c:v', 'libx264', '-c:a', 'copy', '-pix_fmt', 'yuv420p'])

        command.append(output_path)

        # --- Execute Command ---
        is_windows = sys.platform == "win32"
        # Pass the modified environment to the subprocess
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows, env=env)
        
        print(json.dumps({"output_file_path": output_path, "stdout": result.stdout}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command)}))
        sys.exit(1)

if __name__ == '__main__':
    main()
