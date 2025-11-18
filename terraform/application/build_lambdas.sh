#!/bin/bash

# This script creates ZIP files for Python Lambda functions.
# It *originally* assumed it's being run from the ./terraform/application/ directory,
# but it now auto-cds to its own directory so you can invoke it from anywhere.
# Lambda source code is expected in directories like ../../final-summary/
# (i.e., sibling directories to the 'terraform' directory).

# Always run from the directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# Path to the root directory containing individual Lambda function folders,
# relative to this script's location (terraform/application/)
LAMBDA_SOURCE_ROOT="../../" 

# Default Lambda function names (these should match the folder names under LAMBDA_SOURCE_ROOT)
DEFAULT_LAMBDAS=(
  "start-summary-chain"
  "combine-text-segments"
  "final-summary"
  "revise-summary"
  "session-chat"
  "campaign-chat"
  "create-campaign-index"
  "stripeWebhook"
  "spend-credits"
  "refund-credits"
  "html-to-url"
  "post-cognito-confirmation"
  "error-notifier"
)

BUILD_DIR="build" # Temporary build directory within terraform/application/

# Lambdas that rely entirely on shared layers for dependencies.
# For these, we DO NOT vendor requirements into the function zip to avoid
# overshadowing layer packages (which caused the pydantic_core error).
USE_LAYER_LAMBDAS=(
  "start-summary-chain"
  "init-credits"
  "refund-credits"
  "final-summary"
  "revise-summary"
  "session-chat"
  "campaign-chat"
  "create-campaign-index"
  "spend-credits"
)

is_in_use_layer_list() {
  local name="$1"
  for item in "${USE_LAYER_LAMBDAS[@]}"; do
    if [[ "$item" == "$name" ]]; then
      return 0
    fi
  done
  return 1
}

# --- Script Start ---
echo "Starting Lambda packaging process..."
echo "Script location: $(pwd)"
echo "Lambda source root: $(cd "$LAMBDA_SOURCE_ROOT"; pwd)" # Show absolute path for clarity

# Determine which lambdas to build
if [ -n "$1" ]; then
  # If a parameter is provided, build only that specific lambda
  LAMBDAS=("$1")
  echo "Building only specified Lambda: $1"
else
  # Otherwise, build all default lambdas
  LAMBDAS=("${DEFAULT_LAMBDAS[@]}")
  echo "Building all default Lambdas."
fi

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
  # Resolve absolute path for use after pushd
  if [ -d "$LAMBDA_SRC_DIR_RELATIVE" ]; then
    LAMBDA_SRC_DIR_ABS="$(cd "$LAMBDA_SRC_DIR_RELATIVE" && pwd)"
  else
    LAMBDA_SRC_DIR_ABS=""
  fi
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
  # If this lambda relies on shared layers, skip vendoring dependencies to avoid overshadowing the layer
  if is_in_use_layer_list "$lambda_name"; then
    echo "Skipping dependency install for ${lambda_name} (uses shared layers)."
  else
    # Prefer per-lambda requirements.txt next to app.py
    if [ -n "${LAMBDA_SRC_DIR_ABS}" ] && [ -f "${LAMBDA_SRC_DIR_ABS}/requirements.txt" ]; then
      echo "Installing dependencies from requirements.txt for ${lambda_name}..."
      cp "${LAMBDA_SRC_DIR_ABS}/requirements.txt" .
      # Use python3 -m pip to avoid PATH issues
      python3 -m pip install -r requirements.txt -t . --upgrade
      rm -f requirements.txt
      echo "Dependencies installed for ${lambda_name}."
    elif [ "$lambda_name" == "final-summary" ]; then
      echo "No vendored deps needed for ${lambda_name}; relying on layer."
    fi
  fi

  # Create the ZIP file in the terraform/application directory
  # IMPORTANT: remove any existing zip first, otherwise `zip` will update/append
  # and stale dependencies from previous builds (e.g., faiss/numpy) will remain.
  echo "Creating ZIP file: ../../${ZIP_FILE_NAME}"
  rm -f "../../${ZIP_FILE_NAME}"
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
