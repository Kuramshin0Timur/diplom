import logging
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from app.config import Config
import math

logger = logging.getLogger(__name__)

class CoordinateLayer:
    """Генератор сетки координат для Антарктиды"""
    
    @staticmethod
    def meters_to_lonlat(x: float, y: float) -> tuple:
        """
        Конвертация EPSG:3031 (метры) в EPSG:4326 (lon, lat)
        Использует обратную проекцию полярной стереографической проекции
        """
        # Параметры проекции EPSG:3031
        lat0 = -90  # Центральная широта (Южный полюс)
        lon0 = 0    # Центральная долгота
        k0 = 1.0    # Масштабный коэффициент
        R = 6378137.0  # Радиус Земли в метрах (WGS84)
        e = 0.081819191  # Эксцентриситет эллипсоида WGS84
        
        # Конвертируем обратно: из метров в широту/долготу
        rho = np.sqrt(x**2 + y**2)
        
        if rho < 1e-6:
            # В центре (Южный полюс)
            lat = -90.0
            lon = lon0
        else:
            # Решаем для широты
            t = rho * k0 / (R * (1 + e)**(1 + e) * (1 - e)**(1 - e))
            # Приближенное решение для широты
            mu = math.pi / 2 - 2 * math.atan(t)
            lat = math.degrees(mu)
            
            # Долгота
            lon = lon0 + math.degrees(math.atan2(-x, y))
        
        # Ограничиваем широту антарктическим диапазоном
        lat = max(-90, min(-60, lat))
        
        return lon, lat
    
    @staticmethod
    def generate_grid_tiles(map_id: str = "coordinate_grid"):
        """
        Генерирует тайлы с сеткой координат и подписями
        """
        from app.tiler import TileGenerator
        
        tile_gen = TileGenerator()
        grid_dir = Config.TILES_DIR / map_id
        grid_dir.mkdir(parents=True, exist_ok=True)
        
        zoom_levels = range(Config.MIN_ZOOM, 7)
        
        # Параметры сетки
        lat_lines = [-60, -65, -70, -75, -80, -85]  # Параллели
        lon_lines = [-180, -150, -120, -90, -60, -30, 0, 30, 60, 90, 120, 150]  # Меридианы
        
        stats = {'total_tiles': 0}
        
        for z in zoom_levels:
            tiles_per_side = 2 ** z
            tiles_count = 0
            
            for x in range(tiles_per_side):
                for y in range(tiles_per_side):
                    # Получаем границы тайла в EPSG:3031
                    minx, miny, maxx, maxy = tile_gen.get_tile_bounds(z, x, y)
                    
                    # Создаем изображение тайла
                    tile_img = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
                    draw = ImageDraw.Draw(tile_img)
                    
                    # Рисуем сетку
                    grid_drawn = CoordinateLayer.draw_grid_on_tile(
                        draw, minx, miny, maxx, maxy,
                        lat_lines, lon_lines, z
                    )
                    
                    # Рисуем подписи координат (только на высоких зумах)
                    if z >= 4:
                        CoordinateLayer.draw_labels_on_tile(
                            draw, minx, miny, maxx, maxy,
                            lat_lines, lon_lines, z, tile_img.size
                        )
                    
                    if grid_drawn:
                        tile_path = grid_dir / str(z) / str(x) / f"{y}.png"
                        tile_path.parent.mkdir(parents=True, exist_ok=True)
                        tile_img.save(tile_path, 'PNG')
                        tiles_count += 1
            
            stats['total_tiles'] += tiles_count
            logger.info(f"Grid zoom {z}: generated {tiles_count} tiles")
        
        return stats
    
    @staticmethod
    def draw_grid_on_tile(draw, minx, miny, maxx, maxy, lat_lines, lon_lines, zoom):
        """Рисует линии сетки на тайле"""
        grid_drawn = False
        line_color = (255, 255, 255, 180)  # Белый полупрозрачный
        
        # Для каждой параллели
        for lat in lat_lines:
            # Находим точки пересечения с границами тайла
            points = CoordinateLayer._get_latitude_line_in_tile(lat, minx, miny, maxx, maxy)
            if len(points) >= 2:
                # Конвертируем метры в пиксели
                px_points = []
                for px, py in points:
                    x_px = (px - minx) / (maxx - minx) * 256
                    y_px = (maxy - py) / (maxy - miny) * 256
                    px_points.append((x_px, y_px))
                
                if len(px_points) >= 2:
                    draw.line(px_points, fill=line_color, width=1)
                    grid_drawn = True
        
        # Для каждого меридиана
        for lon in lon_lines:
            points = CoordinateLayer._get_longitude_line_in_tile(lon, minx, miny, maxx, maxy)
            if len(points) >= 2:
                px_points = []
                for px, py in points:
                    x_px = (px - minx) / (maxx - minx) * 256
                    y_px = (maxy - py) / (maxy - miny) * 256
                    px_points.append((x_px, y_px))
                
                if len(px_points) >= 2:
                    draw.line(px_points, fill=line_color, width=1)
                    grid_drawn = True
        
        return grid_drawn
    
    @staticmethod
    def _get_latitude_line_in_tile(lat, minx, miny, maxx, maxy):
        """Находит пересечение параллели с границами тайла"""
        points = []
        
        # Конвертируем параллель в EPSG:3031 координаты
        # Используем упрощенную формулу для кругов широты
        R = 6378137.0
        lat_rad = math.radians(lat)
        
        # Радиус параллели в метрах
        r = R * math.cos(lat_rad)
        
        # Параллель - это круг, аппроксимируем прямыми на малых участках
        for lon in range(-180, 181, 10):
            lon_rad = math.radians(lon)
            x = r * math.sin(lon_rad)
            y = -r * math.cos(lon_rad)
            
            if minx <= x <= maxx and miny <= y <= maxy:
                points.append((x, y))
        
        return points
    
    @staticmethod
    def _get_longitude_line_in_tile(lon, minx, miny, maxx, maxy):
        """Находит пересечение меридиана с границами тайла"""
        points = []
        lon_rad = math.radians(lon)
        
        # Меридиан - это прямая через полюс
        # y = tan(lon) * x для x > 0
        
        # Проверяем пересечения с границами
        for lat in range(-90, -55, 5):
            lat_rad = math.radians(lat)
            R = 6378137.0
            r = R * math.cos(lat_rad)
            
            x = r * math.sin(lon_rad)
            y = -r * math.cos(lon_rad)
            
            if minx <= x <= maxx and miny <= y <= maxy:
                points.append((x, y))
        
        # Добавляем полюс
        if minx <= 0 <= maxx and miny <= 0 <= maxy:
            points.append((0, 0))
        
        return points
    
    @staticmethod
    def draw_labels_on_tile(draw, minx, miny, maxx, maxy, lat_lines, lon_lines, zoom, tile_size):
        """Рисует подписи координат"""
        try:
            # Пытаемся загрузить шрифт, используем стандартный если нет
            font = ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        
        text_color = (255, 255, 255, 255)
        
        # Подписи широт
        for lat in lat_lines:
            # Находим подходящую позицию для подписи
            x_pos = (minx + maxx) / 2
            y_pos = CoordinateLayer._lat_to_meters(lat)
            
            if miny <= y_pos <= maxy and minx <= x_pos <= maxx:
                px_x = (x_pos - minx) / (maxx - minx) * tile_size[0]
                px_y = (maxy - y_pos) / (maxy - miny) * tile_size[1]
                
                label = f"{abs(lat)}°{'S' if lat < 0 else 'N'}"
                draw.text((px_x + 5, px_y - 5), label, fill=text_color, font=font)
        
        # Подписи долгот
        for lon in lon_lines:
            x_pos = CoordinateLayer._lon_to_meters(lon)
            y_pos = (miny + maxy) / 2
            
            if minx <= x_pos <= maxx and miny <= y_pos <= maxy:
                px_x = (x_pos - minx) / (maxx - minx) * tile_size[0]
                px_y = (maxy - y_pos) / (maxy - miny) * tile_size[1]
                
                label = f"{abs(lon)}°{'E' if lon > 0 else 'W' if lon < 0 else ''}"
                draw.text((px_x + 5, px_y - 5), label, fill=text_color, font=font)
    
    @staticmethod
    def _lat_to_meters(lat):
        """Конвертирует широту в EPSG:3031 метры (приблизительно)"""
        R = 6378137.0
        lat_rad = math.radians(lat)
        return -R * math.cos(lat_rad)
    
    @staticmethod
    def _lon_to_meters(lon):
        """Конвертирует долготу в EPSG:3031 метры (приблизительно)"""
        R = 6378137.0
        lon_rad = math.radians(lon)
        return R * math.sin(lon_rad) * math.cos(math.radians(-85))