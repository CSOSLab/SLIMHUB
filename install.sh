#!/bin/bash

# Get the absolute path of the current script
SCRIPT_PATH=$(realpath "$0")

# Construct the path to main.py and requirements.txt
BASE_DIR="$(dirname "$SCRIPT_PATH")"
MAIN_PY_PATH="$BASE_DIR/main.py"
REQ_FILE="$BASE_DIR/requirements.txt"

echo "🔹 Starting Slimhub installation..."

# Ensure python3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 is not installed. Please install Python3 first."
    exit 1
fi

# Ensure pip is installed
if ! python3 -m pip --version &> /dev/null; then
    echo "📦 pip for Python3 is not found. Installing python3-pip..."
    if command -v apt &> /dev/null; then
        sudo apt update && sudo apt install -y python3-pip
    else
        echo "❌ Package manager not detected. Please install pip manually."
        exit 1
    fi
else
    echo "✅ pip is already installed."
fi

# Install dependencies from requirements.txt if it exists
if [ -f "$REQ_FILE" ]; then
    echo "📥 Installing dependencies from requirements.txt..."
    
    # Use --break-system-packages only on Debian-based systems
    if command -v apt &> /dev/null; then
        python3 -m pip install -r "$REQ_FILE" --break-system-packages
    else
        python3 -m pip install -r "$REQ_FILE"
    fi
else
    echo "⚠️ Warning: requirements.txt not found in $BASE_DIR. Skipping dependency installation."
fi

# Add aliases to ~/.bashrc only if they don’t already exist
if ! grep -q 'alias slimhub=' ~/.bashrc; then
    echo "alias slimhub=\"python3 $MAIN_PY_PATH\"" >> ~/.bashrc
    echo "✅ Alias 'slimhub' added!"
else
    echo "🔹 Alias 'slimhub' already exists, skipping..."
fi

if ! grep -q 'alias slimhub-background=' ~/.bashrc; then
    echo "alias slimhub-background=\"nohup python3 $MAIN_PY_PATH -r > /dev/null 2>&1 &\"" >> ~/.bashrc
    echo "✅ Alias 'slimhub-background' added!"
else
    echo "🔹 Alias 'slimhub-background' already exists, skipping..."
fi

# Inform the user to apply the alias manually
echo -e "\n🎉 Slimhub installed successfully! 🚀"
echo "🔹 Please run: source ~/.bashrc or restart your terminal to apply changes."
