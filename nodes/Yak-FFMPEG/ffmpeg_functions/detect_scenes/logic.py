import sys
import json
import subprocess
import os
import re
from datetime import timedelta

def get_video_metadata(video_path):
    """Gets video metadata using ffprobe."""
    command = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,duration,avg_frame_rate,nb_frames',
        '-of', 'json', video_path
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return json.loads(result.stdout)['streams'][0]
    except Exception:
        return {}

def seconds_to_timecode(seconds):
    """Converts seconds to HH:MM:SS.ms string format."""
    if seconds < 0:
        seconds = 0
    td = timedelta(seconds=seconds)
    minutes, seconds_val = divmod(td.seconds, 60)
    hours, minutes = divmod(minutes, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02}:{minutes:02}:{seconds_val:02}.{milliseconds:03}"

def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Expected a single argument: path to parameters JSON."}))
        sys.exit(1)

    params_path = sys.argv[1]
    command_for_error_logging = []

    try:
        with open(params_path, 'r') as f:
            params = json.load(f)

        input_video = params.get('inputVideoFilePath')
        if not input_video or not os.path.exists(input_video):
            raise ValueError("Input video path is required and was not found.")

        threshold = params.get('ffmpegThreshold', 0.4)
        min_duration = params.get('minSceneDuration', 0.25)
        output_dir = params.get('outputDirectory')
        output_base_name = params.get('outputBaseName')

        command = [
            'ffmpeg', '-i', input_video,
            '-vf', f"select='gt(scene,{threshold})',metadata=print",
            '-f', 'null', '-'
        ]
        command_for_error_logging = command
        result = subprocess.run(command, check=True, capture_output=True, text=True)

        metadata = get_video_metadata(input_video)
        duration = float(metadata.get('duration', 0))
        framerate = eval(metadata.get('avg_frame_rate', '0/1'))
        total_frames_str = metadata.get('nb_frames')
        total_frames = int(total_frames_str) if total_frames_str and total_frames_str.isdigit() else int(duration * framerate)

        # --- MODIFICATION START ---
        # Convert all timestamps to exact frame numbers first
        cut_frames = {0} # Use a set to automatically handle duplicate frames
        for line in result.stderr.splitlines():
            if 'pts_time' in line:
                match = re.search(r'pts_time:([\d.]+)', line)
                if match:
                    # Convert timestamp to frame number immediately
                    cut_frames.add(int(float(match.group(1)) * framerate))
        
        cut_frames.add(total_frames) # Add the very last frame
        sorted_cut_frames = sorted(list(cut_frames))

        scenes = []
        for i in range(len(sorted_cut_frames) - 1):
            start_f = sorted_cut_frames[i]
            # The end frame is ONE FRAME BEFORE the start of the next scene
            end_f = sorted_cut_frames[i+1] - 1

            if end_f < start_f:
                end_f = start_f

            # Now, convert the precise frame numbers back to seconds
            start_s = start_f / framerate if framerate > 0 else 0
            end_s = end_f / framerate if framerate > 0 else 0
            length_s = end_s - start_s
            # --- MODIFICATION END ---

            if length_s >= min_duration:
                scenes.append({
                    "scene_number": 0, "start_frame": start_f, "start_timecode": seconds_to_timecode(start_s),
                    "start_seconds": round(start_s, 3), "end_frame": end_f,
                    "end_timecode": seconds_to_timecode(end_s), "end_seconds": round(end_s, 3),
                    "length_frames": end_f - start_f, "length_timecode": seconds_to_timecode(length_s),
                    "length_seconds": round(length_s, 3),
                })

        for i, scene in enumerate(scenes):
            scene['scene_number'] = i + 1
        
        final_json_output = {
            "video_metadata": {
                "width": metadata.get('width'), "height": metadata.get('height'),
                "duration_seconds": duration, "frame_rate": framerate
            },
            "scene_count": len(scenes),
            "scenes": scenes
        }

        output_json_path = os.path.join(output_dir, f"{output_base_name}.json")
        with open(output_json_path, 'w') as f:
            json.dump(final_json_output, f, indent=4)

        stdout_json = {
            "status": "success",
            "message": f"Successfully processed video and found {len(scenes)} scene(s).",
            "output_file_path": output_json_path
        }
        stdout_json.update(final_json_output)
        print(json.dumps(stdout_json))

    except (subprocess.CalledProcessError, ValueError, FileNotFoundError) as e:
        error_details = f"Stderr: {e.stderr.strip()}" if hasattr(e, 'stderr') else str(e)
        error_message = f"Script failed. {error_details}"
        safe_command_str = " ".join(map(str, command_for_error_logging))
        print(json.dumps({"error": error_message, "command": safe_command_str}))
        sys.exit(1)

if __name__ == '__main__':
    main()