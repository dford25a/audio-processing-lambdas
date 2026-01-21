# syntax=docker/dockerfile:1
#
# Speaker Diarization Lambda Container
# Uses Faster-Whisper (int8) + Pyannote.audio for diarization
# Architecture: ARM64 (Graviton2) for cost savings
#

# Use the official AWS Lambda Python 3.10 base image for ARM64
FROM public.ecr.aws/lambda/python:3.10-arm64

# Install system dependencies using yum (Amazon Linux 2)
# - wget/tar/bzip2: for downloading and extracting models
# - xz: for extracting ffmpeg static build
# - libsndfile: required for soundfile
# - gcc/gcc-c++/make: required for building matplotlib and other packages
RUN yum update -y && \
    yum install -y wget tar bzip2 xz libsndfile git gcc gcc-c++ make && \
    yum clean all && \
    rm -rf /var/cache/yum

# Install ffmpeg from static build (not in Amazon Linux repos)
RUN wget -q https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz && \
    tar xf ffmpeg-release-arm64-static.tar.xz && \
    mv ffmpeg-*-arm64-static/ffmpeg /usr/local/bin/ && \
    mv ffmpeg-*-arm64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-*

# Install PyTorch CPU-only (ARM64)
# Using the lightweight CPU-only version to minimize size
RUN pip install --no-cache-dir \
    torch==2.1.2 --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies
# Key packages:
# - faster-whisper: Lightweight transcription with int8 quantization
# - pyannote.audio: Speaker diarization (PyTorch-based)
# - soundfile: Audio file I/O
# - numpy: Numerical operations
# - boto3: AWS SDK
RUN pip install --no-cache-dir \
    "numpy<2.0" \
    "huggingface-hub>=0.21,<0.25" \
    "faster-whisper>=1.0.0,<1.1.0" \
    "pyannote.audio>=3.1.0" \
    "soundfile>=0.12.0" \
    "boto3>=1.34.0"

# --- Model Cache Directories ---
ENV FASTER_WHISPER_CACHE_DIR="/opt/models/faster-whisper"
ENV HF_HOME="/opt/models/huggingface"

# Create model directories
RUN mkdir -p ${FASTER_WHISPER_CACHE_DIR} ${HF_HOME}

# --- Download Faster-Whisper Model ---
# Pre-download the small.en model with int8 quantization
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8', download_root='${FASTER_WHISPER_CACHE_DIR}')"

# Note: Pyannote models require HuggingFace token and will be downloaded at runtime
# Set HF_TOKEN environment variable in Lambda configuration

# Copy application code
WORKDIR ${LAMBDA_TASK_ROOT}
COPY app.py ${LAMBDA_TASK_ROOT}/

# Lambda handler
CMD ["app.handler"]
