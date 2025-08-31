import sys
import json
import subprocess
import os
import tempfile
import platform

# Pillow is required for measuring text width.
# You can install it with: pip install Pillow
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print(json.dumps({"error": "Pillow library not found. Please install it using: pip install Pillow"}))
    sys.exit(1)

def get_video_dimensions(video_path):
    """Gets the width and height of a video file using ffprobe."""
    try:
        command = [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'json', video_path
        ]
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        video_info = json.loads(result.stdout)
        width = video_info['streams'][0]['width']
        height = video_info['streams'][0]['height']
        return width, height
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, IndexError) as e:
        raise ValueError(f"Failed to get video dimensions from {video_path}: {e}")

def wrap_text_into_lines(text, font, max_width):
    """Wraps text to fit a maximum width, returning a list of strings (lines)."""
    lines = []
    words = text.split()
    if not words:
        return []

    current_line = words[0]
    for word in words[1:]:
        if font.getbbox(current_line + " " + word)[2] <= max_width:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

def hex_to_ffmpeg_color(hex_color):
    """Converts a #RRGGBB hex color to FFmpeg's 0xRRGGBB format."""
    return f"0x{hex_color[1:]}" if hex_color.startswith('#') else hex_color

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Expected a single argument: path to parameters JSON."}))
        sys.exit(1)

    params_path = sys.argv[1]
    temp_files = []
    try:
        with open(params_path, 'r', encoding='utf-8') as f:
            params = json.load(f)

        command = ['ffmpeg', '-y']
        
        # --- Get Core Parameters ---
        is_transparent = params.get('outputAsTransparentOverlay', True)
        text_content = params.get('textContent', '')
        if not text_content:
            raise ValueError("Text Content cannot be empty.")
        
        start_time = params.get('startTime', 0)
        end_time = params.get('endTime', 5)
        if start_time >= end_time:
            raise ValueError("End Time must be greater than Start Time.")

        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')
        output_path = os.path.join(output_dir, f"{output_base_name}.{'mov' if is_transparent else 'mp4'}")

        # --- INPUT SETUP ---
        if is_transparent:
            width = params.get('videoWidth', 1080)
            height = params.get('videoHeight', 1920)
            duration = end_time
            command.extend(['-f', 'lavfi', '-i', f'color=c=black@0.0:s={width}x{height}:d={duration}'])
            input_stream_specifier = "[0:v]"
        else:
            input_video = params.get('inputVideoFilePath')
            if not input_video or not os.path.exists(input_video):
                raise ValueError("Input video path is required for burn-in mode.")
            command.extend(['-i', input_video])
            width, height = get_video_dimensions(input_video)
            input_stream_specifier = "[0:v]"

        # --- FONT LOGIC ---
        script_dir = os.path.dirname(os.path.abspath(__file__))
        fonts_dir = os.path.abspath(os.path.join(script_dir, '..', '_shared', 'text_effects', 'fonts'))
        font_map = {
            "Anton": "Anton-Regular.ttf", "Asimovian": "Asimovian-Regular.ttf", "Bebas Neue": "BebasNeue-Regular.ttf",
            "Caprasimo": "Caprasimo-Regular.ttf", "Libertinus Keyboard": "LibertinusKeyboard-Regular.ttf",
            "Libre Barcode 39 Text": "LibreBarcode39Text-Regular.ttf", "Roboto": "Roboto-Black.ttf",
            "Silkscreen": "Silkscreen-Regular.ttf", "Story Script": "StoryScript-Regular.ttf", "Trade Winds": "TradeWinds-Regular.ttf"
        }
        selected_font_value = params.get('fontFamily', 'Roboto')
        font_filename = font_map.get(selected_font_value, font_map['Roboto'])
        font_file_path = os.path.join(fonts_dir, font_filename)
        if not os.path.exists(font_file_path):
            raise FileNotFoundError(f"Font file not found: {font_file_path}")
        escaped_font_path = font_file_path.replace('\\', '/').replace(':', '\\:')
        font_size = params.get('fontSize', 72)
        font = ImageFont.truetype(font_file_path, font_size)

        # --- BACKGROUND SETTINGS ---
        enable_background = params.get('enableBackground', False)
        bg_color = params.get('backgroundColor', '#000000')
        bg_padding = params.get('backgroundPadding', 10)

        # --- WRAP AND POSITION TEXT ---
        max_text_width = width * 0.9
        lines = wrap_text_into_lines(text_content, font, max_text_width)
        
        line_height = font.getbbox("Agh")[3] - font.getbbox("Agh")[1]
        total_text_height = len(lines) * line_height

        aspect_ratio = params.get('aspectRatio', '9:16')
        use_custom_coords = params.get('useCustomCoordinates', False)
        
        all_filters = []
        
        if use_custom_coords:
            start_y = params.get('yCoordinate', 10)
            box_filters = []
            text_filters = []
            for j, line_text in enumerate(lines):
                line_y_pos = start_y + (j * line_height)
                line_width = font.getbbox(line_text)[2]
                if enable_background:
                    box_width = line_width + (bg_padding * 2)
                    box_height = line_height + (bg_padding * 2)
                    box_x = params.get('xCoordinate', 10) - bg_padding
                    box_y = line_y_pos - bg_padding
                    box_filter = (f"drawbox=x={box_x}:y={box_y}:w={box_width}:h={box_height}:"
                                  f"color={hex_to_ffmpeg_color(bg_color)}@0.8:t=fill:"
                                  f"enable='between(t,{start_time},{end_time})'")
                    box_filters.append(box_filter)

                escaped_text = line_text.replace("'", "'\\''").replace(":", "\\:").replace(",", "\\,")
                text_filter = (f"drawtext=fontfile='{escaped_font_path}':text='{escaped_text}':enable='between(t,{start_time},{end_time})':"
                            f"fontcolor={hex_to_ffmpeg_color(params.get('fontColor', '#FFFFFF'))}:fontsize={font_size}:"
                            f"bordercolor={hex_to_ffmpeg_color(params.get('fontOutlineColor', '#000000'))}:borderw={params.get('outlineThickness', 3)}:"
                            f"x={params.get('xCoordinate', 10)}:y={line_y_pos}")
                text_filters.append(text_filter)
            all_filters.extend(box_filters)
            all_filters.extend(text_filters)
        else:
            position_key = params.get('presetPositionPortrait', 'middle') if aspect_ratio == '9:16' else params.get('presetPositionLandscape', 'middleCenter')
            
            if "top" in position_key.lower(): center_y = height / 6
            elif "middle" in position_key.lower(): center_y = height / 2
            else: center_y = 5 * height / 6
            
            start_y = center_y - (total_text_height / 2)
            
            box_filters = []
            text_filters = []
            for j, line_text in enumerate(lines):
                line_y_pos = start_y + (j * line_height)
                line_width = font.getbbox(line_text)[2]

                if "left" in position_key.lower(): x_expr = "10"
                elif "right" in position_key.lower(): x_expr = f"w-({line_width})-10"
                else: x_expr = f"(w-{line_width})/2"

                if enable_background:
                    box_width = line_width + (bg_padding * 2)
                    box_height = line_height + (bg_padding * 2)
                    if "left" in position_key.lower(): box_x = 10 - bg_padding
                    elif "right" in position_key.lower(): box_x = width - line_width - 10 - bg_padding
                    else: box_x = (width / 2) - (box_width / 2)
                    box_y = line_y_pos - bg_padding
                    box_filter = (f"drawbox=x={box_x}:y={box_y}:w={box_width}:h={box_height}:"
                                  f"color={hex_to_ffmpeg_color(bg_color)}@1.0:t=fill:"
                                  f"enable='between(t,{start_time},{end_time})'")
                    box_filters.append(box_filter)

                escaped_text = line_text.replace("'", "'\\''").replace(":", "\\:").replace(",", "\\,")
                text_filter = (f"drawtext=fontfile='{escaped_font_path}':text='{escaped_text}':enable='between(t,{start_time},{end_time})':"
                            f"fontcolor={hex_to_ffmpeg_color(params.get('fontColor', '#FFFFFF'))}:fontsize={font_size}:"
                            f"bordercolor={hex_to_ffmpeg_color(params.get('fontOutlineColor', '#000000'))}:borderw={params.get('outlineThickness', 3)}:"
                            f"x={x_expr}:y={line_y_pos}")
                text_filters.append(text_filter)
            all_filters.extend(box_filters)
            all_filters.extend(text_filters)

        # --- CREATE AND USE FILTER SCRIPT ---
        filter_chain = f"{input_stream_specifier}{','.join(all_filters)}[outv]"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as temp_filter_file:
            temp_filter_file.write(filter_chain)
            temp_filter_path = temp_filter_file.name
            temp_files.append(temp_filter_path)
        
        command.extend(['-filter_complex_script', temp_filter_path])
        
        # --- OUTPUT MAPPING & CODECS ---
        command.extend(['-map', '[outv]'])
        if not is_transparent:
            command.extend(['-map', '0:a?'])
        
        if is_transparent:
            command.extend(['-c:v', 'qtrle'])
        else:
            command.extend(['-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p'])

        command.append(output_path)
        
        is_windows = platform.system() == "Windows"
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows)
        
        print(json.dumps({"output_file_path": output_path, "stdout": result.stdout}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        print(json.dumps({"error": error_message, "command": " ".join(command)}))
        sys.exit(1)
    finally:
        for f in temp_files:
            try:
                os.remove(f)
            except OSError:
                pass

if __name__ == '__main__':
    main()

