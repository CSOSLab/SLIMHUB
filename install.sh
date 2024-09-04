#!/bin/sh

# Get the absolute path of the current script
SCRIPT_PATH=$(realpath "$0")

# Construct the path to main.py
MAIN_PY_PATH="$(dirname "$SCRIPT_PATH")/main.py"

# Add the alias to .bashrc
echo "alias slimhub=\"python3 $MAIN_PY_PATH\"" >> ~/.bashrc

# Add the alias for slimhub_background
echo "alias slimhub-background=\"nohup python3 $MAIN_PY_PATH -r &\"" >> ~/.bashrc

# Apply the changes
. ~/.bashrc

echo "Alias 'slimhub' has been successfully added."
