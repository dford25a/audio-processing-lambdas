#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
PYTHON_VERSION="3.11" # Match this to your Lambda runtime (or highest version if multiple)
PLATFORM="manylinux2014_x86_64" # For x86_64 Lambda architecture.
LAYER_NAME="stripe" # New generic name for the combined layer
SITE_PACKAGES_SUBDIR="lib/python${PYTHON_VERSION}/site-packages"
PACKAGE_INSTALL_DIR="python/${SITE_PACKAGES_SUBDIR}" # Standard path for site-packages
BUILD_DIR="./${LAYER_NAME}_layer_build" # Temporary directory for building the layer
OUTPUT_ZIP_FILE="${LAYER_NAME}_layer.zip" # New output zip file name

# --- Script Start ---
echo "Starting combined Python dependencies Lambda layer creation..."

# 1. Clean up previous build artifacts (if any)
echo "Cleaning up previous build artifacts..."
rm -rf "${BUILD_DIR}"
rm -f "${OUTPUT_ZIP_FILE}"

# 2. Create build directory and the target package installation directory
echo "Creating build directory: ${BUILD_DIR}/${PACKAGE_INSTALL_DIR}"
mkdir -p "${BUILD_DIR}/${PACKAGE_INSTALL_DIR}"

# 3. Install all dependencies into the target directory
#    - pydantic: For data validation and settings management.
#    - openai: For interacting with the OpenAI API.
#    - requests: For making HTTP requests (used in your final_summary Lambda).
echo "Installing dependencies (stripe) for Python ${PYTHON_VERSION} on ${PLATFORM}..."
pip install \
    --platform "${PLATFORM}" \
    --target "${BUILD_DIR}/${PACKAGE_INSTALL_DIR}" \
    --implementation cp \
    --python-version "${PYTHON_VERSION}" \
    --only-binary=:all: \
    --upgrade \
    stripe

# 4. Clean up unnecessary files from the package directory to reduce layer size
echo "Cleaning up unnecessary files (.pyc, __pycache__, tests, etc.)..."
# Remove .pyc files and __pycache__ directories
find "${BUILD_DIR}/python" -type f -name '*.pyc' -delete
find "${BUILD_DIR}/python" -type d -name '__pycache__' -exec rm -rf {} +
# Consider removing other non-essential files like tests, examples, if size is critical
# Example: find "${BUILD_DIR}/${PACKAGE_INSTALL_DIR}" -type d -name 'tests' -exec rm -rf {} +
# Example: find "${BUILD_DIR}/${PACKAGE_INSTALL_DIR}" -type d -name 'examples' -exec rm -rf {} +

# 5. Create the zip file
echo "Creating Lambda layer zip file: ${OUTPUT_ZIP_FILE}..."
(
  cd "${BUILD_DIR}" && \
  zip -r "../${OUTPUT_ZIP_FILE}" python # Zip the 'python' directory from BUILD_DIR
)
# The subshell and cd ensure that the paths in the zip file are relative
# to the BUILD_DIR, resulting in 'python/lib/pythonX.Y/site-packages/...' structure in the zip.

# 6. Clean up the build directory
echo "Cleaning up build directory: ${BUILD_DIR}..."
rm -rf "${BUILD_DIR}"

echo "-----------------------------------------------------------------------"
echo "Combined Python dependencies Lambda layer created successfully: ${OUTPUT_ZIP_FILE}"
echo "Ensure this zip file is in the location expected by your Terraform script."
echo "The layer includes: pydantic, openai, requests, and their dependencies."
echo "Lambda function architecture should match: ${PLATFORM}"
echo "Lambda runtime should be compatible with Python: ${PYTHON_VERSION}"
echo "-----------------------------------------------------------------------"