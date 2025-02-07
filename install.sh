#!/bin/sh

# Get the absolute path of the current script
SCRIPT_PATH=$(realpath "$0")

# Construct the path to main.py
MAIN_PY_PATH="$(dirname "$SCRIPT_PATH")/main.py"

# Get the absolute path of the Python interpreter insde the venv
VENV_PYTHON="/home/hmkang/SLIMHUB/slimhub-env/bin/python"

# Add the alias to .bashrc
echo "alias slimhub=\"$VENV_PYTHON  $MAIN_PY_PATH\"" >> ~/.bashrc

# Add the alias for slimhub_background
echo "alias slimhub-background=\"nohup $VENV_PYTHON $MAIN_PY_PATH -r &\"" >> ~/.bashrc

# Apply the changes
. ~/.bashrc

echo "Alias 'slimhub' has been successfully added."
