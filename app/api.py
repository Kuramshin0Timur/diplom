from flask import Blueprint, request, jsonify, abort, send_file
from werkzeug.utils import secure_filename
from pathlib import Path
import json
import logging
from typing import Dict, List
from app.config import Config
from app.processor import ImageProcessor
from app.tiler import TileGenerator
from app.georeferencer import Georeferencer
from app.srf_processor import SRFProcessor
from datetime import datetime
import os
from PIL import Image, ImageDraw
import io
import re

# Increase PIL limit
Image.MAX_IMAGE_PIXELS = None

api_bp = Blueprint('api', __name__)
processor = ImageProcessor()
tiler = TileGenerator()
georeferencer = Georeferencer()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'tif', 'tiff', 'jpg', 'jpeg', 'png', 'srf', 'SRF'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {x.lower() for x in ALLOWED_EXTENSIONS}

def load_library_metadata():
    """Safe load library metadata from JSON file"""
    metadata_file = Config.LIBRARY_DIR / 'metadata.json'
    
    if not metadata_file.exists():
        default_metadata = {"version": "1.0", "created": datetime.now().isoformat(), "maps": []}
        with open(metadata_file, 'w') as f:
            json.dump(default_metadata, f, indent=2)
        return default_metadata
    
    try:
        with open(metadata_file, 'r') as f:
            content = f.read().strip()
            if not content:
                default_metadata = {"version": "1.0", "created": datetime.now().isoformat(), "maps": []}
                with open(metadata_file, 'w') as f2:
                    json.dump(default_metadata, f2, indent=2)
                return default_metadata
            
            data = json.loads(content)
            if 'maps' not in data:
                data['maps'] = []
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Metadata JSON decode error: {e}, recreating file")
        default_metadata = {"version": "1.0", "created": datetime.now().isoformat(), "maps": []}
        with open(metadata_file, 'w') as f:
            json.dump(default_metadata, f, indent=2)
        return default_metadata

def save_library_metadata(metadata):
    """Save library metadata to JSON file"""
    metadata_file = Config.LIBRARY_DIR / 'metadata.json'
    try:
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save metadata: {e}")
        return False

def get_image_preview(file_path: Path, max_size=(200, 200)):
    """Get image preview with proper format handling"""
    try:
        ext = file_path.suffix.lower()
        
        # SRF files - try to extract preview
        if ext in {'.srf', '.SRF'}:
            try:
                with Image.open(file_path) as img:
                    img.thumbnail(max_size, Image.Resampling.LANCZOS)
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    return img
            except:
                img = Image.new('RGB', max_size, color='#8e44ad')
                draw = ImageDraw.Draw(img)
                draw.text((max_size[0]//2, max_size[1]//2), "SRF\nFile", fill='white', anchor='mm', align='center')
                return img
        
        # Regular images
        with Image.open(file_path) as img:
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            elif img.mode == 'RGBA':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1])
                img = rgb_img
            
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            return img
            
    except Exception as e:
        logger.error(f"Failed to generate preview for {file_path}: {e}")
        img = Image.new('RGB', max_size, color='#e74c3c')
        draw = ImageDraw.Draw(img)
        draw.text((max_size[0]//2, max_size[1]//2), "Preview\nError", fill='white', anchor='mm', align='center')
        return img

@api_bp.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'antarctic-mapper'})

@api_bp.route('/tile-bounds', methods=['GET'])
def get_tile_bounds():
    return jsonify({
        'bounds': Config.ANTARCTIC_BOUNDS,
        'min_zoom': Config.MIN_ZOOM,
        'max_zoom': Config.MAX_ZOOM,
        'projection': Config.EPSG_ANTARCTIC,
        'tile_size': 256
    })

@api_bp.route('/library/maps', methods=['GET'])
def get_library_maps():
    """Get all maps from library"""
    try:
        metadata = load_library_metadata()
        
        maps = []
        seen_ids = set()
        
        # Scan antarctic directory
        antarctic_dir = Config.LIBRARY_DIR / 'antarctic'
        if antarctic_dir.exists():
            for img_path in antarctic_dir.iterdir():
                if img_path.is_file():
                    ext = img_path.suffix.lower()
                    if ext in {'.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf'}:
                        map_id = img_path.stem
                        if map_id not in seen_ids:
                            seen_ids.add(map_id)
                            maps.append({
                                'id': map_id,
                                'name': img_path.name,
                                'path': str(img_path),
                                'category': 'antarctic',
                                'type': ext[1:],
                                'size': img_path.stat().st_size,
                                'modified': datetime.fromtimestamp(img_path.stat().st_mtime).isoformat(),
                                'processed': False,
                                'gcps': []
                            })
        
        # Scan srf directory
        srf_dir = Config.LIBRARY_DIR / 'srf'
        if srf_dir.exists():
            for img_path in srf_dir.iterdir():
                if img_path.is_file():
                    ext = img_path.suffix.lower()
                    if ext in {'.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf'}:
                        map_id = img_path.stem
                        if map_id not in seen_ids:
                            seen_ids.add(map_id)
                            maps.append({
                                'id': map_id,
                                'name': img_path.name,
                                'path': str(img_path),
                                'category': 'srf',
                                'type': ext[1:],
                                'size': img_path.stat().st_size,
                                'modified': datetime.fromtimestamp(img_path.stat().st_mtime).isoformat(),
                                'processed': False,
                                'gcps': []
                            })
        
        # Merge with metadata
        metadata_maps = {m.get('id'): m for m in metadata.get('maps', [])}
        for map_item in maps:
            if map_item['id'] in metadata_maps:
                map_item['processed'] = metadata_maps[map_item['id']].get('processed', False)
                map_item['gcps'] = metadata_maps[map_item['id']].get('gcps', [])
                map_item['bounds'] = metadata_maps[map_item['id']].get('bounds', {})
                map_item['is_georeferenced'] = metadata_maps[map_item['id']].get('is_georeferenced', False)
                map_item['tile_stats'] = metadata_maps[map_item['id']].get('tile_stats', {})
        
        return jsonify({
            'maps': maps,
            'total': len(maps),
            'library_path': str(Config.LIBRARY_DIR)
        })
    except Exception as e:
        logger.error(f"Failed to get library maps: {e}", exc_info=True)
        return jsonify({'error': str(e), 'maps': [], 'total': 0}), 500

@api_bp.route('/library/add', methods=['POST'])
def add_to_library():
    """Add image to library"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        category = request.form.get('category', 'antarctic')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': f'File type not allowed'}), 400
        
        original_ext = Path(file.filename).suffix.lower()
        safe_name = secure_filename(Path(file.filename).stem)
        filename = safe_name + original_ext
        
        # Determine target directory
        if category == 'srf' or original_ext in {'.srf', '.SRF'}:
            target_dir = Config.LIBRARY_DIR / 'srf'
        else:
            target_dir = Config.LIBRARY_DIR / 'antarctic'
        
        target_dir.mkdir(exist_ok=True)
        target_path = target_dir / filename
        
        # Check if file exists
        if target_path.exists():
            return jsonify({'error': f'File {filename} already exists in library'}), 400
        
        # Save file
        file.save(target_path)
        
        # Check if SRF has georeferencing
        is_georeferenced = False
        if original_ext in {'.srf', '.SRF'}:
            try:
                has_georef, _ = SRFProcessor.has_georeferencing(target_path)
                is_georeferenced = has_georef
            except:
                pass
        
        # Update metadata
        metadata = load_library_metadata()
        
        map_exists = False
        for item in metadata['maps']:
            if item.get('id') == target_path.stem:
                map_exists = True
                break
        
        if not map_exists:
            metadata['maps'].append({
                'id': target_path.stem,
                'name': filename,
                'path': str(target_path),
                'category': category,
                'added': datetime.now().isoformat(),
                'processed': False,
                'gcps': [],
                'is_georeferenced': is_georeferenced
            })
            save_library_metadata(metadata)
        
        logger.info(f"Added {filename} to library (georeferenced: {is_georeferenced})")
        
        return jsonify({
            'success': True,
            'message': f'Added {filename} to library',
            'id': target_path.stem,
            'is_georeferenced': is_georeferenced
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to add to library: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/library/process/<map_id>', methods=['POST'])
def process_library_map(map_id):
    """Process a map from library by ID - handles SRF correctly"""
    try:
        data = request.get_json() or {}
        gcps = data.get('gcps', [])
        
        # Find the map file
        map_path = None
        is_srf = False
        
        # Check antarctic directory
        antarctic_dir = Config.LIBRARY_DIR / 'antarctic'
        if antarctic_dir.exists():
            for ext in ['.tif', '.tiff', '.jpg', '.jpeg', '.png']:
                test_path = antarctic_dir / f"{map_id}{ext}"
                if test_path.exists():
                    map_path = test_path
                    break
        
        # Check srf directory
        if not map_path:
            srf_dir = Config.LIBRARY_DIR / 'srf'
            if srf_dir.exists():
                for ext in ['.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf', '.SRF']:
                    test_path = srf_dir / f"{map_id}{ext}"
                    if test_path.exists():
                        map_path = test_path
                        is_srf = ext.lower() in {'.srf', '.SRF'}
                        break
        
        if not map_path:
            return jsonify({'error': f'Map {map_id} not found in library'}), 404
        
        logger.info(f"Processing library map: {map_path} (SRF: {is_srf})")
        
        # Process based on file type
        if is_srf:
            # Check if SRF has georeferencing
            try:
                has_georef, georef_info = SRFProcessor.has_georeferencing(map_path)
            except:
                has_georef = False
            
            if has_georef:
                logger.info(f"Processing georeferenced SRF: {map_path}")
                output_path = Config.OUTPUT_DIR / f"antarctic_{map_id}.tif"
                result_path = SRFProcessor.process_srf(map_path, output_path)
                
                if not result_path or not result_path.exists():
                    return jsonify({'error': 'SRF processing failed'}), 500
                
                # Generate tiles with map_id
                tile_stats = tiler.generate_tiles_from_vrt(result_path, map_id=map_id)
                logger.info(f"Generated {tile_stats['total_tiles']} tiles for map {map_id}")
            else:
                # SRF without georeferencing - use standard pipeline
                logger.info("SRF has no georeferencing, using standard pipeline")
                img_data = [{'path': map_path, 'gcps': gcps}]
                processed = processor.process_batch(img_data)
                
                if not processed:
                    return jsonify({'error': 'Failed to process image'}), 500
                
                source_for_tiles = processed[0]
                tile_stats = tiler.generate_tiles_from_vrt(source_for_tiles, map_id=map_id)
        else:
            # Standard processing for non-SRF files
            img_data = [{'path': map_path, 'gcps': gcps}]
            processed = processor.process_batch(img_data)
            
            if not processed:
                return jsonify({'error': 'Failed to process image'}), 500
            
            if len(processed) > 1:
                vrt_path = Config.TEMP_DIR / f"{map_id}_merged.vrt"
                vrt_path = processor.create_vrt(processed, vrt_path)
                source_for_tiles = vrt_path
            else:
                source_for_tiles = processed[0]
            
            tile_stats = tiler.generate_tiles_from_vrt(source_for_tiles, map_id=map_id)
        
        # Update metadata
        metadata = load_library_metadata()
        found = False
        for item in metadata['maps']:
            if item.get('id') == map_id:
                item['processed'] = True
                item['processed_date'] = datetime.now().isoformat()
                item['tile_stats'] = tile_stats
                if gcps:
                    item['gcps'] = gcps
                if is_srf:
                    item['is_georeferenced'] = True
                found = True
                break
        
        if not found:
            metadata['maps'].append({
                'id': map_id,
                'name': map_path.name,
                'path': str(map_path),
                'processed': True,
                'processed_date': datetime.now().isoformat(),
                'tile_stats': tile_stats,
                'gcps': gcps,
                'is_georeferenced': is_srf
            })
        
        save_library_metadata(metadata)
        
        return jsonify({
            'success': True,
            'map_id': map_id,
            'tile_stats': tile_stats,
            'preserved_georeferencing': is_srf and has_georef if is_srf else False
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to process library map: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/library/batch-process', methods=['POST'])
def batch_process_library():
    """Batch process multiple maps from library"""
    try:
        data = request.get_json()
        if not data or 'map_ids' not in data:
            return jsonify({'error': 'No map IDs provided'}), 400
        
        map_ids = data.get('map_ids', [])
        gcps_map = data.get('gcps', {})
        
        results = []
        
        for map_id in map_ids:
            try:
                # Find the map
                map_path = None
                is_srf = False
                
                for category_dir in ['antarctic', 'srf']:
                    category_path = Config.LIBRARY_DIR / category_dir
                    if category_path.exists():
                        for ext in ['.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf', '.SRF']:
                            test_path = category_path / f"{map_id}{ext}"
                            if test_path.exists():
                                map_path = test_path
                                is_srf = ext.lower() in {'.srf', '.SRF'}
                                break
                    if map_path:
                        break
                
                if not map_path:
                    results.append({'map_id': map_id, 'success': False, 'error': 'Not found'})
                    continue
                
                # Process based on type
                if is_srf:
                    try:
                        has_georef, _ = SRFProcessor.has_georeferencing(map_path)
                    except:
                        has_georef = False
                    
                    if has_georef:
                        output_path = Config.OUTPUT_DIR / f"antarctic_{map_id}.tif"
                        result_path = SRFProcessor.process_srf(map_path, output_path)
                        if result_path:
                            tiler.generate_tiles_from_vrt(result_path, map_id=map_id)
                            results.append({'map_id': map_id, 'success': True})
                        else:
                            results.append({'map_id': map_id, 'success': False, 'error': 'SRF processing failed'})
                    else:
                        gcps = gcps_map.get(map_id, [])
                        img_data = [{'path': map_path, 'gcps': gcps}]
                        processed = processor.process_batch(img_data)
                        if processed:
                            tiler.generate_tiles_from_vrt(processed[0], map_id=map_id)
                            results.append({'map_id': map_id, 'success': True})
                        else:
                            results.append({'map_id': map_id, 'success': False, 'error': 'Processing failed'})
                else:
                    gcps = gcps_map.get(map_id, [])
                    img_data = [{'path': map_path, 'gcps': gcps}]
                    processed = processor.process_batch(img_data)
                    if processed:
                        tiler.generate_tiles_from_vrt(processed[0], map_id=map_id)
                        results.append({'map_id': map_id, 'success': True})
                    else:
                        results.append({'map_id': map_id, 'success': False, 'error': 'Processing failed'})
                    
            except Exception as e:
                results.append({'map_id': map_id, 'success': False, 'error': str(e)})
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results),
            'successful': sum(1 for r in results if r['success'])
        }), 200
        
    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/library/delete/<map_id>', methods=['DELETE'])
def delete_from_library(map_id):
    """Delete map from library"""
    try:
        deleted = False
        
        # Delete from directories
        for category_dir in ['antarctic', 'srf']:
            dir_path = Config.LIBRARY_DIR / category_dir
            if dir_path.exists():
                for ext in ['.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf', '.SRF']:
                    file_path = dir_path / f"{map_id}{ext}"
                    if file_path.exists():
                        file_path.unlink()
                        deleted = True
                        logger.info(f"Deleted {file_path}")
                        break
        
        # Delete tiles directory for this map
        tiles_dir = Config.TILES_DIR / map_id
        if tiles_dir.exists():
            import shutil
            shutil.rmtree(tiles_dir)
            logger.info(f"Deleted tiles for map {map_id}")
        
        # Remove from metadata
        metadata = load_library_metadata()
        metadata['maps'] = [m for m in metadata['maps'] if m.get('id') != map_id]
        save_library_metadata(metadata)
        
        return jsonify({'success': True, 'deleted': deleted}), 200
        
    except Exception as e:
        logger.error(f"Failed to delete map: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/library/maps/<map_id>/thumbnail', methods=['GET'])
def get_map_thumbnail(map_id):
    """Get thumbnail for a map"""
    try:
        # Find the map file
        map_path = None
        
        # Check directories
        for category_dir in ['antarctic', 'srf']:
            dir_path = Config.LIBRARY_DIR / category_dir
            if dir_path.exists():
                for ext in ['.tif', '.tiff', '.jpg', '.jpeg', '.png', '.srf', '.SRF']:
                    file_path = dir_path / f"{map_id}{ext}"
                    if file_path.exists():
                        map_path = file_path
                        break
                if map_path:
                    break
        
        if not map_path:
            # Return default placeholder
            img = Image.new('RGB', (200, 200), color='#2c3e50')
            draw = ImageDraw.Draw(img)
            draw.text((100, 100), "No\nPreview", fill='white', anchor='mm', align='center')
            img_io = io.BytesIO()
            img.save(img_io, 'PNG')
            img_io.seek(0)
            return send_file(img_io, mimetype='image/png')
        
        # Process image
        with Image.open(map_path) as img:
            img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            
            if img.mode != 'RGB':
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    rgb_img.paste(img, mask=img.split()[-1])
                else:
                    rgb_img.paste(img)
                img = rgb_img
            
            img_io = io.BytesIO()
            img.save(img_io, 'PNG', optimize=True)
            img_io.seek(0)
            
            return send_file(img_io, mimetype='image/png')
        
    except Exception as e:
        logger.error(f"Failed to generate thumbnail: {e}")
        img = Image.new('RGB', (200, 200), color='#e74c3c')
        draw = ImageDraw.Draw(img)
        draw.text((100, 100), "Error", fill='white', anchor='mm')
        img_io = io.BytesIO()
        img.save(img_io, 'PNG')
        img_io.seek(0)
        return send_file(img_io, mimetype='image/png')

@api_bp.route('/points', methods=['GET'])
def get_points():
    """Get all georeferenced points from processed images"""
    points = []
    
    if Config.OUTPUT_DIR.exists():
        for tif_path in Config.OUTPUT_DIR.glob('*.tif'):
            try:
                import rasterio
                with rasterio.open(tif_path) as src:
                    bounds = src.bounds
                    points.append({
                        'id': tif_path.stem,
                        'name': tif_path.name,
                        'bounds': {
                            'minx': bounds.left,
                            'miny': bounds.bottom,
                            'maxx': bounds.right,
                            'maxy': bounds.top
                        },
                        'center': {
                            'x': (bounds.left + bounds.right) / 2,
                            'y': (bounds.bottom + bounds.top) / 2
                        }
                    })
            except Exception as e:
                logger.error(f"Failed to read {tif_path}: {e}")
    
    return jsonify(points)

@api_bp.route('/process', methods=['POST'])
def process_images():
    """Process uploaded images with georeferencing"""
    try:
        if 'files' not in request.files:
            return jsonify({'error': 'No files provided'}), 400
        
        files = request.files.getlist('files')
        
        if not files or files[0].filename == '':
            return jsonify({'error': 'No files selected'}), 400
        
        gcps_data = request.form.get('gcps', '[]')
        try:
            gcps_list = json.loads(gcps_data)
        except:
            gcps_list = []
        
        saved_images = []
        for idx, file in enumerate(files):
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                save_path = Config.INPUT_DIR / filename
                file.save(save_path)
                
                img_data = {
                    'path': save_path,
                    'gcps': gcps_list[idx] if idx < len(gcps_list) else []
                }
                saved_images.append(img_data)
        
        if not saved_images:
            return jsonify({'error': 'No valid images uploaded'}), 400
        
        logger.info(f"Processing {len(saved_images)} images")
        processed = processor.process_batch(saved_images)
        
        if not processed:
            return jsonify({'error': 'Failed to process any images'}), 500
        
        if len(processed) > 1:
            vrt_path = Config.TEMP_DIR / "merged_antarctic.vrt"
            vrt_path = processor.create_vrt(processed, vrt_path)
            source_for_tiles = vrt_path
            map_id = "merged"
        else:
            source_for_tiles = processed[0]
            map_id = Path(processed[0]).stem.replace('antarctic_', '')
        
        validation = processor.validate_bounds(source_for_tiles)
        if not validation.get('valid', False):
            logger.warning(f"Image bounds may be outside Antarctic region")
        
        logger.info("Generating tiles...")
        tile_stats = tiler.generate_tiles_from_vrt(source_for_tiles, map_id=map_id)
        
        # Cleanup temp files
        for temp_file in Config.TEMP_DIR.glob('georef_*'):
            if temp_file.exists():
                temp_file.unlink()
        
        return jsonify({
            'success': True,
            'processed_images': [str(p) for p in processed],
            'tile_stats': tile_stats,
            'validation': validation,
            'total_images': len(processed),
            'map_id': map_id
        }), 200
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/gcps/detect', methods=['POST'])
def detect_gcps():
    """Auto-detect GCPs from image"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        filename = secure_filename(file.filename)
        temp_path = Config.TEMP_DIR / filename
        file.save(temp_path)
        
        gcps = georeferencer.auto_detect_gcps_from_lonlat(temp_path, {})
        
        if temp_path.exists():
            temp_path.unlink()
        
        return jsonify({
            'gcps': gcps,
            'count': len(gcps)
        }), 200
        
    except Exception as e:
        logger.error(f"GCP detection failed: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tiles/exists/<int:z>/<int:x>/<int:y>', methods=['GET'])
def check_tile_exists(z, x, y):
    """Check if tile exists (legacy)"""
    return jsonify({'exists': False})
# В api.py, замените функцию upload_earthquakes и get_earthquakes:

@api_bp.route('/earthquakes/upload', methods=['POST'])
def upload_earthquakes():
    """Upload and parse CSV file with earthquake data"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'File must be CSV format'}), 400
        
        # Read CSV content
        content = file.read().decode('utf-8')
        lines = content.strip().split('\n')
        
        if len(lines) < 2:
            return jsonify({'error': 'CSV file is empty'}), 400
        
        # Parse header
        header = lines[0].split(',')
        
        # Normalize header
        normalized_header = [col.strip().lower().replace('"', '') for col in header]
        
        # Find column indices
        lat_idx = None
        lon_idx = None
        date_idx = None
        time_idx = None
        mag_idx = None
        name_idx = None
        depth_idx = None
        
        for i, col in enumerate(normalized_header):
            if 'lat' in col:
                lat_idx = i
            elif 'lon' in col or 'long' in col:
                lon_idx = i
            elif 'date' in col:
                date_idx = i
            elif 'time' in col:
                time_idx = i
            elif 'mag' in col or 'magnitude' in col:
                mag_idx = i
            elif 'name' in col or 'place' in col or 'location' in col:
                name_idx = i
            elif 'depth' in col:
                depth_idx = i
        
        if lat_idx is None or lon_idx is None:
            return jsonify({'error': 'CSV must contain Latitude and Longitude columns'}), 400
        
        # Parse data with better error handling
        earthquakes = []
        skipped = 0
        
        for line_num, line in enumerate(lines[1:], start=2):
            if not line.strip():
                continue
            
            # Handle quoted fields properly
            parts = []
            current = ''
            in_quotes = False
            
            for char in line:
                if char == '"' and not in_quotes:
                    in_quotes = True
                elif char == '"' and in_quotes:
                    in_quotes = False
                elif char == ',' and not in_quotes:
                    parts.append(current.strip())
                    current = ''
                else:
                    current += char
            parts.append(current.strip())
            
            # Remove quotes from parts
            parts = [p.strip('"') for p in parts]
            
            if len(parts) <= max(lat_idx, lon_idx):
                skipped += 1
                continue
            
            try:
                lat_str = parts[lat_idx].strip().replace('°', '').replace('S', '-').replace('N', '')
                lon_str = parts[lon_idx].strip().replace('°', '').replace('W', '-').replace('E', '')
                
                lat = float(lat_str)
                lon = float(lon_str)
                
                # Validate coordinates
                if lat < -90 or lat > -60:  # Antarctic range
                    lat = max(-90, min(lat, -60))
                
                if lon < -180 or lon > 180:
                    lon = ((lon + 180) % 360) - 180
                
                quake_mag = 4.0
                if mag_idx is not None and len(parts) > mag_idx and parts[mag_idx].strip():
                    try:
                        quake_mag = float(parts[mag_idx].strip())
                    except:
                        pass
                
                quake = {
                    'lat': lat,
                    'lon': lon,
                    'date': parts[date_idx].strip() if date_idx is not None and len(parts) > date_idx else '',
                    'time': parts[time_idx].strip() if time_idx is not None and len(parts) > time_idx else '',
                    'magnitude': quake_mag,
                    'name': parts[name_idx].strip() if name_idx is not None and len(parts) > name_idx and parts[name_idx].strip() else f"Magnitude {quake_mag:.1f} Earthquake",
                    'depth': float(parts[depth_idx].strip()) if depth_idx is not None and len(parts) > depth_idx and parts[depth_idx].strip() else 10.0
                }
                
                earthquakes.append(quake)
                
            except ValueError as e:
                logger.warning(f"Line {line_num}: Failed to parse {e}")
                skipped += 1
                continue
        
        # Save ALL earthquakes (no limit)
        earthquakes_file = Config.DATA_DIR / 'earthquakes.json'
        with open(earthquakes_file, 'w') as f:
            json.dump(earthquakes, f, indent=2)
        
        logger.info(f"Saved {len(earthquakes)} earthquakes to file")
        
        return jsonify({
            'success': True,
            'message': f'Loaded {len(earthquakes)} earthquakes (skipped {skipped})',
            'count': len(earthquakes),
            'skipped': skipped
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to upload earthquakes: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@api_bp.route('/earthquakes', methods=['GET'])
def get_earthquakes():
    """Get all earthquakes with pagination support"""
    try:
        earthquakes_file = Config.DATA_DIR / 'earthquakes.json'
        if not earthquakes_file.exists():
            return jsonify({'earthquakes': [], 'count': 0, 'total': 0}), 200
        
        with open(earthquakes_file, 'r') as f:
            earthquakes = json.load(f)
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 5000, type=int)  # Increase to 5000 per request
        
        # Calculate pagination
        total = len(earthquakes)
        start = (page - 1) * per_page
        end = start + per_page
        
        paginated = earthquakes[start:end]
        
        return jsonify({
            'earthquakes': paginated,
            'count': len(paginated),
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': end < total
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get earthquakes: {e}")
        return jsonify({'error': str(e)}), 500
@api_bp.route('/earthquakes', methods=['GET'])
def get_earthquakes():
    """Get all earthquakes with pagination support"""
    try:
        earthquakes_file = Config.DATA_DIR / 'earthquakes.json'
        if not earthquakes_file.exists():
            return jsonify({'earthquakes': [], 'count': 0, 'total': 0}), 200
        
        with open(earthquakes_file, 'r') as f:
            earthquakes = json.load(f)
        
        # Get pagination parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 1000, type=int)  # Limit to 1000 per request
        
        # Calculate pagination
        total = len(earthquakes)
        start = (page - 1) * per_page
        end = start + per_page
        
        paginated = earthquakes[start:end]
        
        return jsonify({
            'earthquakes': paginated,
            'count': len(paginated),
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_more': end < total
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get earthquakes: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/earthquakes/stats', methods=['GET'])
def get_earthquakes_stats():
    """Get statistics about earthquakes"""
    try:
        earthquakes_file = Config.DATA_DIR / 'earthquakes.json'
        if not earthquakes_file.exists():
            return jsonify({'total': 0, 'date_range': None}), 200
        
        with open(earthquakes_file, 'r') as f:
            earthquakes = json.load(f)
        
        total = len(earthquakes)
        
        # Get date range if dates exist
        dates = [eq.get('date') for eq in earthquakes if eq.get('date')]
        date_range = None
        if dates:
            date_range = {
                'min': min(dates),
                'max': max(dates)
            }
        
        # Get magnitude range
        magnitudes = [eq.get('magnitude', 0) for eq in earthquakes if eq.get('magnitude')]
        mag_range = None
        if magnitudes:
            mag_range = {
                'min': min(magnitudes),
                'max': max(magnitudes),
                'avg': sum(magnitudes) / len(magnitudes)
            }
        
        return jsonify({
            'total': total,
            'date_range': date_range,
            'magnitude_range': mag_range
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/earthquakes/clear', methods=['DELETE'])
def clear_earthquakes():
    """Clear all earthquakes data"""
    try:
        earthquakes_file = Config.DATA_DIR / 'earthquakes.json'
        if earthquakes_file.exists():
            earthquakes_file.unlink()
        return jsonify({'success': True, 'message': 'Earthquakes cleared'}), 200
    except Exception as e:
        logger.error(f"Failed to clear earthquakes: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/layers/generate', methods=['POST'])
def generate_layers():
    """Generate auxiliary layers (grid, coastline)"""
    try:
        data = request.get_json() or {}
        generate_grid = data.get('grid', True)
        generate_coastline = data.get('coastline', True)
        
        results = {}
        
        if generate_grid:
            from app.coordinate_layer import CoordinateLayer
            grid_stats = CoordinateLayer.generate_grid_tiles()
            results['grid'] = grid_stats
        
        if generate_coastline:
            from app.coastline_layer import CoastlineLayer
            coastline_stats = CoastlineLayer.generate_coastline_tiles()
            results['coastline'] = coastline_stats
        
        return jsonify({
            'success': True,
            'layers_generated': results
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to generate layers: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/layers/enable', methods=['POST'])
def enable_layer():
    """Enable/disable layer"""
    data = request.get_json()
    layer_name = data.get('layer')
    enabled = data.get('enabled', True)
    
    # Save layer state
    layers_config = Config.DATA_DIR / 'layers_config.json'
    
    if layers_config.exists():
        with open(layers_config, 'r') as f:
            config = json.load(f)
    else:
        config = {}
    
    config[layer_name] = enabled
    
    with open(layers_config, 'w') as f:
        json.dump(config, f)
    
    return jsonify({'success': True, 'layer': layer_name, 'enabled': enabled})

@api_bp.route('/coordinates/upload', methods=['POST'])
def upload_coordinates():
    """Batch upload coordinates from CSV"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not file.filename.endswith('.csv'):
            return jsonify({'error': 'File must be CSV format'}), 400
        
        content = file.read().decode('utf-8')
        lines = content.strip().split('\n')
        
        # Parse CSV
        header = lines[0].split(',')
        
        # Determine columns
        lat_idx = None
        lon_idx = None
        name_idx = None
        desc_idx = None
        
        for i, col in enumerate(header):
            col_lower = col.lower().strip()
            if 'lat' in col_lower:
                lat_idx = i
            elif 'lon' in col_lower or 'long' in col_lower:
                lon_idx = i
            elif 'name' in col_lower or 'label' in col_lower:
                name_idx = i
            elif 'desc' in col_lower or 'description' in col_lower:
                desc_idx = i
        
        if lat_idx is None or lon_idx is None:
            return jsonify({'error': 'CSV must contain Latitude and Longitude columns'}), 400
        
        # Load coordinates
        coordinates = []
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split(',')
            if len(parts) <= max(lat_idx, lon_idx):
                continue
            
            try:
                coord = {
                    'lat': float(parts[lat_idx].strip()),
                    'lon': float(parts[lon_idx].strip()),
                    'name': parts[name_idx].strip() if name_idx is not None and len(parts) > name_idx else '',
                    'description': parts[desc_idx].strip() if desc_idx is not None and len(parts) > desc_idx else ''
                }
                coordinates.append(coord)
            except ValueError:
                continue
        
        # Save
        coords_file = Config.DATA_DIR / 'coordinates.json'
        with open(coords_file, 'w') as f:
            json.dump(coordinates, f, indent=2)
        
        return jsonify({
            'success': True,
            'message': f'Loaded {len(coordinates)} coordinates',
            'count': len(coordinates),
            'coordinates': coordinates
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to upload coordinates: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/coordinates', methods=['GET'])
def get_coordinates():
    """Get all uploaded coordinates"""
    try:
        coords_file = Config.DATA_DIR / 'coordinates.json'
        if coords_file.exists():
            with open(coords_file, 'r') as f:
                coordinates = json.load(f)
            return jsonify({'coordinates': coordinates, 'count': len(coordinates)})
        return jsonify({'coordinates': [], 'count': 0})
    except Exception as e:
        logger.error(f"Failed to get coordinates: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/gcps/batch', methods=['POST'])
def batch_gcps():
    """Upload multiple GCPs via CSV"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        content = file.read().decode('utf-8')
        lines = content.strip().split('\n')
        
        # Expected format: pixel_x,pixel_y,longitude,latitude
        gcps = []
        for line in lines[1:]:  # Skip header
            if not line.strip():
                continue
            parts = line.split(',')
            if len(parts) >= 4:
                try:
                    gcp = {
                        'pixel_x': float(parts[0].strip()),
                        'pixel_y': float(parts[1].strip()),
                        'longitude': float(parts[2].strip()),
                        'latitude': float(parts[3].strip())
                    }
                    gcps.append(gcp)
                except ValueError:
                    continue
        
        return jsonify({
            'success': True,
            'gcps': gcps,
            'count': len(gcps)
        }), 200
        
    except Exception as e:
        logger.error(f"Batch GCP upload failed: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/map/rmse/<map_id>', methods=['GET'])
def get_rmse(map_id):
    """Get RMSE for a specific map"""
    try:
        metadata = load_library_metadata()
        
        for map_item in metadata.get('maps', []):
            if map_item.get('id') == map_id:
                return jsonify({
                    'rmse': map_item.get('rmse', None),
                    'max_error': map_item.get('max_error', None),
                    'gcps_count': len(map_item.get('gcps', [])),
                    'method': 'Affine Transformation'
                })
        
        return jsonify({'error': 'Map not found'}), 404
        
    except Exception as e:
        logger.error(f"Failed to get RMSE: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/library/maps/<map_id>/info', methods=['GET'])
def get_map_info(map_id):
    """Get detailed information about a map"""
    try:
        metadata = load_library_metadata()
        for map_item in metadata.get('maps', []):
            if map_item.get('id') == map_id:
                return jsonify({
                    'id': map_item.get('id'),
                    'name': map_item.get('name'),
                    'processed': map_item.get('processed', False),
                    'tile_stats': map_item.get('tile_stats', {}),
                    'bounds': map_item.get('bounds', {}),
                    'size': map_item.get('size', 0),
                    'modified': map_item.get('modified', '')
                })
        return jsonify({'error': 'Map not found'}), 404
    except Exception as e:
        logger.error(f"Failed to get map info: {e}")
        return jsonify({'error': str(e)}), 500