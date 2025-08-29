import sys
import json
import os
import tempfile
import whisper
import subprocess
import warnings

# Suppress verbose warnings from libraries like librosa, often used by Whisper
warnings.filterwarnings("ignore", category=FutureWarning)

def convert_to_audio(input_path, temp_files_list):
    """
    Converts any media file (video or audio) into a 16kHz mono WAV audio file,
    which is the standard format required by Whisper for optimal performance.

    Args:
        input_path (str): The path to the input media file.
        temp_files_list (list): A list to keep track of temporary files for cleanup.

    Returns:
        str: The path to the converted WAV audio file.
    """
    # Create a temporary file path for the WAV output in a known temp directory
    temp_dir = os.path.join(os.getcwd(), 'temp', 'input')
    os.makedirs(temp_dir, exist_ok=True)
    output_wav_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav", dir=temp_dir).name
    temp_files_list.append(output_wav_path)

    try:
        # Use FFmpeg to perform the conversion.
        # -y: Overwrite output file if it exists.
        # -i: Specify the input file.
        # -vn: Disable video stream, extracting only audio.
        # -acodec pcm_s16le: Set audio codec to 16-bit PCM for compatibility.
        # -ar 16000: Resample audio to 16kHz.
        # -ac 1: Convert audio to mono.
        command = ['ffmpeg', '-y', '-i', input_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', output_wav_path]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(f"FFmpeg conversion failed. Ensure FFmpeg is installed and in your system's PATH. Error: {e}") from e

    return output_wav_path

def format_output(result, detail_level):
    """
    Formats the raw Whisper transcription result based on the user's requested detail level.
    """
    if detail_level == 'text_only':
        return {"transcription": result.get("text")}
    elif detail_level == 'segment_timestamps':
        return {
            "transcription": result.get("text"),
            "language": result.get("language"),
            "segments": result.get("segments"),
        }
    elif detail_level == 'word_timestamps':
        # For word-level timestamps, the entire rich result object is valuable.
        return result
    else:
        # Default to a safe, informative format if the detail level is unrecognized.
        return {
            "transcription": result.get("text"),
            "language": result.get("language"),
            "segments": result.get("segments"),
        }

def main():
    output_json = {}
    temp_files_to_clean = []
    output_file_path = ''

    try:
        if len(sys.argv) < 2:
            raise ValueError("Path to input JSON configuration file is missing.")
        input_json_path = sys.argv[1]

        with open(input_json_path, 'r', encoding='utf-8') as f:
            params = json.load(f)

        input_file_path = params.get("input_file_path")
        if not input_file_path or not os.path.exists(input_file_path):
            raise FileNotFoundError(f"Input file not found at: {input_file_path}")

        # Convert the source media to a Whisper-compatible audio file
        audio_path = convert_to_audio(input_file_path, temp_files_to_clean)

        # Load the specified Whisper model (will be downloaded and cached on first use)
        model = whisper.load_model(params.get("model", "base"))

        # Prepare the options for the transcription process
        transcribe_options = {
            "task": params.get("task", "transcribe"),
            "word_timestamps": params.get("output_detail") == 'word_timestamps',
            "fp16": False  # Set to False for broad compatibility, especially on CPU
        }
        
        # Add optional parameters only if they have been provided by the user
        if params.get("language"):
            transcribe_options["language"] = params["language"]
        if params.get("initial_prompt") is not None:
            transcribe_options["initial_prompt"] = params["initial_prompt"]
        if params.get("temperature") is not None:
            transcribe_options["temperature"] = params["temperature"]
        if params.get("beam_size") is not None and params["beam_size"] > 0:
            transcribe_options["beam_size"] = params["beam_size"]
        if params.get("aggressive_vad"):
            transcribe_options["no_speech_threshold"] = 0.4  # Default is ~0.6; lower is more aggressive

        # Perform the core transcription task
        result = model.transcribe(audio_path, **transcribe_options)

        # Format the result into the desired structure
        final_data = format_output(result, params.get("output_detail"))

        output_json = {"status": "success", "data": final_data}

    except Exception as e:
        # If any error occurs, create a standardized error object
        output_json = {"status": "error", "message": f"An error occurred in the Python script: {str(e)}"}

    finally:
        # Create a temporary directory for the output if it doesn't exist
        temp_output_dir = os.path.join(os.getcwd(), 'temp', 'output')
        os.makedirs(temp_output_dir, exist_ok=True)
        
        # Write the final JSON object (either success or error) to a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, mode='w', suffix=".json", dir=temp_output_dir, encoding='utf-8')
        output_file_path = temp_file.name
        with temp_file as f:
            json.dump(output_json, f, indent=4)

        # Clean up the intermediate WAV file
        for f in temp_files_to_clean:
            if os.path.exists(f):
                os.unlink(f)
        
        # Print the path of the final output JSON file to stdout.
        # This is the only output the TypeScript node will see.
        print(output_file_path)

if __name__ == "__main__":
    main()
