#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
PYTHON_VERSION="3.11" # Match this to your Lambda runtime
PLATFORM="manylinux2014_x86_64" # For x86_64 Lambda architecture.
LAYER_NAME="html_dependencies"
SITE_PACKAGES_SUBDIR="lib/python${PYTHON_VERSION}/site-packages"
PACKAGE_INSTALL_DIR="python/${SITE_PACKAGES_SUBDIR}"
BUILD_DIR="./${LAYER_NAME}_layer_build"
OUTPUT_ZIP_FILE="${LAYER_NAME}_layer.zip"

# --- Script Start ---
echo "Starting HTML dependencies Lambda layer creation..."

# 1. Clean up previous build artifacts
echo "Cleaning up previous build artifacts..."
rm -rf "${BUILD_DIR}"
rm -f "${OUTPUT_ZIP_FILE}"

# 2. Create build directory
echo "Creating build directory: ${BUILD_DIR}/${PACKAGE_INSTALL_DIR}"
mkdir -p "${BUILD_DIR}/${PACKAGE_INSTALL_DIR}"

# 3. Install beautifulsoup4
echo "Installing beautifulsoup4 for Python ${PYTHON_VERSION} on ${PLATFORM}..."
pip install \
    --platform "${PLATFORM}" \
    --target "${BUILD_DIR}/${PACKAGE_INSTALL_DIR}" \
    --implementation cp \
    --python-version "${PYTHON_VERSION}" \
    --only-binary=:all: \
    --upgrade \
    beautifulsoup4

# 4. Create the zip file
echo "Creating Lambda layer zip file: ${OUTPUT_ZIP_FILE}..."
(
  cd "${BUILD_DIR}" && \
  zip -r "../${OUTPUT_ZIP_FILE}" python
)

# 5. Clean up the build directory
echo "Cleaning up build directory: ${BUILD_DIR}..."
rm -rf "${BUILD_DIR}"

echo "-----------------------------------------------------------------------"
echo "HTML dependencies Lambda layer created successfully: ${OUTPUT_ZIP_FILE}"
echo "-----------------------------------------------------------------------"
