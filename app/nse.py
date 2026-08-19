"""
Capa de Nivel Socioeconómico (NSE) por polígonos.

Carga data/nse_polygons.geojson y resuelve el NSE en un punto (point-in-polygon).
Soporta geometrías Polygon y MultiPolygon (formato típico de AGEB/INEGI).
Estructura compatible con datos oficiales: basta reemplazar el GeoJSON manteniendo
properties {name, metro, nse, ses_index}.
"""
import json, os
from .geo import point_in_polygon, bbox_of

HERE = os.path.dirname(os.path.abspath(__file__))
GEOJSON = os.path.join(os.path.dirname(HERE), "data", "nse_polygons.geojson")


def _polys_of(geom):
    """Normaliza a lista de polígonos (cada uno = lista de anillos)."""
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return list(geom["coordinates"])
    return []


class NSELayer:
    def __init__(self, path=GEOJSON):
        self.path = path
        self.features = []
        self.raw = {"type": "FeatureCollection", "features": []}
        self.load()

    def load(self):
        self.features = []
        if not os.path.exists(self.path):
            return
        self.raw = json.load(open(self.path, encoding="utf-8"))
        for f in self.raw.get("features", []):
            polys = _polys_of(f.get("geometry", {}))
            if not polys:
                continue
            # bbox global de todos los polígonos de la feature
            bxs = [bbox_of(p) for p in polys]
            bbox = (min(b[0] for b in bxs), min(b[1] for b in bxs),
                    max(b[2] for b in bxs), max(b[3] for b in bxs))
            self.features.append({"props": f.get("properties", {}),
                                  "polys": polys, "bbox": bbox})

    def loaded(self):
        return len(self.features)

    def nse_at(self, lat, lon):
        """Properties del polígono que contiene el punto, o None."""
        for f in self.features:
            b = f["bbox"]
            if not (b[0] <= lat <= b[2] and b[1] <= lon <= b[3]):
                continue
            for poly in f["polys"]:
                if point_in_polygon(lat, lon, poly):
                    return f["props"]
        return None

    def geojson(self):
        return self.raw
