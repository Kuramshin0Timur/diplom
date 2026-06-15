#!/bin/bash

echo "Setting up Antarctic Mapper System..."

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev gdal-bin libgdal-dev

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install numpy first
pip install numpy==1.24.3

# Install rasterio with specific version
pip install rasterio==1.3.8 --no-binary rasterio

# Install other dependencies
pip install -r requirements.txt

# Create directory structure
echo "Creating directory structure..."
mkdir -p data/{input,temp,output,tiles}
mkdir -p logs

# Set permissions
chmod -R 755 data
chmod -R 755 logs

echo "Setup complete!"
echo ""
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  python run.py"