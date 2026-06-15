#!/usr/bin/env python3
from app import create_app
from waitress import serve
import logging
import sys
import os
import socket
import subprocess

# Disable GDAL warnings
os.environ['GDAL_DISABLE_READDIR_ON_OPEN'] = 'EMPTY_DIR'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/antarctic_mapper.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def get_wsl_ip():
    """Get WSL IP address for network access"""
    try:
        # Get Windows host IP from WSL
        result = subprocess.run(['cat', '/etc/resolv.conf'], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'nameserver' in line:
                return line.split()[1]
    except:
        pass
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_wsl_local_ip():
    """Get WSL local IP"""
    try:
        result = subprocess.run(['hostname', '-I'], capture_output=True, text=True)
        return result.stdout.strip().split()[0]
    except:
        return "127.0.0.1"

if __name__ == '__main__':
    app = create_app()
    wsl_ip = get_wsl_ip()
    wsl_local = get_wsl_local_ip()
    
    logger.info("=" * 70)
    logger.info("🌍 Antarctic Mapper Server Started on WSL!")
    logger.info("=" * 70)
    logger.info(f"📍 Local access (WSL):    http://{wsl_local}:5000")
    logger.info(f"📡 From Windows browser:  http://{wsl_ip}:5000")
    logger.info("")
    logger.info("💡 IMPORTANT for WSL1:")
    logger.info("   - WSL1 uses Windows network stack")
    logger.info("   - Access via Windows IP address (usually 172.x.x.x or 192.168.x.x)")
    logger.info("   - Or use localhost if browser is in WSL")
    logger.info("")
    logger.info("💡 To share with others on the same network:")
    logger.info(f"   Send them: http://{wsl_ip}:5000")
    logger.info("")
    logger.info("💡 To share over the internet, use ngrok:")
    logger.info("   Download: https://ngrok.com/download")
    logger.info("   Then run: ngrok http 5000")
    logger.info("=" * 70)
    logger.info("Supported formats: TIFF, GeoTIFF, JPG, PNG, SRF")
    logger.info("Projection: Antarctic Polar Stereographic (EPSG:3031)")
    logger.info("=" * 70)
    
    # Start server (bind to all interfaces for WSL)
    serve(app, host='0.0.0.0', port=5000, threads=4)