import sys
import json
import os
import tempfile
import torchaudio as ta
import base64
from chatterbox.tts import ChatterboxTTS
import warnings
import subprocess
from contextlib import redirect_stdout, redirect_stderr
import io
import shutil

warnings.filterwarnings("ignore", category=FutureWarning)

import torch
device = "cuda" if torch.cuda.is_available() else "cpu"


def ensure_wav(input_path: str, temp_files: list) -> str:
    """
    Ensure the given audio file is in WAV format.
    If it's not, use ffmpeg to convert to a temp wav file.
    Returns the path to the wav file.
    """
    if input_path.lower().endswith(".wav"):
        return input_path

    output_wav_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
    temp_files.append(output_wav_path)
    try:
        cmd = ["ffmpeg", "-y", "-i", input_path, output_wav_path]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(
            f"FFmpeg conversion failed for '{input_path}': {e}. Ensure FFmpeg is installed and in PATH."
        ) from e

    return output_wav_path


def convert_output_format(wav_path: str, output_path: str) -> str:
    """
    Convert a generated wav file into the user-specified output path/format.
    If no extension provided, defaults to .mp3.
    """
    base, ext = os.path.splitext(output_path)

    if not ext:  # user didn't specify extension → default to mp3
        output_path = base + ".mp3"
        ext = ".mp3"

    if ext.lower() == ".wav":
        # Already wav, just rename/move
        shutil.move(wav_path, output_path)
    else:
        # Use ffmpeg to convert wav -> desired format
        try:
            cmd = ["ffmpeg", "-y", "-i", wav_path, output_path]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            os.unlink(wav_path)
        except Exception as e:
            raise RuntimeError(f"Failed to convert output to {ext}: {e}")

    return output_path


def main():
    temp_files = []
    try:
        input_data = json.load(sys.stdin)
        mode = input_data.get("mode")
        output_file_path = input_data.get("output_file_path") or ""

        # Resolve inputs
        target_voice_path = ensure_wav(input_data.get("target_voice_path"), temp_files)
        if not target_voice_path:
            raise ValueError("A target voice file is required.")

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            model = ChatterboxTTS.from_pretrained(device=device)
            generate_kwargs = {
                "audio_prompt_path": target_voice_path,
                "exaggeration": input_data.get("exaggeration", 0.5),
                "cfg_weight": input_data.get("cfg_weight", 0.5),
            }

            if mode == "tts":
                text = input_data.get("text")
                if not text:
                    raise ValueError("Text input is required for TTS mode.")
                wav = model.generate(text, **generate_kwargs)

            elif mode == "vc":
                source_audio_path = ensure_wav(input_data.get("source_audio_path"), temp_files)
                if not source_audio_path:
                    raise ValueError("Source audio is required for VC mode.")
                wav = model.generate(source_audio_path, **generate_kwargs)

            else:
                raise ValueError(f"Invalid mode: {mode}")

        # Save to temporary wav first
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmpwav:
            ta.save(tmpwav.name, wav, model.sr)
            tmpwav_path = tmpwav.name
        temp_files.append(tmpwav_path)

        # Final conversion / move
        if not output_file_path:
            # if completely unspecified, create mp3 in temp/output
            temp_dir = os.path.join(os.getcwd(), "temp", "output")
            os.makedirs(temp_dir, exist_ok=True)
            output_file_path = os.path.join(temp_dir, f"output_{os.getpid()}.mp3")

        final_path = convert_output_format(tmpwav_path, output_file_path)

        result = {
            "status": "success",
            "message": f"Chatterbox {mode.upper()} completed.",
            "output_file_path": final_path,
        }

    except Exception as e:
        result = {"status": "error", "message": str(e)}

    finally:
        for f in temp_files:
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except Exception:
                pass

        print(json.dumps(result))


if __name__ == "__main__":
    main()