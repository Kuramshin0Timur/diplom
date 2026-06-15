import os
import json
from pathlib import Path

class Config:
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / 'data'
    LIBRARY_DIR = DATA_DIR / 'library'
    INPUT_DIR = DATA_DIR / 'input'
    TEMP_DIR = DATA_DIR / 'temp'
    OUTPUT_DIR = DATA_DIR / 'output'
    TILES_DIR = DATA_DIR / 'tiles'
    LOGS_DIR = BASE_DIR / 'logs'
    
    EPSG_WGS84 = 'EPSG:4326'
    EPSG_ANTARCTIC = 'EPSG:3031'
    
    PROJ_ANTARCTIC = '+proj=stere +lat_0=-90 +lat_ts=-71 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs'
    
    MIN_ZOOM = 2
    MAX_ZOOM = 8
    
    # Antarctic bounds in meters - полный охват Антарктиды (согласовано с map.js)
    ANTARCTIC_BOUNDS = {
        'minx': -4500000,
        'miny': -4500000,
        'maxx': 4500000,
        'maxy': 4500000
    }
    
    MAX_IMAGE_SIZE = 4000
    TILE_SIZE = 256
    
    SUPPORTED_FORMATS = {'.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf', '.SRF'}
    
    @classmethod
    def init_dirs(cls):
        for dir_path in [cls.INPUT_DIR, cls.TEMP_DIR, cls.OUTPUT_DIR, cls.TILES_DIR, cls.LOGS_DIR, cls.LIBRARY_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        (cls.LIBRARY_DIR / 'antarctic').mkdir(exist_ok=True)
        (cls.LIBRARY_DIR / 'srf').mkdir(exist_ok=True)
        
        cls.init_metadata()
    
    @classmethod
    def init_metadata(cls):
        metadata_file = cls.LIBRARY_DIR / 'metadata.json'
        default_metadata = {"version": "1.0", "created": "2024-01-01T00:00:00", "maps": []}
        
        if not metadata_file.exists():
            with open(metadata_file, 'w') as f:
                json.dump(default_metadata, f, indent=2)