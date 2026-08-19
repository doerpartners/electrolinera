"""Utilidades geoespaciales sin dependencias externas."""
import math


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos (fórmula de Haversine)."""
    R = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def point_in_ring(lat, lon, ring):
    """Ray casting sobre un anillo de coords GeoJSON [lon, lat]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]   # lon, lat
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and \
           (lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def point_in_polygon(lat, lon, coordinates):
    """coordinates GeoJSON Polygon: [outer_ring, hole1, ...]."""
    if not coordinates:
        return False
    if not point_in_ring(lat, lon, coordinates[0]):
        return False
    for hole in coordinates[1:]:
        if point_in_ring(lat, lon, hole):
            return False
    return True


def bbox_of(coordinates):
    ring = coordinates[0]
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return (min(lats), min(lons), max(lats), max(lons))


class SpatialIndex:
    """Índice de rejilla simple para consultas por radio (rápido para ~miles de puntos)."""

    def __init__(self, points, cell_deg=0.05):
        self.cell = cell_deg
        self.grid = {}
        self.points = points
        for i, p in enumerate(points):
            key = self._key(p["lat"], p["lon"])
            self.grid.setdefault(key, []).append(i)

    def _key(self, lat, lon):
        return (int(math.floor(lat / self.cell)), int(math.floor(lon / self.cell)))

    def query_radius(self, lat, lon, radius_km):
        """Devuelve lista de (punto, distancia_km) dentro del radio."""
        # margen de celdas a revisar (1 grado ~ 111 km)
        span = int(math.ceil((radius_km / 111.0) / self.cell)) + 1
        ck = self._key(lat, lon)
        out = []
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                for i in self.grid.get((ck[0] + dy, ck[1] + dx), []):
                    p = self.points[i]
                    d = haversine_km(lat, lon, p["lat"], p["lon"])
                    if d <= radius_km:
                        out.append((p, d))
        out.sort(key=lambda t: t[1])
        return out
