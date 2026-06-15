import json
import logging
from pathlib import Path
from typing import List, Tuple
import numpy as np
from app.config import Config

logger = logging.getLogger(__name__)

class CoastlineLayer:
    """Генератор тайлов береговой линии из данных OpenStreetMap/GSHHG"""
    
    @staticmethod
    def load_coastline_data() -> List[List[Tuple[float, float]]]:
        """
        Загружает данные береговой линии из встроенного JSON или
        генерирует упрощенную береговую линию Антарктиды
        """
        coastline_file = Config.DATA_DIR / 'coastline.json'
        
        if coastline_file.exists():
            with open(coastline_file, 'r') as f:
                return json.load(f)
        
        # Встроенные упрощенные данные для Антарктиды
        # Основные точки контура Антарктиды (приблизительные)
        antarctic_coast = [
            # Полуостров Антарктида
            [-75, -70], [-74, -69], [-72, -68], [-70, -67], [-68, -66],
            [-66, -65], [-64, -65], [-62, -66], [-60, -67], [-58, -68],
            # Земля Уилкса
            [-60, -70], [-65, -72], [-70, -75], [-75, -78], [-80, -80],
            [-85, -82], [-90, -84], [-95, -85], [-100, -86], [-105, -86],
            # Земля Королевы Мод
            [-110, -85], [-115, -84], [-120, -82], [-125, -80], [-130, -78],
            [-135, -76], [-140, -75], [-145, -74], [-150, -73], [-155, -72],
            # Земля Мэри Бэрд
            [-160, -71], [-165, -70], [-170, -69], [-175, -68], [180, -67],
            [175, -66], [170, -65], [165, -65], [160, -66], [155, -67],
            # Земля Виктории
            [150, -68], [145, -69], [140, -70], [135, -71], [130, -72],
            [125, -73], [120, -74], [115, -75], [110, -76], [105, -77],
            # Завершаем круг
            [100, -78], [95, -79], [90, -80], [85, -79], [80, -78],
            [75, -77], [70, -76], [65, -75], [60, -74], [55, -73],
            [50, -72], [45, -71], [40, -70], [35, -69], [30, -68],
            [25, -67], [20, -66], [15, -65], [10, -65], [5, -66],
            [0, -67], [-5, -68], [-10, -69], [-15, -70], [-20, -71],
            [-25, -72], [-30, -73], [-35, -74], [-40, -75], [-45, -76],
            [-50, -77], [-55, -78], [-60, -79], [-65, -80], [-70, -81],
            [-72, -82], [-74, -80], [-75, -75], [-75, -70]
        ]
        
        # Конвертируем в список сегментов
        coastline_segments = [antarctic_coast]
        
        # Сохраняем для будущего использования
        coastline_file.parent.mkdir(parents=True, exist_ok=True)
        with open(coastline_file, 'w') as f:
            json.dump(coastline_segments, f)
        
        return coastline_segments
    
    @staticmethod
    def generate_coastline_tiles(map_id: str = "coastline"):
        """
        Генерирует тайлы с береговой линией
        """
        from app.tiler import TileGenerator
        
        tile_gen = TileGenerator()
        coastline_dir = Config.TILES_DIR / map_id
        coastline_dir.mkdir(parents=True, exist_ok=True)
        
        coastline_data = CoastlineLayer.load_coastline_data()
        zoom_levels = range(Config.MIN_ZOOM, 7)
        
        stats = {'total_tiles': 0}
        
        for z in zoom_levels:
            tiles_per_side = 2 ** z
            tiles_count = 0
            
            for x in range(tiles_per_side):
                for y in range(tiles_per_side):
                    minx, miny, maxx, maxy = tile_gen.get_tile_bounds(z, x, y)
                    
                    tile_img = CoastlineLayer._render_coastline_tile(
                        coastline_data, minx, miny, maxx, maxy
                    )
                    
                    tile_path = coastline_dir / str(z) / str(x) / f"{y}.png"
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    tile_img.save(tile_path, 'PNG')
                    tiles_count += 1
            
            stats['total_tiles'] += tiles_count
            logger.info(f"Coastline zoom {z}: generated {tiles_count} tiles")
        
        return stats
    
    @staticmethod
    def _render_coastline_tile(coastline_data, minx, miny, maxx, maxy):
        """Отрисовывает береговую линию на тайле"""
        from PIL import Image, ImageDraw
        from app.coordinate_layer import CoordinateLayer
        
        tile_img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
        draw = ImageDraw.Draw(tile_img)
        
        line_color = (52, 152, 219, 200)  # Голубой полупрозрачный
        fill_color = (52, 152, 219, 80)   # Заливка океана
        land_color = (144, 238, 144, 100)  # Зеленый полупрозрачный для суши
        
        # Для каждого сегмента береговой линии
        for segment in coastline_data:
            points = []
            for lon, lat in segment:
                # Конвертируем координаты в EPSG:3031
                lon_rad = np.radians(lon)
                lat_rad = np.radians(lat)
                
                R = 6378137.0
                r = R * np.cos(lat_rad)
                
                x = r * np.sin(lon_rad)
                y = -r * np.cos(lon_rad)
                
                # Проверяем, находится ли точка в тайле
                if minx <= x <= maxx and miny <= y <= maxy:
                    px_x = (x - minx) / (maxx - minx) * 256
                    px_y = (maxy - y) / (maxy - miny) * 256
                    points.append((px_x, px_y))
            
            # Рисуем линию
            if len(points) >= 2:
                draw.line(points, fill=line_color, width=2)
        
        return tile_img