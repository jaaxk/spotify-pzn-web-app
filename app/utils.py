# app/utils.py
import os
import requests
import tempfile
import boto3
from botocore.exceptions import ClientError
import subprocess
import numpy as np

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")



def download_preview_to_temp(preview_url):
    """Download preview URL to a local temporary file and return path"""
    r = requests.get(preview_url, stream=True, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch preview: {preview_url} status={r.status_code}")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    for chunk in r.iter_content(chunk_size=8192):
        if chunk:
            tmp.write(chunk)
    tmp.flush()
    tmp.close()
    return tmp.name

def resample_to_24k(input_path, sample_rate=24000):
    """
    Use ffmpeg to convert audio to mono and resample to specified sample rate.
    Returns numpy array of float32 samples in range [-1, 1].
    """
    # Create temporary output file
    output_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    output_path = output_tmp.name
    output_tmp.close()
    
    try:
        # ffmpeg command to convert to mono, resample, and limit to 15 seconds
        cmd = [
            "ffmpeg",
            "-i", str(input_path),  # Input file
            "-ar", str(sample_rate),  # Sample rate
            "-ac", "1",  # Mono audio
            "-f", "wav",  # Output format
            "-y",  # Overwrite output file if it exists
            "-loglevel", "warning",  # Only show warnings/errors
            str(output_path)
        ] #  "-t", "15",  # Limit to first 15 seconds
        
        # Run ffmpeg
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")
        
        # Read the WAV file using a simple WAV reader
        with open(output_path, 'rb') as f:
            # Skip WAV header (44 bytes)
            f.seek(44)
            # Read audio data
            audio_data = f.read()
        
        # Convert bytes to numpy array (16-bit PCM)
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # Convert to float32 in range [-1, 1]
        audio_float = audio_array.astype(np.float32) / 32768.0
        
        return audio_float, sample_rate
        
    finally:
        # Clean up temporary output file
        if os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except Exception as e:
                print(f"Failed to clean up temporary file {output_path}: {e}")
