#!/bin/bash

# Enable strict mode
set -euo pipefail

# Define the path to the Python script
SCRIPT_PATH="./bioGen/ulits/api_set_sandbox.py"

# Check if the Python script exists
if [ ! -f "$SCRIPT_PATH" ]; then
    echo "Error: Script $SCRIPT_PATH not found."
    exit 1
fi

# Check if Python3 is available
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: Python3 interpreter not found. Please install Python3."
    exit 1
fi

# Execute the Python script with all arguments passed to the shell script
python3 "$SCRIPT_PATH" "$@"

# Display a completion message
echo "Script execution finished."
