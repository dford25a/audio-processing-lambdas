FROM public.ecr.aws/lambda/python:3.10

# Install system dependencies
RUN yum update -y && \
    yum install -y git wget tar xz ffmpeg && \
    yum clean all # It's good practice to clean yum cache

# Install Python dependencies
# Explicitly install NumPy < 2.0 before other packages that depend on it
RUN pip install --no-cache-dir numpy"<2.0"

# Install faster-whisper (it will use the already installed NumPy 1.x)
RUN pip install --no-cache-dir faster-whisper

# setuptools-rust might be needed by a sub-dependency (e.g., tokenizers)
RUN pip install --no-cache-dir setuptools-rust

# Your application code
COPY app.py ${LAMBDA_TASK_ROOT}/

# Set the CMD to your handler
CMD [ "app.handler" ]