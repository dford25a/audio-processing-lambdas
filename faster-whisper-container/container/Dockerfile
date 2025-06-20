# Use the official AWS Lambda Python 3.10 base image
FROM public.ecr.aws/lambda/python:3.10

# Update yum and install necessary system dependencies in a single layer
# This includes git, wget, tar, xz, and ffmpeg (essential for audio processing)
# yum clean all is used to remove cached package data, reducing image size
RUN yum update -y && \
    yum install -y git wget tar xz ffmpeg && \
    yum clean all

# Install all Python dependencies in a single layer to optimize image size.
# --no-cache-dir prevents pip from storing a cache, further reducing size.
# Versions are pinned for stable, predictable builds.
RUN pip install --no-cache-dir \
    setuptools-rust \
    "numpy==1.26.4" \
    "onnxruntime==1.16.3" \
    "faster-whisper==0.10.0"

# --- Pre-download the faster-whisper model during the build ---

# Set the cache directory for faster-whisper within the Docker image.
# This ensures the model is looked for in the correct, pre-populated location.
ENV FASTER_WHISPER_CACHE_DIR="/usr/local/faster-whisper-models-cache"

# Create the directory where the model will be stored.
RUN mkdir -p ${FASTER_WHISPER_CACHE_DIR}

# Use a Python command to instantiate the WhisperModel, which triggers the download.
# This critical step ensures the model is baked into the image, avoiding slow
# downloads during Lambda execution and preventing "file not found" errors.
# 'device="cpu"' and 'compute_type="int8"' are optimal for a CPU-based Lambda environment.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='${FASTER_WHISPER_CACHE_DIR}')"

# Copy your application code into the Lambda task root directory
COPY app.py ${LAMBDA_TASK_ROOT}/

# Set the command for the Lambda function.
# This specifies that your 'app.py' file's 'handler' function will be executed.
CMD [ "app.handler" ]