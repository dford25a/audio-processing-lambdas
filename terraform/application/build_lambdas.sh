#!/bin/bash

# This script creates ZIP files for Python Lambda functions

# Create directories for each Lambda
mkdir -p build/start-summary-chain
mkdir -p build/combine-text-segments
mkdir -p build/final-summary
mkdir -p build/revise-summary
mkdir -p build/session-chat

# Copy Python files to respective directories
cp ../start-summary-chain/app.py build/start-summary-chain/
cp ../combine-text-segments/app.py build/combine-text-segments/
cp ../final-summary/app.py build/final-summary/
cp ../revise-summary/app.py build/revise-summary/
cp ../session-chat/app.py build/session-chat/

# Create ZIP files
cd build/start-summary-chain && zip -r ../../start-summary-chain.zip . && cd ../..
cd build/combine-text-segments && zip -r ../../combine-text-segments.zip . && cd ../..
cd build/final-summary && zip -r ../../final-summary.zip . && cd ../..
cd build/revise-summary && zip -r ../../revise-summary.zip . && cd ../..
cd build/session-chat && zip -r ../../session-chat.zip . && cd ../..

# Clean up build directory
rm -rf build