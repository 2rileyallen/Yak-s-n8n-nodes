import sys
import json
import os
import tempfile
import whisper
import warnings
import torch

# Suppress future warnings from whisper
warnings.filterwarnings("ignore", category=FutureWarning)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"status": "error", "message": "No JSON payload path provided."}), file=sys.stderr)
        sys.exit(1)

    payload_path = sys.argv[1]

    try:
        with open(payload_path, 'r') as f:
            params = json.load(f)

        # --- Extract parameters from JSON payload ---
        input_file_path = params.get("input_file_path")
        model_size = params.get("model", "base")
        task = params.get("task", "transcribe")
        language = params.get("language") or None  # Whisper expects None for auto-detect, not empty string
        output_detail = params.get("output_detail", "segment_timestamps")

        # Advanced options
        initial_prompt = params.get("initial_prompt")
        temperature = params.get("temperature", 0.0)
        beam_size = params.get("beam_size", 5)
        # We don't use aggressive_vad directly, but it informs other settings if we choose to
        # For now, it's not directly mapped to a whisper parameter.

        if not input_file_path or not os.path.exists(input_file_path):
            raise ValueError(f"Input file not found at path: {input_file_path}")

        # --- Load model and perform transcription ---
        # Check for GPU availability
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = whisper.load_model(model_size, device=device)

        # The transcribe function handles ffmpeg conversion internally
        result = model.transcribe(
            input_file_path,
            task=task,
            language=language,
            initial_prompt=initial_prompt if initial_prompt else None,
            temperature=float(temperature),
            beam_size=int(beam_size) if beam_size else None,
            word_timestamps=(output_detail == "word_timestamps")
        )

        # --- Format the output based on user's choice ---
        final_data = {}
        if output_detail == "word_timestamps":
            # This is the new logic to combine all word arrays
            all_words = []
            if result.get("segments"):
                for segment in result["segments"]:
                    if "words" in segment:
                        all_words.extend(segment["words"])
            final_data = {
                "text": result.get("text"),
                "language": result.get("language"),
                "words": all_words  # Return the single, combined list
            }
        elif output_detail == "segment_timestamps":
            final_data = {
                "text": result.get("text"),
                "language": result.get("language"),
                "segments": result.get("segments")
            }
        else:  # text_only
            final_data = {
                "text": result.get("text")
            }

        output_json = {
            "status": "success",
            "data": final_data
        }

    except Exception as e:
        output_json = {
            "status": "error",
            "message": f"An unexpected error occurred: {str(e)}"
        }

    # --- Write result to a temporary JSON file and return its path ---
    temp_dir = os.path.join(os.getcwd(), 'temp', 'output')
    os.makedirs(temp_dir, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(delete=False, mode='w', suffix='.json', dir=temp_dir, encoding='utf-8') as temp_file:
        json.dump(output_json, temp_file, indent=2, ensure_ascii=False)
        print(temp_file.name) # Return the path of the output file to stdout

if __name__ == "__main__":
    main()

