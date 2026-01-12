# syntax=docker/dockerfile:1

# We use a Debian base so that ffmpeg + development headers are available,
# then run on Lambda using the AWS Lambda Runtime Interface Client (RIC).
#
# Docs: https://docs.aws.amazon.com/lambda/latest/dg/images-create.html

# --- Builder stage ---
FROM python:3.10-slim-bookworm AS builder

ENV DEBIAN_FRONTEND=noninteractive

# System deps needed for:
# - ffmpeg runtime + headers (for PyAV)
# - compiling wheels where needed
# - git (some deps may fetch from VCS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    pkg-config \
    gcc \
    g++ \
    git \
  && rm -rf /var/lib/apt/lists/*

# Upgrade pip tooling
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install PyTorch CPU wheels directly to system Python
RUN pip install --no-cache-dir \
    torch==2.1.0+cpu torchaudio==2.1.0+cpu --index-url https://download.pytorch.org/whl/cpu

# Install whisperx + diarization deps directly to system Python
# Pin av to a version that provides prebuilt wheels to avoid compiling.
# (Compiling av is slow and can require extra toolchains.)
RUN pip install --no-cache-dir \
    "numpy<2.0" \
    "onnxruntime==1.16.3" \
    "av==11.0.0" \
    "whisperx==3.1.5" \
    "pyannote.audio>=3.1" \
    boto3 \
    awslambdaric

# --- Runtime stage ---
FROM python:3.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive

# ffmpeg runtime is required because your handler loads audio from mp3/etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
  && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder (system site-packages)
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Set cache directories to a location in the image (read-only at runtime)
ENV HF_HOME="/usr/local/huggingface-cache"
ENV WHISPERX_CACHE_DIR="/usr/local/whisperx-models-cache"

# Create cache directories
RUN mkdir -p ${HF_HOME} ${WHISPERX_CACHE_DIR}

# Pre-download the faster-whisper model during build (without VAD which has URL issues)
# The VAD model will be downloaded at runtime to /tmp
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='${WHISPERX_CACHE_DIR}')"

# Copy your application code
WORKDIR /var/task
COPY app.py /var/task/app.py

# Lambda entrypoint via RIC
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["app.handler"]
