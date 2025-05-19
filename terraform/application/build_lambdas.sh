#!/bin/bash

# This script creates ZIP files for Python Lambda functions
# It assumes it's being run from the ./terraform/application/ directory.
# Lambda source code is expected in directories like ../../final-summary/
# (i.e., sibling directories to the 'terraform' directory).

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# Path to the root directory containing individual Lambda function folders,
# relative to this script's location (terraform/application/)
LAMBDA_SOURCE_ROOT="../../" 

# Lambda function names (these should match the folder names under LAMBDA_SOURCE_ROOT)
LAMBDAS=(
  "start-summary-chain"
  "combine-text-segments"
  "final-summary"
  "revise-summary"
  "session-chat"
)

BUILD_DIR="build" # Temporary build directory within terraform/application/

# --- Script Start ---
echo "Starting Lambda packaging process..."
echo "Script location: $(pwd)"
echo "Lambda source root: $(cd "$LAMBDA_SOURCE_ROOT"; pwd)" # Show absolute path for clarity

# Clean up previous build directory if it exists
if [ -d "$BUILD_DIR" ]; then
  echo "Removing old build directory..."
  rm -rf "$BUILD_DIR"
fi
mkdir -p "$BUILD_DIR"
echo "Created build directory: $BUILD_DIR"

# Loop through each Lambda function
for lambda_name in "${LAMBDAS[@]}"; do
  echo "-----------------------------------------------------"
  echo "Processing Lambda: $lambda_name"
  echo "-----------------------------------------------------"

  LAMBDA_SRC_DIR_RELATIVE="${LAMBDA_SOURCE_ROOT}${lambda_name}" # Relative path for checks and cp
  LAMBDA_BUILD_TARGET_DIR="${BUILD_DIR}/${lambda_name}"
  # Output zip file will be in the current directory (terraform/application)
  # This matches how your Terraform lambda.tf file references them (e.g., "${path.module}/final-summary.zip")
  ZIP_FILE_NAME="${lambda_name}.zip" 

  # Check if source directory exists
  if [ ! -d "$LAMBDA_SRC_DIR_RELATIVE" ]; then
    echo "ERROR: Source directory ${LAMBDA_SRC_DIR_RELATIVE} (resolved to $(cd "$LAMBDA_SRC_DIR_RELATIVE" 2>/dev/null || echo "not found")) not found for Lambda ${lambda_name}. Skipping."
    continue
  fi
  
  # Check if app.py exists
  if [ ! -f "${LAMBDA_SRC_DIR_RELATIVE}/app.py" ]; then
    echo "ERROR: app.py not found in ${LAMBDA_SRC_DIR_RELATIVE} for Lambda ${lambda_name}. Skipping."
    continue
  fi

  echo "Creating build target directory: ${LAMBDA_BUILD_TARGET_DIR}"
  mkdir -p "$LAMBDA_BUILD_TARGET_DIR"

  echo "Copying source files from ${LAMBDA_SRC_DIR_RELATIVE} to ${LAMBDA_BUILD_TARGET_DIR}"
  cp "${LAMBDA_SRC_DIR_RELATIVE}/app.py" "${LAMBDA_BUILD_TARGET_DIR}/"
  # If you have other .py files or subdirectories in your Lambda source, copy them too:
  # Example: cp -r "${LAMBDA_SRC_DIR_RELATIVE}/my_utils" "${LAMBDA_BUILD_TARGET_DIR}/"

  # Change to the build target directory for this Lambda
  # All commands from here (pip install, zip) are relative to this LAMBDA_BUILD_TARGET_DIR
  pushd "$LAMBDA_BUILD_TARGET_DIR" > /dev/null # Use pushd/popd for safer directory changes
  echo "Changed directory to $(pwd)"

  # Install dependencies if any
  if [ "$lambda_name" == "final-summary" ]; then
    echo "Installing 'requests' library for ${lambda_name}..."
    # Ensure pip is available and python3 is appropriate.
    # For environments with multiple pythons, 'python3 -m pip' is safer.
    python3 -m pip install requests -t . --upgrade 
    echo "'requests' installed."
  fi
  
  # Add other specific dependencies for other lambdas here if needed
  # elif [ "$lambda_name" == "another-lambda-with-deps" ]; then
  #   echo "Installing dependencies for ${lambda_name}..."
  #   python3 -m pip install somepackage anotherpackage -t .
  #   echo "Dependencies installed for ${lambda_name}."
  # fi

  # Create the ZIP file in the terraform/application directory
  echo "Creating ZIP file: ../../${ZIP_FILE_NAME}"
  zip -r "../../${ZIP_FILE_NAME}" .
  
  popd > /dev/null # Go back to the original script directory (terraform/application)
  echo "Changed directory back to $(pwd)"
  echo "Successfully packaged ${lambda_name} into ${ZIP_FILE_NAME}"
done

echo "-----------------------------------------------------"
echo "Cleaning up build directory: $BUILD_DIR"
rm -rf "$BUILD_DIR"
echo "Build directory removed."
echo "-----------------------------------------------------"
echo "Lambda packaging process completed."
echo "ZIP files are located in: $(pwd)"
echo "-----------------------------------------------------"
