import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import rasterio
from rasterio.crs import CRS
import numpy as np
from app.config import Config
from app.georeferencer import Georeferencer
from app.srf_processor import SRFProcessor
from PIL import Image as PilImage
import time
import shutil
import subprocess
import json
import cv2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self):
        self.georeferencer = Georeferencer()
    
    def detect_and_correct_antarctic(self, image_path: Path) -> Tuple[Optional[Path], Dict]:
        """
        Detects Antarctic continent contour, rotates and crops image.
        Returns (path to processed image, transformation metadata)
        """
        transform_data = {
            'rotated': False,
            'angle': 0,
            'crop_x': 0,
            'crop_y': 0,
            'crop_w': 0,
            'crop_h': 0,
            'original_width': 0,
            'original_height': 0,
            'new_width': 0,
            'new_height': 0
        }
        
        try:
            logger.info("Detecting Antarctic contour and correcting rotation...")
            
            # Load image
            img = cv2.imread(str(image_path))
            if img is None:
                logger.error(f"Failed to load image with OpenCV: {image_path}")
                return image_path, transform_data
            
            height, width = img.shape[:2]
            transform_data['original_width'] = width
            transform_data['original_height'] = height
            logger.info(f"Original image size: {width}x{height}")
            
            # Convert to HSV for better continent detection
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            
            # Mask for Antarctic land (ice is white/blue, ocean is dark)
            lower_ice = np.array([0, 0, 180])
            upper_ice = np.array([180, 80, 255])
            mask_ice = cv2.inRange(hsv, lower_ice, upper_ice)
            
            # Alternative mask for gray/white areas
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, mask_gray = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
            
            # Combine masks
            mask = cv2.bitwise_or(mask_ice, mask_gray)
            
            # Morphological closing to fill holes
            kernel = np.ones((5, 5), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            # Find contours
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                logger.warning("No contours found, using original image")
                return image_path, transform_data
            
            # Find largest contour
            largest_contour = max(contours, key=cv2.contourArea)
            contour_area = cv2.contourArea(largest_contour)
            total_area = width * height
            area_ratio = contour_area / total_area
            
            logger.info(f"Largest contour area: {contour_area} ({area_ratio:.1%} of image)")
            
            if area_ratio < 0.1:
                logger.warning("Contour too small, maybe detection failed")
                return image_path, transform_data
            
            # Find minimal bounding rectangle for angle detection
            rect = cv2.minAreaRect(largest_contour)
            (center_x, center_y), (rect_w, rect_h), angle = rect
            
            logger.info(f"MinAreaRect: center=({center_x:.1f}, {center_y:.1f}), "
                       f"size=({rect_w:.1f}, {rect_h:.1f}), angle={angle:.1f}°")
            
            # Normalize rotation angle
            if rect_w < rect_h:
                angle = angle + 90
            
            rotation_angle = angle
            logger.info(f"Rotation angle to correct: {rotation_angle:.1f}°")
            
            # Rotate if angle is significant
            processed_img = img
            if abs(rotation_angle) > 2 and abs(rotation_angle) < 88:
                logger.info(f"Rotating image by {-rotation_angle:.1f} degrees")
                transform_data['rotated'] = True
                transform_data['angle'] = rotation_angle
                
                rotation_matrix = cv2.getRotationMatrix2D((center_x, center_y), -rotation_angle, 1.0)
                processed_img = cv2.warpAffine(
                    img, rotation_matrix, (width, height),
                    flags=cv2.INTER_LANCZOS4,
                    borderMode=cv2.BORDER_CONSTANT,
                    borderValue=(0, 0, 0)
                )
                
                # Recalculate mask on rotated image
                hsv_rot = cv2.cvtColor(processed_img, cv2.COLOR_BGR2HSV)
                mask_rot = cv2.inRange(hsv_rot, lower_ice, upper_ice)
                gray_rot = cv2.cvtColor(processed_img, cv2.COLOR_BGR2GRAY)
                _, mask_gray_rot = cv2.threshold(gray_rot, 200, 255, cv2.THRESH_BINARY)
                mask_rot = cv2.bitwise_or(mask_rot, mask_gray_rot)
                mask_rot = cv2.morphologyEx(mask_rot, cv2.MORPH_CLOSE, kernel)
                
                contours_rot, _ = cv2.findContours(mask_rot, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours_rot:
                    largest_contour = max(contours_rot, key=cv2.contourArea)
            else:
                logger.info("No significant rotation needed")
            
            # Crop to bounding box
            x, y, w, h = cv2.boundingRect(largest_contour)
            padding = int(min(w, h) * 0.02)
            crop_x = max(0, x - padding)
            crop_y = max(0, y - padding)
            crop_w = min(width - crop_x, w + 2 * padding)
            crop_h = min(height - crop_y, h + 2 * padding)
            
            transform_data['crop_x'] = crop_x
            transform_data['crop_y'] = crop_y
            transform_data['crop_w'] = crop_w
            transform_data['crop_h'] = crop_h
            
            logger.info(f"Cropping to: x={crop_x}, y={crop_y}, w={crop_w}, h={crop_h}")
            
            cropped = processed_img[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]
            new_height, new_width = cropped.shape[:2]
            transform_data['new_width'] = new_width
            transform_data['new_height'] = new_height
            
            logger.info(f"New dimensions after crop: {new_width}x{new_height}")
            
            # Save processed image
            processed_path = Config.TEMP_DIR / f"processed_{image_path.stem}.png"
            cv2.imwrite(str(processed_path), cropped)
            logger.info(f"Saved processed image: {processed_path}")
            
            return processed_path, transform_data
            
        except Exception as e:
            logger.error(f"Failed to detect and correct Antarctic: {e}", exc_info=True)
            return image_path, transform_data
    
    def georeference_polar_image(self, image_path: Path, output_path: Path) -> Optional[Path]:
        """
        Georeferences polar Antarctic maps using full extent.
        Assigns EPSG:3031 with complete continent coverage.
        """
        try:
            start_time = time.time()
            logger.info("Georeferencing polar Antarctic image")
            
            # Get dimensions of processed image
            try:
                with PilImage.open(image_path) as pil_img:
                    width, height = pil_img.size
                logger.info(f"Image dimensions: {width}x{height}")
            except Exception as e:
                logger.error(f"Failed to open image with PIL: {e}")
                return None
            
            # Full Antarctic extent in EPSG:3031
            left = Config.ANTARCTIC_BOUNDS['minx']
            top = Config.ANTARCTIC_BOUNDS['maxy']
            right = Config.ANTARCTIC_BOUNDS['maxx']
            bottom = Config.ANTARCTIC_BOUNDS['miny']
            
            logger.info(f"Assigning EPSG:3031 bounds:")
            logger.info(f"  Left: {left} m, Top: {top} m")
            logger.info(f"  Right: {right} m, Bottom: {bottom} m")
            
            # Use gdal_translate for georeferencing with NO compression to avoid LZW errors
            cmd = [
                'gdal_translate',
                '-of', 'GTiff',
                '-a_srs', Config.EPSG_ANTARCTIC,
                '-a_ullr',
                str(left), str(top), str(right), str(bottom),
                '-co', 'COMPRESS=NONE',
                '-co', 'TILED=NO',
                str(image_path),
                str(output_path)
            ]
            
            logger.info("Running gdal_translate...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"gdal_translate failed: {result.stderr}")
                return None
            
            if not output_path.exists():
                logger.error("Output file not created")
                return None
            
            # Verify the output
            try:
                with rasterio.open(output_path) as src:
                    logger.info(f"Output CRS: {src.crs}")
                    logger.info(f"Output bounds: {src.bounds}")
            except Exception as e:
                logger.warning(f"Could not verify output: {e}")
            
            size_mb = output_path.stat().st_size / (1024 * 1024)
            elapsed = time.time() - start_time
            logger.info(f"Successfully georeferenced in {elapsed:.1f}s, size: {size_mb:.1f} MB")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Georeferencing failed: {e}", exc_info=True)
            return None
    
    def process_single_image(self, img_path: Path, output_path: Path, gcps: List = None) -> Optional[Path]:
        """
        Process a single image with optional GCPs
        """
        try:
            # Step 1: Preprocessing (detect, rotate, crop)
            processed_path, transform_data = self.detect_and_correct_antarctic(img_path)
            
            if processed_path is None or not processed_path.exists():
                logger.error("Preprocessing failed, using original image")
                processed_path = img_path
            
            # Step 2: Georeferencing
            result_path = self.georeference_polar_image(processed_path, output_path)
            
            # Cleanup temp file
            if processed_path != img_path and processed_path.exists():
                processed_path.unlink()
            
            return result_path
            
        except Exception as e:
            logger.error(f"Failed to process {img_path}: {e}", exc_info=True)
            return None
    
    def process_batch(self, images_data: List[Dict]) -> List[Path]:
        """
        Process images - handles SRF with georeferencing properly
        """
        processed_images = []
        
        for i, img_data in enumerate(images_data):
            img_path = img_data['path']
            logger.info(f"=" * 70)
            logger.info(f"Processing image {i+1}/{len(images_data)}: {img_path.name}")
            total_start = time.time()
            
            if not img_path.exists():
                logger.error(f"File not found: {img_path}")
                continue
            
            # Check if it's an SRF file
            is_srf = img_path.suffix.lower() in {'.srf', '.SRF'}
            
            try:
                output_path = Config.OUTPUT_DIR / f"antarctic_{img_path.stem}.tif"
                
                if is_srf:
                    # Try SRF processor first (extracts embedded image)
                    logger.info("Processing as SRF - extracting embedded image")
                    result_path = SRFProcessor.process_srf(img_path, output_path)
                    
                    if result_path and result_path.exists():
                        processed_images.append(result_path)
                        elapsed = time.time() - total_start
                        logger.info(f"SRF processed successfully in {elapsed:.1f}s: {result_path}")
                        continue
                    else:
                        logger.warning("SRF processor failed, falling back to standard pipeline")
                
                # Standard pipeline for non-georeferenced images or SRF fallback
                logger.info("Using standard georeferencing pipeline")
                
                # Step 1: Preprocessing
                processed_path, transform_data = self.detect_and_correct_antarctic(img_path)
                
                if processed_path is None or not processed_path.exists():
                    logger.error("Preprocessing failed, using original image")
                    processed_path = img_path
                
                # Step 2: Georeferencing
                result_path = self.georeference_polar_image(processed_path, output_path)
                
                # Cleanup temp file
                if processed_path != img_path and processed_path.exists():
                    processed_path.unlink()
                
                if result_path and result_path.exists():
                    processed_images.append(result_path)
                    elapsed = time.time() - total_start
                    logger.info(f"Successfully processed {img_path.name} in {elapsed:.1f}s")
                    
                    if transform_data.get('rotated'):
                        logger.info(f"  - Rotated by {transform_data['angle']:.1f}°")
                    if transform_data.get('crop_w', 0) > 0:
                        logger.info(f"  - Cropped from {transform_data['original_width']}x{transform_data['original_height']} "
                                   f"to {transform_data['new_width']}x{transform_data['new_height']}")
                else:
                    logger.error(f"Failed to process {img_path.name}")
                    
            except Exception as e:
                logger.error(f"Failed to process {img_path.name}: {e}", exc_info=True)
                continue
        
        logger.info(f"=" * 70)
        logger.info(f"Processed {len(processed_images)}/{len(images_data)} images successfully")
        return processed_images
    
    def create_vrt(self, image_paths: List[Path], output_vrt_path: Path) -> Optional[Path]:
        """Create VRT from multiple images"""
        try:
            cmd = ['gdalbuildvrt', str(output_vrt_path)] + [str(p) for p in image_paths]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"gdalbuildvrt failed: {result.stderr}")
                return None
            
            logger.info(f"VRT created: {output_vrt_path}")
            return output_vrt_path
        except Exception as e:
            logger.error(f"VRT failed: {e}")
            return None
    
    def validate_bounds(self, image_path: Path) -> Dict:
        """Validate image bounds"""
        try:
            cmd = ['gdalinfo', '-json', str(image_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                return {'valid': False, 'error': result.stderr}
            
            info = json.loads(result.stdout)
            bounds = info.get('wgs84Extent', {})
            
            return {
                'bounds': bounds,
                'valid': True,
                'width': info.get('size', [0, 0])[0],
                'height': info.get('size', [0, 0])[1]
            }
        except Exception as e:
            return {'valid': False, 'error': str(e)}