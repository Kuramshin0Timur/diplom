from flask import Flask, send_file, abort
from flask_cors import CORS
from app.config import Config
from pathlib import Path
import logging
import re
from PIL import Image
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__, static_folder='static', static_url_path='')
    app.config.from_object(Config)
    
    # Enable CORS for all routes
    CORS(app, resources={
        r"/*": {
            "origins": "*",
            "methods": ["GET", "POST", "DELETE", "OPTIONS", "PUT"],
            "allow_headers": ["Content-Type", "Authorization"]
        }
    })
    
    Config.init_dirs()
    
    from app.api import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    
    @app.route('/')
    def index():
        return app.send_static_file('index.html')
    
    @app.route('/tiles/<map_id>/<int:z>/<int:x>/<int:y>.png')
    def serve_map_tile(map_id, z, x, y):
        """
        Serve tiles for specific map ID
        Each map has its own tile directory
        """
        # Sanitize map_id to prevent path traversal
        # Allow letters, numbers, underscores, hyphens, and Cyrillic
        if not re.match(r'^[a-zA-Z0-9_\-]+$', map_id):
            # Also allow Cyrillic (processed map names)
            if not re.match(r'^[\w\u0400-\u04FF\-]+$', map_id):
                logger.warning(f"Invalid map_id format: {map_id}")
                abort(404)
        
        # Build path to tile
        tile_path = Config.TILES_DIR / map_id / str(z) / str(x) / f"{y}.png"
        
        if tile_path.exists() and tile_path.stat().st_size > 100:
            response = send_file(
                tile_path, 
                mimetype='image/png',
                max_age=3600  # Cache for 1 hour
            )
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Cache-Control'] = 'public, max-age=3600'
            return response
        
        # Return empty transparent 1x1 PNG for missing tiles
        # This prevents browser errors and allows smooth panning
        empty_tile = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        img_io = io.BytesIO()
        empty_tile.save(img_io, 'PNG')
        img_io.seek(0)
        
        response = send_file(img_io, mimetype='image/png')
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    
    @app.route('/tiles/<map_id>/<int:z>/<int:x>/<int:y>')
    def serve_map_tile_no_ext(map_id, z, x, y):
        """Serve tiles without extension (for compatibility)"""
        return serve_map_tile(map_id, z, x, y)
    
    # Legacy route for backward compatibility - returns empty tiles
    @app.route('/tiles/<int:z>/<int:x>/<int:y>.png')
    def serve_legacy_tile(z, x, y):
        """Legacy tile route - returns empty tiles to avoid 404 errors"""
        empty_tile = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        img_io = io.BytesIO()
        empty_tile.save(img_io, 'PNG')
        img_io.seek(0)
        
        response = send_file(img_io, mimetype='image/png')
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response
    
    @app.route('/tiles/<int:z>/<int:x>/<int:y>')
    def serve_legacy_tile_no_ext(z, x, y):
        """Legacy tile route without extension"""
        return serve_legacy_tile(z, x, y)
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {'error': 'Not found'}, 404
    
    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        return {'error': 'Internal server error'}, 500
    
    return app