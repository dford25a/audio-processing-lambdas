#!/usr/bin/env bash
# NOTE: this script was an experimental Docker-based FAISS layer builder and is no longer used
# in the current workflow. Use build_faiss_layer.sh instead.
set -euo pipefail

# Build the FAISS dependencies layer inside the official AWS Lambda Python 3.11 image
# Ensures wheels are compatible with Lambda runtime (glibc/manylinux)

IMAGE="public.ecr.aws/lambda/python:3.11"
LAYER_BUILD_DIR="faiss_dependencies_layer_build"
SITE_PACKAGES_DIR="python/lib/python3.11/site-packages"
OUTPUT_ZIP="faiss_dependencies_layer.zip"

# Clean previous artifacts
rm -rf "${LAYER_BUILD_DIR}" "${OUTPUT_ZIP}"

# Use Docker to build the layer
docker run --rm \
  --platform linux/amd64 \
  -v "$(pwd)":/workspace \
  -w /workspace \
  --entrypoint /bin/bash \
  ${IMAGE} \
  -lc "\
    set -euo pipefail && \
    python -m pip install --upgrade pip && \
    mkdir -p ${LAYER_BUILD_DIR}/${SITE_PACKAGES_DIR} && \
    # Install numpy first (faiss needs it)
    pip install -t ${LAYER_BUILD_DIR}/${SITE_PACKAGES_DIR} numpy && \
    pip install -t ${LAYER_BUILD_DIR}/${SITE_PACKAGES_DIR} faiss-cpu && \
    cd ${LAYER_BUILD_DIR} && \
    python -m zipfile -c ../${OUTPUT_ZIP} python && \
    cd /workspace && \
    python - <<'PY'
import os
import sys
layer_root = os.path.join('faiss_dependencies_layer_build','python','lib','python3.11','site-packages')
faiss_dir = os.path.join(layer_root,'faiss')
print('faiss dir exists:', os.path.isdir(faiss_dir))
print('numpy present:', os.path.isdir(os.path.join(layer_root,'numpy')))
PY
  "

echo "Built ${OUTPUT_ZIP}. Copy it into terraform/application/ and re-apply."
