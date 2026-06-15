#!/usr/bin/env python3
from app import create_app
import logging
import sys
import os

# Disable GDAL warnings
os.environ['GDAL_DISABLE_READDIR_ON_OPEN'] = 'EMPTY_DIR'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Create the app
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = os.environ.get('HOST', '0.0.0.0')
    
    logger.info("=" * 70)
    logger.info("🌍 Antarctic Mapper Server Started!")
    logger.info("=" * 70)
    logger.info(f"📍 Running on: http://{host}:{port}")
    logger.info("=" * 70)
    
    # For local development
    if os.environ.get('ENV') != 'production':
        app.run(host=host, port=port, debug=True)
    else:
        # For production (gunicorn will be used)
        pass