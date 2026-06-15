import json
import numpy as np
import rasterio
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps, from_origin
from rasterio.crs import CRS
from PIL import Image
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from app.config import Config
import re
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Georeferencer:
    def __init__(self):
        pass
    
    def load_srf_file(self, image_path: Path) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Load SRF file (specialized format with embedded PNG)"""
        try:
            # First try to open as regular image
            with Image.open(image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                width, height = img.size
                logger.info(f"Successfully loaded SRF as regular image: {width}x{height}")
                return np.array(img), (width, height)
        except Exception as e:
            logger.debug(f"Could not open as regular image: {e}")
        
        # Try to extract PNG data from SRF file
        try:
            with open(image_path, 'rb') as f:
                data = f.read()
            
            # Look for PNG signature
            png_sig = b'\x89PNG\r\n\x1a\n'
            png_pos = data.find(png_sig)
            
            if png_pos == -1:
                raise ValueError(f"No PNG data found in SRF file: {image_path}")
            
            # Extract PNG data from position to end
            png_data = data[png_pos:]
            
            # Find end of PNG (IEND chunk)
            iend_marker = b'IEND'
            iend_pos = png_data.find(iend_marker)
            if iend_pos != -1:
                # Include IEND chunk (8 bytes)
                png_data = png_data[:iend_pos + 8]
            
            # Load the PNG data
            img = Image.open(io.BytesIO(png_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            width, height = img.size
            logger.info(f"Successfully extracted PNG from SRF: {width}x{height}")
            return np.array(img), (width, height)
            
        except Exception as e:
            logger.error(f"Failed to load SRF file {image_path}: {e}")
            raise ValueError(f"Cannot load SRF: {image_path}")
    
    def load_image(self, image_path: Path) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Load image from any format"""
        ext = image_path.suffix.lower()
        
        if ext in {'.srf', '.SRF'}:
            return self.load_srf_file(image_path)
        
        with Image.open(image_path) as img:
            if img.mode == 'RGBA':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1])
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            width, height = img.size
            
            max_dim = Config.MAX_IMAGE_SIZE
            if max(width, height) > max_dim:
                scale = max_dim / max(width, height)
                new_size = (int(width * scale), int(height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                width, height = new_size
            
            return np.array(img), (width, height)
    
    def validate_and_clamp_latitude(self, lat: float) -> float:
        """Clamp latitude to valid Antarctic range [-90, -60]"""
        if lat < -90:
            logger.warning(f"Latitude {lat} < -90, clamping to -90")
            return -90
        if lat > -60:
            logger.warning(f"Latitude {lat} > -60, clamping to -60")
            return -60
        return lat
    
    def add_edge_gcps(self, gcps: List[Dict], width: int, height: int) -> List[Dict]:
        """Add GCPs at image edges to prevent extrapolation"""
        existing_gcps = {(gcp['pixel_x'], gcp['pixel_y']): gcp for gcp in gcps}
        
        # Get min/max coordinates from existing GCPs
        lons = [gcp['longitude'] for gcp in gcps]
        lats = [gcp['latitude'] for gcp in gcps]
        min_lon = min(lons)
        max_lon = max(lons)
        min_lat = min(lats)
        max_lat = max(lats)
        
        new_gcps = list(gcps)
        
        # Add corner GCPs if missing
        corners = [
            (0, 0, min_lon, max_lat),
            (width, 0, max_lon, max_lat),
            (0, height, min_lon, min_lat),
            (width, height, max_lon, min_lat)
        ]
        
        for px, py, lon, lat in corners:
            if (px, py) not in existing_gcps:
                new_gcps.append({
                    'pixel_x': px,
                    'pixel_y': py,
                    'longitude': lon,
                    'latitude': lat
                })
                logger.info(f"Added edge GCP: ({px},{py}) -> ({lon},{lat})")
        
        return new_gcps
    
    def calculate_safe_transform(self, gcps: List[GroundControlPoint], width: int, height: int) -> Optional[rasterio.transform.Affine]:
        """Calculate transform with fallback to simpler method if extrapolation occurs"""
        try:
            # Try polynomial transform first
            transform = from_gcps(gcps)
            
            # Check all corners
            corners = [(0, 0), (0, height), (width, 0), (width, height)]
            valid = True
            
            for x, y in corners:
                lon, lat = transform * (x, y)
                if lat < -90 or lat > -60:
                    logger.warning(f"Transform at ({x},{y}) gives invalid lat {lat}")
                    valid = False
                    break
            
            if valid:
                return transform
            
            # Fallback: use affine from first 3 GCPs only (no extrapolation)
            logger.info("Falling back to affine transform from first 3 GCPs")
            from rasterio.transform import Affine
            
            p1, p2, p3 = gcps[:3]
            
            # Solve for affine coefficients
            A = np.array([
                [p1.col, p1.row, 1, 0, 0, 0],
                [0, 0, 0, p1.col, p1.row, 1],
                [p2.col, p2.row, 1, 0, 0, 0],
                [0, 0, 0, p2.col, p2.row, 1],
                [p3.col, p3.row, 1, 0, 0, 0],
                [0, 0, 0, p3.col, p3.row, 1]
            ])
            
            B = np.array([p1.x, p1.y, p2.x, p2.y, p3.x, p3.y])
            coeffs = np.linalg.lstsq(A, B, rcond=None)[0]
            
            transform = Affine(coeffs[0], coeffs[1], coeffs[2],
                              coeffs[3], coeffs[4], coeffs[5])
            
            # Validate fallback transform
            for x, y in corners:
                lon, lat = transform * (x, y)
                if lat < -90 or lat > -60:
                    logger.error(f"Fallback transform also invalid at ({x},{y}): lat={lat}")
                    return None
            
            return transform
            
        except Exception as e:
            logger.error(f"Transform calculation failed: {e}")
            return None
    
    def georeference_image(self, image_path: Path, gcps: List[Dict], output_path: Path) -> Optional[Path]:
        """Georeference image with full-edge GCPs"""
        try:
            # Load image
            img_array, (width, height) = self.load_image(image_path)
            logger.info(f"Image: {width}x{height}")
            
            if len(gcps) < 3:
                raise ValueError(f"Need at least 3 GCPs, got {len(gcps)}")
            
            # Clamp latitudes in GCPs
            clamped_gcps = []
            for gcp in gcps:
                clamped_gcp = gcp.copy()
                clamped_gcp['latitude'] = self.validate_and_clamp_latitude(gcp['latitude'])
                clamped_gcps.append(clamped_gcp)
            
            # Add edge GCPs to prevent extrapolation
            full_gcps = self.add_edge_gcps(clamped_gcps, width, height)
            logger.info(f"Added edge GCPs, total: {len(full_gcps)}")
            
            # Create rasterio GCPs
            rasterio_gcps = []
            for i, gcp in enumerate(full_gcps):
                pixel_x = float(gcp.get('pixel_x', gcp.get('col', 0)))
                pixel_y = float(gcp.get('pixel_y', gcp.get('row', 0)))
                lon = float(gcp.get('longitude', gcp.get('lon', 0)))
                lat = float(gcp.get('latitude', gcp.get('lat', 0)))
                
                # Ensure within bounds
                pixel_x = max(0, min(pixel_x, width))
                pixel_y = max(0, min(pixel_y, height))
                
                rasterio_gcps.append(
                    GroundControlPoint(
                        row=pixel_y,
                        col=pixel_x,
                        x=lon,
                        y=lat,
                        z=0,
                        id=f"gcp_{i}"
                    )
                )
                logger.info(f"GCP {i}: ({pixel_x},{pixel_y}) -> ({lon},{lat})")
            
            # Calculate safe transform
            transform = self.calculate_safe_transform(rasterio_gcps, width, height)
            
            if transform is None:
                raise ValueError("Cannot compute valid transform")
            
            # Calculate RMSE
            residuals = []
            for gcp in rasterio_gcps:
                try:
                    col, row = ~transform * (gcp.x, gcp.y)
                    error = np.sqrt((col - gcp.col)**2 + (row - gcp.row)**2)
                    residuals.append(error)
                except:
                    pass
            
            if residuals:
                rmse = np.mean(residuals)
                max_err = max(residuals)
                logger.info(f"RMSE: {rmse:.2f} px, Max: {max_err:.2f} px")
            
            # Create GeoTIFF
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=3,
                dtype=img_array.dtype,
                crs=CRS.from_epsg(4326),
                transform=transform,
                compress='lzw',
                tiled=True
            ) as dst:
                for band in range(3):
                    dst.write(img_array[:, :, band], band + 1)
            
            logger.info(f"Georeferenced: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Georeferencing failed: {e}")
            return None
    
    def auto_detect_gcps_from_lonlat(self, image_path: Path, reference_bounds: Dict) -> List[Dict]:
        """Auto-detect GCPs from filename"""
        gcps = []
        filename = image_path.stem
        
        # Pattern for coordinates in filename: lon1_lat1_lon2_lat2
        pattern = r'([+-]?\d+\.?\d*)[_-]([+-]?\d+\.?\d*)[_-]([+-]?\d+\.?\d*)[_-]([+-]?\d+\.?\d*)'
        match = re.search(pattern, filename)
        
        if match:
            try:
                lon1, lat1, lon2, lat2 = map(float, match.groups())
                
                with Image.open(image_path) as img:
                    width, height = img.size
                
                # Clamp latitudes
                lat1 = self.validate_and_clamp_latitude(lat1)
                lat2 = self.validate_and_clamp_latitude(lat2)
                
                # Add edge GCPs
                gcps = [
                    {'pixel_x': 0, 'pixel_y': 0, 'longitude': lon1, 'latitude': lat1},
                    {'pixel_x': width, 'pixel_y': 0, 'longitude': lon2, 'latitude': lat1},
                    {'pixel_x': width, 'pixel_y': height, 'longitude': lon2, 'latitude': lat2},
                    {'pixel_x': 0, 'pixel_y': height, 'longitude': lon1, 'latitude': lat2},
                ]
                logger.info(f"Auto-detected GCPs: {gcps}")
            except Exception as e:
                logger.warning(f"Failed to parse GCPs: {e}")
        
        return gcps