import logging
from pathlib import Path
from typing import Dict, List, Tuple
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.crs import CRS
from rasterio.transform import from_bounds
import numpy as np
from PIL import Image
from app.config import Config
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import shutil

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TileGenerator:
    def __init__(self):
        self.crs = CRS.from_string(Config.EPSG_ANTARCTIC)
        self.progress_lock = threading.Lock()
    
    def get_tile_bounds(self, z: int, x: int, y: int) -> Tuple[float, float, float, float]:
        """Get tile bounds in EPSG:3031"""
        minx = Config.ANTARCTIC_BOUNDS['minx']
        maxx = Config.ANTARCTIC_BOUNDS['maxx']
        miny = Config.ANTARCTIC_BOUNDS['miny']
        maxy = Config.ANTARCTIC_BOUNDS['maxy']
        
        total_width = maxx - minx
        total_height = maxy - miny
        
        tiles_per_side = 2 ** z
        tile_width = total_width / tiles_per_side
        tile_height = total_height / tiles_per_side
        
        tile_minx = minx + (x * tile_width)
        tile_maxx = tile_minx + tile_width
        tile_maxy = maxy - (y * tile_height)
        tile_miny = tile_maxy - tile_height
        
        return tile_minx, tile_miny, tile_maxx, tile_maxy
    
    def render_tile(self, src: rasterio.DatasetReader, minx: float, miny: float,
                   maxx: float, maxy: float, output_path: Path, tile_size: int = 256) -> bool:
        """Render single tile"""
        try:
            tile_transform = from_bounds(minx, miny, maxx, maxy, tile_size, tile_size)
            
            num_bands = min(src.count, 3)
            tile_array = np.zeros((num_bands, tile_size, tile_size), dtype=np.uint8)
            
            for band_idx in range(1, num_bands + 1):
                try:
                    reproject(
                        source=rasterio.band(src, band_idx),
                        destination=tile_array[band_idx - 1],
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=tile_transform,
                        dst_crs=self.crs,
                        resampling=Resampling.bilinear,
                        num_threads=2
                    )
                except Exception as e:
                    continue
            
            if src.count == 1:
                rgb_data = np.stack([tile_array[0]] * 3, axis=2)
            elif src.count >= 3:
                rgb_data = np.transpose(tile_array[:3], (1, 2, 0))
            else:
                rgb_data = np.zeros((tile_size, tile_size, 3), dtype=np.uint8)
            
            if np.mean(rgb_data) < 5:
                return False
            
            img = Image.fromarray(rgb_data, 'RGB')
            img.save(output_path, 'PNG', optimize=True)
            return True
            
        except Exception as e:
            return False
    
    def generate_tiles_for_map(self, source_path: Path, map_id: str, zoom_levels: List[int]) -> Dict:
        """Generate tiles for a specific map ID - stored in map-specific directory"""
        stats = {'zoom_levels': {}, 'total_tiles': 0, 'skipped_tiles': 0, 'map_id': map_id}
        
        # Create map-specific tile directory
        map_tiles_dir = Config.TILES_DIR / map_id
        map_tiles_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            with rasterio.open(source_path) as src:
                src_bounds = src.bounds
                logger.info(f"Source bounds: {src_bounds}")
                
                for z in zoom_levels:
                    tiles_per_side = 2 ** z
                    tiles_count = 0
                    skipped_count = 0
                    
                    logger.info(f"Generating zoom level {z} for map {map_id}")
                    start_time = time.time()
                    
                    tiles_to_generate = []
                    for x in range(tiles_per_side):
                        for y in range(tiles_per_side):
                            minx, miny, maxx, maxy = self.get_tile_bounds(z, x, y)
                            
                            if not (maxx < src_bounds.left or minx > src_bounds.right or
                                   maxy < src_bounds.bottom or miny > src_bounds.top):
                                tiles_to_generate.append((x, y, minx, miny, maxx, maxy))
                    
                    logger.info(f"Zoom {z}: {len(tiles_to_generate)} tiles to generate")
                    
                    for x, y, minx, miny, maxx, maxy in tiles_to_generate:
                        tile_dir = map_tiles_dir / str(z) / str(x)
                        tile_dir.mkdir(parents=True, exist_ok=True)
                        tile_path = tile_dir / f"{y}.png"
                        
                        if tile_path.exists() and tile_path.stat().st_size > 500:
                            tiles_count += 1
                            continue
                        
                        if self.render_tile(src, minx, miny, maxx, maxy, tile_path):
                            tiles_count += 1
                        else:
                            skipped_count += 1
                    
                    elapsed = time.time() - start_time
                    stats['zoom_levels'][z] = {
                        'tiles': tiles_count,
                        'skipped': skipped_count,
                        'time': f"{elapsed:.1f}s"
                    }
                    stats['total_tiles'] += tiles_count
                    stats['skipped_tiles'] += skipped_count
                    
                    logger.info(f"Zoom {z}: {tiles_count} tiles, {skipped_count} empty, time: {elapsed:.1f}s")
            
            return stats
            
        except Exception as e:
            logger.error(f"Tile generation failed: {e}")
            return stats
    
    def generate_tiles_from_vrt(self, vrt_path: Path, map_id: str = None) -> Dict:
        """Generate tiles from VRT for a specific map"""
        zoom_levels = list(range(Config.MIN_ZOOM, 7))  # Zooms 2-6
        if map_id:
            return self.generate_tiles_for_map(vrt_path, map_id, zoom_levels)
        else:
            # Fallback for backward compatibility
            return self.generate_tiles(vrt_path, zoom_levels)
    
    # Keep old method for compatibility
    def generate_tiles(self, source_path: Path, zoom_levels: List[int]) -> Dict:
        """Legacy method - generates tiles in root directory"""
        stats = {'zoom_levels': {}, 'total_tiles': 0, 'skipped_tiles': 0}
        
        try:
            with rasterio.open(source_path) as src:
                src_bounds = src.bounds
                
                for z in zoom_levels:
                    tiles_per_side = 2 ** z
                    tiles_count = 0
                    skipped_count = 0
                    
                    start_time = time.time()
                    
                    for x in range(tiles_per_side):
                        for y in range(tiles_per_side):
                            minx, miny, maxx, maxy = self.get_tile_bounds(z, x, y)
                            
                            if not (maxx < src_bounds.left or minx > src_bounds.right or
                                   maxy < src_bounds.bottom or miny > src_bounds.top):
                                tile_dir = Config.TILES_DIR / str(z) / str(x)
                                tile_dir.mkdir(parents=True, exist_ok=True)
                                tile_path = tile_dir / f"{y}.png"
                                
                                if not (tile_path.exists() and tile_path.stat().st_size > 500):
                                    if self.render_tile(src, minx, miny, maxx, maxy, tile_path):
                                        tiles_count += 1
                                    else:
                                        skipped_count += 1
                                else:
                                    tiles_count += 1
                    
                    elapsed = time.time() - start_time
                    stats['zoom_levels'][z] = {
                        'tiles': tiles_count,
                        'skipped': skipped_count,
                        'time': f"{elapsed:.1f}s"
                    }
                    stats['total_tiles'] += tiles_count
                    stats['skipped_tiles'] += skipped_count
            
            return stats
            
        except Exception as e:
            logger.error(f"Tile generation failed: {e}")
            return stats