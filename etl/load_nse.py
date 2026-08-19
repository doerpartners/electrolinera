#!/usr/bin/env python3
"""
Cargador de polígonos NSE oficiales (INEGI AGEB / AMAI) → esquema del sistema.

Uso:
  python3 etl/load_nse.py <archivo.geojson> [--append] [--out data/nse_polygons.geojson]

Ingiere un GeoJSON (el formato de exportación práctico de INEGI/DENUE/AGEB o de
mapshaper a partir de un shapefile) y normaliza cada feature a:
    properties = { name, metro, nse, ses_index }
mapeando nombres de campo comunes. Geometrías Polygon y MultiPolygon.

Shapefile (.shp): conviértelo primero a GeoJSON, p. ej.
    ogr2ogr -f GeoJSON salida.geojson entrada.shp
o con mapshaper.org (arrastra el .shp/.dbf y exporta GeoJSON).
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OUT = os.path.join(ROOT, "data", "nse_polygons.geojson")

# Mapa de etiqueta NSE (AMAI) -> índice 0..1
NSE_INDEX = {"A/B": 0.90, "A": 0.95, "B": 0.85, "C+": 0.70, "C": 0.50,
             "C-": 0.42, "D+": 0.35, "D": 0.25, "D/E": 0.20, "E": 0.12}
# Estrato INEGI (1=bajo .. 4=alto) -> índice
ESTRATO_INDEX = {"1": 0.25, "2": 0.45, "3": 0.65, "4": 0.88}

# Metros para inferir por centroide si falta el campo
METROS = {
    "Monterrey":  ((25.40, 25.95), (-100.60, -100.00)),
    "Guadalajara":((20.40, 20.90), (-103.60, -103.20)),
    "CDMX":       ((19.20, 19.70), (-99.40, -98.90)),
}

NAME_KEYS = ["name", "NOMBRE", "NOMGEO", "NOM_LOC", "NOM_COL", "colonia", "COLONIA", "NOM_MUN", "settlement"]
NSE_KEYS  = ["nse", "NSE", "AMAI", "amai", "estrato_amai"]
IDX_KEYS  = ["ses_index", "indice", "index"]
STRATO_KEYS = ["ESTRATO", "estrato", "GM_2020", "GMU", "estratos"]
METRO_KEYS = ["metro", "METRO", "NOM_MUN", "MUNICIPIO", "ciudad", "CIUDAD"]


def first(props, keys):
    for k in keys:
        if k in props and props[k] not in (None, ""):
            return props[k]
    return None


def centroid(geom):
    def ring_pts(coords):
        return coords[0]
    pts = []
    t = geom.get("type")
    if t == "Polygon":
        pts = ring_pts(geom["coordinates"])
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            pts += ring_pts(poly)
    if not pts:
        return None
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lon


def infer_metro(geom):
    c = centroid(geom)
    if not c:
        return None
    lat, lon = c
    for name, (la, lo) in METROS.items():
        if la[0] <= lat <= la[1] and lo[0] <= lon <= lo[1]:
            return name
    return None


def normalize_nse(props, geom):
    nse = first(props, NSE_KEYS)
    idx = first(props, IDX_KEYS)
    strato = first(props, STRATO_KEYS)

    if idx is not None:
        try:
            idx = float(idx)
            if idx > 1:  # viene en 0..100
                idx = idx / 100.0
        except ValueError:
            idx = None

    if nse:
        nse = str(nse).upper().replace(" ", "")
        # normaliza variantes
        nse = {"AB": "A/B", "DE": "D/E"}.get(nse, nse)
        if idx is None:
            idx = NSE_INDEX.get(nse)

    if idx is None and strato is not None:
        idx = ESTRATO_INDEX.get(str(strato).strip())
        if not nse:
            nse = {"1": "D/E", "2": "C", "3": "C+", "4": "A/B"}.get(str(strato).strip())

    if idx is None:
        idx = 0.5  # neutral si no hay dato
    if not nse:
        # etiqueta aproximada desde índice
        nse = ("A/B" if idx >= 0.8 else "C+" if idx >= 0.6 else "C" if idx >= 0.45
               else "D+" if idx >= 0.3 else "D/E")

    name = first(props, NAME_KEYS) or "Zona NSE"
    metro = first(props, METRO_KEYS) or infer_metro(geom) or ""
    return {"name": str(name), "metro": str(metro), "nse": nse,
            "ses_index": round(float(idx), 3)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="GeoJSON de entrada (INEGI/AMAI)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--append", action="store_true", help="Agregar a los polígonos existentes")
    args = ap.parse_args()

    src = json.load(open(args.input, encoding="utf-8"))
    feats_in = src.get("features", []) if src.get("type") == "FeatureCollection" else [src]

    out_feats = []
    if args.append and os.path.exists(args.out):
        out_feats = json.load(open(args.out, encoding="utf-8")).get("features", [])

    added = 0
    for f in feats_in:
        geom = f.get("geometry", {})
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        props = normalize_nse(f.get("properties", {}), geom)
        out_feats.append({"type": "Feature", "properties": props, "geometry": geom})
        added += 1

    fc = {"type": "FeatureCollection",
          "meta": {"descripcion": "Zonas NSE normalizadas.",
                   "clasificacion": "AMAI/INEGI -> ses_index 0-1",
                   "generado_por": "etl/load_nse.py"},
          "features": out_feats}
    json.dump(fc, open(args.out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"OK: {added} features normalizadas → {args.out}  (total {len(out_feats)})")


if __name__ == "__main__":
    main()
