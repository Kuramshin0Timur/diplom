import subprocess
import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple
import numpy as np
from PIL import Image
import rasterio
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps
from rasterio.crs import CRS
from app.config import Config

logger = logging.getLogger(__name__)

class SRFProcessor:
    """SRF processor that PRESERVES original georeferencing"""
    
    @staticmethod
    def extract_georeferencing(srf_path: Path) -> Optional[Dict]:
        """
        Извлекает оригинальную геопривязку из SRF файла используя GDAL
        GDAL умеет читать геопривязку из многих форматов, включая SRF
        """
        try:
            # Используем gdalinfo для получения геопривязки
            cmd = ['gdalinfo', '-json', str(srf_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.warning(f"gdalinfo failed: {result.stderr}")
                return None
            
            info = json.loads(result.stdout)
            
            georef_info = {}
            
            # Извлекаем геотрансформ (affine transformation)
            if 'geoTransform' in info:
                georef_info['transform'] = info['geoTransform']
                logger.info(f"Found geoTransform: {georef_info['transform']}")
            
            # Извлекаем CRS
            if 'crs' in info:
                georef_info['crs'] = info['crs']
                logger.info(f"Found CRS: {georef_info['crs']}")
            elif 'coordinateSystem' in info:
                georef_info['crs'] = info['coordinateSystem']
                logger.info(f"Found coordinateSystem")
            
            # Извлекаем GCPs если есть
            if 'gcps' in info and info['gcps']:
                georef_info['gcps'] = info['gcps']
                logger.info(f"Found {len(info['gcps'])} GCPs")
            
            # Извлекаем bounds
            if 'wgs84Extent' in info:
                georef_info['bounds'] = info['wgs84Extent']
            
            if georef_info:
                logger.info(f"Successfully extracted georeferencing from SRF")
                return georef_info
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to extract georeferencing: {e}")
            return None
    
    @staticmethod
    def extract_image_data(srf_path: Path, output_png: Path) -> Optional[Path]:
        """
        Извлекает изображение из SRF сохраняя оригинальные пиксели
        """
        try:
            # Метод 1: Пробуем открыть через GDAL как растр
            cmd = ['gdal_translate', '-of', 'PNG', str(srf_path), str(output_png)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and output_png.exists():
                logger.info(f"Extracted image via GDAL: {output_png}")
                return output_png
            
            # Метод 2: Пробуем через PIL (если формат поддерживается)
            try:
                img = Image.open(srf_path)
                img.save(output_png, 'PNG')
                logger.info(f"Extracted image via PIL: {output_png}")
                return output_png
            except:
                pass
            
            # Метод 3: Ищем встроенное изображение (PNG/JPEG/TIFF)
            with open(srf_path, 'rb') as f:
                data = f.read()
                
                # Ищем PNG сигнатуру
                png_sig = b'\x89PNG\r\n\x1a\n'
                png_pos = data.find(png_sig)
                if png_pos != -1:
                    logger.info(f"Found embedded PNG at {png_pos}")
                    # Сохраняем PNG данные
                    with open(output_png, 'wb') as out:
                        out.write(data[png_pos:])
                    return output_png
            
            logger.error("Could not extract image data from SRF")
            return None
            
        except Exception as e:
            logger.error(f"Failed to extract image: {e}")
            return None
    
    @staticmethod
    def create_geotiff_with_original_georef(
        image_path: Path, 
        georef_info: Dict, 
        output_path: Path
    ) -> Optional[Path]:
        """
        Создает GeoTIFF с ИСХОДНОЙ геопривязкой из SRF
        БЕЗ создания новых GCP или трансформаций
        """
        try:
            # Открываем изображение
            with Image.open(image_path) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                width, height = img.size
                img_array = np.array(img)
            
            # Если есть GCP - используем их
            if 'gcps' in georef_info and georef_info['gcps']:
                gcps = []
                for gcp_data in georef_info['gcps']:
                    gcp = GroundControlPoint(
                        row=gcp_data.get('row', gcp_data.get('y', 0)),
                        col=gcp_data.get('col', gcp_data.get('x', 0)),
                        x=gcp_data.get('longitude', gcp_data.get('x', 0)),
                        y=gcp_data.get('latitude', gcp_data.get('y', 0)),
                        z=gcp_data.get('z', 0),
                        id=gcp_data.get('id', '')
                    )
                    gcps.append(gcp)
                
                transform = from_gcps(gcps)
                crs = CRS.from_epsg(4326)  # WGS84 для GCP
                
            # Если есть geoTransform - используем его
            elif 'transform' in georef_info:
                transform_data = georef_info['transform']
                from rasterio.transform import Affine
                
                transform = Affine(
                    transform_data[1],  # a
                    transform_data[2],  # b
                    transform_data[0],  # c (minx)
                    transform_data[4],  # d
                    transform_data[5],  # e
                    transform_data[3]   # f (maxy)
                )
                
                # Парсим CRS
                if 'crs' in georef_info:
                    crs_str = georef_info['crs'].get('wkt', '')
                    if 'EPSG:3031' in crs_str or 'Antarctic Polar Stereographic' in crs_str:
                        crs = CRS.from_epsg(3031)
                    else:
                        crs = CRS.from_string(crs_str)
                else:
                    crs = CRS.from_epsg(3031)  # По умолчанию Antarctic
            
            else:
                logger.error("No georeferencing information found")
                return None
            
            # Создаем GeoTIFF с оригинальной геопривязкой
            with rasterio.open(
                output_path,
                'w',
                driver='GTiff',
                height=height,
                width=width,
                count=3,
                dtype=img_array.dtype,
                crs=crs,
                transform=transform,
                compress='lzw',
                tiled=True
            ) as dst:
                # Переносим RGB каналы
                for band in range(3):
                    dst.write(img_array[:, :, band], band + 1)
            
            logger.info(f"Created GeoTIFF with original georeferencing: {output_path}")
            logger.info(f"  CRS: {crs}")
            logger.info(f"  Size: {width}x{height}")
            
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to create GeoTIFF: {e}", exc_info=True)
            return None
    
    @staticmethod
    def has_georeferencing(srf_path: Path) -> Tuple[bool, Dict]:
        """Проверяет наличие геопривязки в SRF"""
        georef = SRFProcessor.extract_georeferencing(srf_path)
        return (georef is not None, georef or {})
    
    @staticmethod
    def process_srf(srf_path: Path, output_path: Path) -> Optional[Path]:
        """
        ПОЛНЫЙ ПРАВИЛЬНЫЙ pipeline для SRF:
        1. Извлекаем оригинальную геопривязку
        2. Извлекаем изображение
        3. Создаем GeoTIFF с сохранением оригинальной геопривязки
        """
        try:
            logger.info(f"=" * 60)
            logger.info(f"Processing SRF with original georeferencing preservation")
            logger.info(f"Input: {srf_path}")
            
            # ШАГ 1: Извлекаем геопривязку из SRF
            georef_info = SRFProcessor.extract_georeferencing(srf_path)
            
            if not georef_info:
                logger.warning("No georeferencing found in SRF")
                logger.warning("Falling back to standard polar extent assignment")
                # Если нет геопривязки - используем стандартный метод
                return SRFProcessor.fallback_to_polar_extent(srf_path, output_path)
            
            logger.info(f"✓ Extracted original georeferencing")
            
            # ШАГ 2: Извлекаем изображение
            temp_png = Config.TEMP_DIR / f"{srf_path.stem}_image.png"
            image_path = SRFProcessor.extract_image_data(srf_path, temp_png)
            
            if not image_path or not image_path.exists():
                logger.error("Failed to extract image data")
                return None
            
            logger.info(f"✓ Extracted image: {image_path}")
            
            # ШАГ 3: Создаем GeoTIFF с оригинальной геопривязкой
            result = SRFProcessor.create_geotiff_with_original_georef(
                image_path, georef_info, output_path
            )
            
            # Очистка
            if temp_png.exists():
                temp_png.unlink()
            
            if result and result.exists():
                logger.info(f"✓ SRF processing complete: {output_path}")
                return result
            
            logger.error("Failed to create GeoTIFF")
            return None
            
        except Exception as e:
            logger.error(f"SRF processing failed: {e}", exc_info=True)
            return None
    
    @staticmethod
    def fallback_to_polar_extent(srf_path: Path, output_path: Path) -> Optional[Path]:
        """Fallback: используем стандартный polar extent (без геопривязки)"""
        try:
            # Извлекаем изображение
            temp_png = Config.TEMP_DIR / f"{srf_path.stem}_fallback.png"
            image_path = SRFProcessor.extract_image_data(srf_path, temp_png)
            
            if not image_path:
                return None
            
            # Присваиваем стандартные границы Антарктиды
            with Image.open(image_path) as img:
                width, height = img.size
            
            left = Config.ANTARCTIC_BOUNDS['minx']
            right = Config.ANTARCTIC_BOUNDS['maxx']
            top = Config.ANTARCTIC_BOUNDS['maxy']
            bottom = Config.ANTARCTIC_BOUNDS['miny']
            
            cmd = [
                'gdal_translate',
                '-of', 'GTiff',
                '-a_srs', Config.EPSG_ANTARCTIC,
                '-a_ullr', str(left), str(top), str(right), str(bottom),
                '-co', 'COMPRESS=NONE',
                str(image_path),
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if temp_png.exists():
                temp_png.unlink()
            
            if result.returncode == 0 and output_path.exists():
                logger.info(f"Fallback polar extent assigned: {output_path}")
                return output_path
            
            return None
            
        except Exception as e:
            logger.error(f"Fallback failed: {e}")
            return None