#!/usr/bin/env bash
set -euo pipefail

# Build the base Python dependencies layer inside the official AWS Lambda Python 3.11 image
# This guarantees correct manylinux wheels (including pydantic-core .so)

IMAGE="public.ecr.aws/lambda/python:3.11"
LAYER_BUILD_DIR="python_dependencies_layer_build"
SITE_PACKAGES_DIR="python/lib/python3.11/site-packages"
OUTPUT_ZIP="python_dependencies_layer.zip"

# Clean previous artifacts
rm -rf "${LAYER_BUILD_DIR}" "${OUTPUT_ZIP}"

# Use Docker to build the layer contents (no zipping inside the container)
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
    pip install -t ${LAYER_BUILD_DIR}/${SITE_PACKAGES_DIR} pydantic openai requests thefuzz
  "

# Zip the layer on the host (WSL) using the local zip binary
(
  cd "${LAYER_BUILD_DIR}" && \
  zip -r "../${OUTPUT_ZIP}" python
)

# Sanity check on host that pydantic_core .so exists in the layer
python3 - <<'PY'
import os
import sys
layer_root = os.path.join('python_dependencies_layer_build','python','lib','python3.11','site-packages')
core = os.path.join(layer_root, 'pydantic_core')
if not os.path.isdir(core):
    print('ERROR: pydantic_core package directory not found in layer at', core)
    sys.exit(2)
so_files = [f for f in os.listdir(core) if f.endswith('.so')]
print('Contents of pydantic_core:', os.listdir(core))
if not so_files:
    print('ERROR: pydantic_core shared object (.so) not found in layer!')
    sys.exit(2)
print('OK: pydantic_core .so present:', so_files)
PY

echo "Built ${OUTPUT_ZIP}. Copy it into terraform/application/ and re-apply."
