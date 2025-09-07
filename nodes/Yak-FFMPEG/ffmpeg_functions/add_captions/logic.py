import sys
import json
import subprocess
import os
import tempfile
import math
import platform

# Pillow is required for measuring text width and drawing shapes.
# You can install it with: pip install Pillow
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print(json.dumps({"error": "Pillow library not found. Please install it using: pip install Pillow"}))
    sys.exit(1)

def find_word_list(data):
    """
    Finds the word list whether it's a direct list of objects
    or nested inside a standard Whisper JSON structure.
    """
    if isinstance(data, list) and data:
        first_item = data[0]
        if isinstance(first_item, dict) and 'word' in first_item and 'start' in first_item and 'end' in first_item:
            return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        for segment in data[0].get('segments', []):
            words = segment.get('words')
            if isinstance(words, list) and words and 'word' in words[0]:
                return words
    return None

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

def hex_to_rgba(hex_color, alpha=1.0):
    """Converts #RRGGBB to an (R, G, B, A) tuple for Pillow."""
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    a = int(alpha * 255)
    return (r, g, b, a)

def hex_to_ffmpeg_color(hex_color):
    """Converts #RRGGBB to 0xRRGGBB for FFmpeg's drawbox filter."""
    return f"0x{hex_color.lstrip('#')}"

def get_total_duration(words):
    """Gets the end time of the last word in the list."""
    return math.ceil(words[-1]['end']) if words else 0

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Expected a single argument: path to parameters JSON."}))
        sys.exit(1)

    params_path = sys.argv[1]
    temp_files = []
    command_for_error_logging = []
    try:
        with open(params_path, 'r', encoding='utf-8') as f:
            params = json.load(f)

        command = ['ffmpeg', '-y']
        
        transcription_data_raw = params.get('transcriptionData')
        word_list = find_word_list(json.loads(transcription_data_raw) if isinstance(transcription_data_raw, str) else transcription_data_raw)
        if not word_list:
            raise ValueError("Could not find a valid word list in the Transcription Data.")

        # (FIX) Sanitize the word list at the beginning to remove apostrophes.
        for word_data in word_list:
            if 'word' in word_data and isinstance(word_data['word'], str):
                word_data['word'] = word_data['word'].replace("'", "")

        is_transparent = params.get('outputAsTransparentOverlay', True)
        max_words = int(params.get('maxWordsPerLine', 7))

        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')
        output_path = os.path.join(output_dir, f"{output_base_name}.{'mov' if is_transparent else 'mp4'}")
        
        if is_transparent:
            width = params.get('videoWidth', 1080)
            height = params.get('videoHeight', 1920)
            duration = get_total_duration(word_list)
            command.extend(['-f', 'lavfi', '-i', f'color=c=black@0.0:s={width}x{height}:d={duration}'])
        else:
            input_video = params.get('inputVideoFilePath')
            if not input_video or not os.path.exists(input_video):
                raise ValueError("Input video path is required for burn-in mode.")
            command.extend(['-i', input_video])
            width, height = get_video_dimensions(input_video)
        
        # --- FONT LOGIC ---
        script_dir = os.path.dirname(os.path.abspath(__file__))
        fonts_dir = os.path.abspath(os.path.join(script_dir, '..', '_shared', 'text_effects', 'fonts'))
        font_map = {
            "anton": "Anton-Regular.ttf", "asimovian": "Asimovian-Regular.ttf", "bebasNeue": "BebasNeue-Regular.ttf",
            "caprasimo": "Caprasimo-Regular.ttf", "libertinusKeyboard": "LibertinusKeyboard-Regular.ttf",
            "libreBarcode": "LibreBarcode39Text-Regular.ttf", "roboto": "Roboto-Black.ttf",
            "silkscreen": "Silkscreen-Regular.ttf", "storyScript": "StoryScript-Regular.ttf", "tradeWinds": "TradeWinds-Regular.ttf"
        }
        selected_font_value = params.get('fontFamily', 'roboto')
        font_filename = font_map.get(selected_font_value, font_map['roboto'])
        font_file_path = os.path.join(fonts_dir, font_filename)
        if not os.path.exists(font_file_path):
            raise FileNotFoundError(f"Font file not found: {font_file_path}")
        escaped_font_path = font_file_path.replace('\\', '/').replace(':', '\\:')
        font_size = params.get('fontSize', 48)
        font = ImageFont.truetype(font_file_path, font_size)

        # --- BACKGROUND SETTINGS ---
        enable_background = params.get('enableBackground', False)
        bg_color = params.get('backgroundColor', '#000000')
        bg_padding = params.get('backgroundPadding', 10)
        bg_opacity = params.get('backgroundOpacity', 0.8)
        use_rounded_corners = params.get('useRoundedCorners', True)
        corner_radius = 15

        # --- BUILD FILTER CHAIN ---
        max_text_width = width * 0.9
        all_filters = []
        last_video_stream = "0:v"
        
        caption_chunks = [word_list[i:i + max_words] for i in range(0, len(word_list), max_words)]

        if enable_background and use_rounded_corners:
            # Generate all PNGs first and add them as inputs
            for i, chunk in enumerate(caption_chunks):
                original_text = " ".join(w['word'].strip() for w in chunk)
                lines = wrap_text_into_lines(original_text, font, max_text_width)
                for j, line_text in enumerate(lines):
                    line_width = font.getbbox(line_text)[2]
                    line_height = font.getbbox("Agh")[3] - font.getbbox("Agh")[1]
                    box_width = line_width + (bg_padding * 2)
                    box_height = line_height + (bg_padding * 2)
                    
                    img = Image.new('RGBA', (int(box_width), int(box_height)), (0, 0, 0, 0))
                    draw = ImageDraw.Draw(img)
                    rgba_color = hex_to_rgba(bg_color, bg_opacity)
                    draw.rounded_rectangle([(0, 0), (box_width, box_height)], radius=corner_radius, fill=rgba_color)
                    
                    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_img:
                        img.save(temp_img, 'PNG')
                        temp_img_path = temp_img.name
                        temp_files.append(temp_img_path)
                    
                    command.extend(['-i', temp_img_path])

        # --- Build the actual filter string ---
        input_count = 1 # Start at 1 because 0 is the video
        for i, chunk in enumerate(caption_chunks):
            start_time = chunk[0]['start']
            end_time = chunk[-1]['end']
            original_text = " ".join(w['word'].strip() for w in chunk)
            lines = wrap_text_into_lines(original_text, font, max_text_width)
            
            line_height = font.getbbox("Agh")[3] - font.getbbox("Agh")[1]
            total_text_height = len(lines) * line_height
            
            position_key = params.get('presetPositionPortrait', 'bottom')
            if position_key == 'top': center_y = height / 6
            elif position_key == 'middle': center_y = height / 2
            else: center_y = 5 * height / 6
            start_y = center_y - (total_text_height / 2)

            # Layer backgrounds first
            if enable_background:
                for j, line_text in enumerate(lines):
                    line_width = font.getbbox(line_text)[2]
                    line_y_pos = start_y + (j * line_height)
                    box_width = line_width + (bg_padding * 2)
                    box_height = line_height + (bg_padding * 2)
                    box_x = (width / 2) - (box_width / 2)
                    box_y = line_y_pos - bg_padding

                    next_stream_name = f"v_bg_{i}_{j}"
                    if use_rounded_corners:
                        overlay_filter = f"[{last_video_stream}][{input_count}:v]overlay={box_x}:{box_y}:enable='between(t,{start_time},{end_time})'[{next_stream_name}]"
                        input_count += 1
                    else:
                        overlay_filter = f"[{last_video_stream}]drawbox=x={box_x}:y={box_y}:w={box_width}:h={box_height}:color={hex_to_ffmpeg_color(bg_color)}@{bg_opacity}:t=fill:enable='between(t,{start_time},{end_time})'[{next_stream_name}]"
                    
                    all_filters.append(overlay_filter)
                    last_video_stream = next_stream_name

            # Layer text on top
            for j, line_text in enumerate(lines):
                line_y_pos = start_y + (j * line_height)
                escaped_text = line_text.replace(":", "\\:").replace(",", "\\,")
                
                next_stream_name = f"v_txt_{i}_{j}"
                text_filter = (
                    f"[{last_video_stream}]drawtext=fontfile='{escaped_font_path}':text='{escaped_text}':"
                    f"enable='between(t,{start_time},{end_time})':"
                    f"fontcolor={params.get('fontColor', '#FFFFFF')}:fontsize={font_size}:"
                    f"bordercolor={params.get('fontOutlineColor', '#000000')}:borderw={params.get('outlineThickness', 2)}:"
                    f"x=(w-text_w)/2:y={line_y_pos}[{next_stream_name}]"
                )
                all_filters.append(text_filter)
                last_video_stream = next_stream_name
        
        # --- CREATE AND USE FILTER SCRIPT ---
        final_filter_chain = ";".join(all_filters)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as temp_filter_file:
            temp_filter_file.write(final_filter_chain)
            temp_filter_path = temp_filter_file.name
            temp_files.append(temp_filter_path)
        
        command.extend(['-filter_complex_script', temp_filter_path])
        
        # --- OUTPUT MAPPING & CODECS ---
        command.extend(['-map', f"[{last_video_stream}]"])
        if not is_transparent:
            command.extend(['-map', '0:a?'])
        
        if is_transparent:
            command.extend(['-c:v', 'qtrle'])
        else:
            command.extend(['-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p'])

        command.append(output_path)
        command_for_error_logging = command
        
        is_windows = platform.system() == "Windows"
        result = subprocess.run(command, check=True, capture_output=True, text=True, shell=is_windows)
        
        print(json.dumps({"output_file_path": output_path, "stdout": result.stdout}))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_message = f"FFmpeg command failed. Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        safe_command_str = " ".join(map(str, command_for_error_logging))
        print(json.dumps({"error": error_message, "command": safe_command_str}))
        sys.exit(1)
    finally:
        for f in temp_files:
            try:
                os.remove(f)
            except OSError:
                pass

if __name__ == '__main__':
    main()

