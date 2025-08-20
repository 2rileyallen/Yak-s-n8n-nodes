import sys
sys.path.append('.') 

print("--- Importing app.py and loading all models... ---")
# Import BOTH the check_video and inference functions
from app import check_video, inference
print("--- Models loaded successfully. ---")


# --- DEFINE YOUR FILE PATHS HERE ---
# IMPORTANT: Use the 'r' before the string to handle Windows backslashes correctly.
audio_file_path = r"C:\Users\2rile\OneDrive\Documents\Sound Recordings\Riley's Voice.m4a"
video_file_path = r"C:\Users\2rile\Videos\ComfyUI Videos\T2V_14B_wan2.2_480x480_5seconds_4steps_00010.mp4"
# --- END OF FILE PATHS ---


print("\n--- Step 1: Pre-processing video (matching the UI's behavior) ---")
processed_video_path = check_video(video_file_path)
print(f"Video pre-processed and saved to: {processed_video_path}")


print("\n--- Step 2: Starting MuseTalk Inference ---")
print(f"Audio Input: {audio_file_path}")
print(f"Processed Video Input: {processed_video_path}")

try:
    # Call the inference function, but use the PROCESSED video path as input
    result_video, result_text = inference(
        audio_path=audio_file_path,
        video_path=processed_video_path, # Use the new path here
        bbox_shift=0,
        extra_margin=10,
        parsing_mode="jaw",
        left_cheek_width=90,
        right_cheek_width=90
    )

    print("\n--- Inference Successful! ---")
    print(f"Generated video saved at: {result_video}")
    print(f"Information: {result_text}")

except Exception as e:
    print(f"\n--- An Error Occurred During Inference ---")
    print(e)
    import traceback
    traceback.print_exc()