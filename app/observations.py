"""
Observaciones de campo (levantamientos manuales).

Mecanismo validado para agregar información nueva que NO viene de scrapers:
un observador reporta un sitio con sus zonas (sótanos, corporativo/comercial),
cargadores por marca y estado (operativo/planeado), y vehículos vistos cargando.

Esquema de una observación (data/observations.json es una lista de estas):

{
  "id":         str (opcional; se autogenera desde name+fecha),
  "name":       str  (REQUERIDO)               ej. "Samara",
  "lat":        float(REQUERIDO, -90..90),
  "lon":        float(REQUERIDO, -180..180),
  "address":    str (opcional),
  "site_type":  "mall"|"corporate"|"mixed"|"other"  (def. "mixed"),
  "observed_at":"YYYY-MM-DD" (opcional),
  "observer":   str (opcional),
  "parking_spaces": int|null   (cajones totales del sitio, opcional),
  "ev_observed":    int|null   (EVs vistos en el estacionamiento, opcional),
  "source":     "field_survey" (fijo),
  "zones": [                                    (REQUERIDO, >=1)
    {
      "zone":    str (REQUERIDO)                ej. "Sótano 1 - Corporativo",
      "section": "corporativo"|"comercial"|null,
      "level":   str|null                       ej. "Sótano 1",
      "parking_spaces": int|null                (cajones de la zona, opcional),
      "chargers":[                              (>=0)
        {"count": int>=0,
         "brands": [str],                       ej. ["Siemens","BYD","ClipperCreek"],
         "status": "operational"|"planned"|"out_of_service",
         "connector": str|null,
         "kw": number|null}
      ],
      "vehicles_charging": [                     (opcional)
        {"make": str, "type": str|null}          ej. {"make":"BYD","type":"camioneta"}
      ]
    }
  ]
}
"""
import json, os, re, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(os.path.dirname(HERE), "data", "observations.json")

VALID_STATUS = {"operational", "planned", "out_of_service"}
VALID_SITE = {"mall", "corporate", "mixed", "other"}
FAST_KW = 50.0
FAST_CONNECTOR_HINTS = ("CCS", "CHADEMO", "NACS", "GB/T (FAST)")


def _slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "sitio"


def _opt_int(v):
    """int >=0 o None; lanza ValueError si es inválido."""
    if v in (None, ""):
        return None
    iv = int(v)
    if iv < 0:
        raise ValueError("negativo")
    return iv


def validate(obs):
    """Devuelve (ok, errores[list], normalizado|None)."""
    errs = []
    if not isinstance(obs, dict):
        return False, ["la observación debe ser un objeto"], None
    name = (obs.get("name") or "").strip()
    if not name:
        errs.append("falta 'name'")
    try:
        lat = float(obs["lat"]); lon = float(obs["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            errs.append("lat/lon fuera de rango")
    except (KeyError, TypeError, ValueError):
        errs.append("faltan 'lat'/'lon' numéricos")
        lat = lon = None
    zones_in = obs.get("zones")
    if not isinstance(zones_in, list) or not zones_in:
        errs.append("se requiere 'zones' con al menos 1 zona")
        zones_in = []

    site_type = obs.get("site_type", "mixed")
    if site_type not in VALID_SITE:
        errs.append(f"site_type inválido: {site_type}")

    try:
        site_parking = _opt_int(obs.get("parking_spaces"))
    except (TypeError, ValueError):
        errs.append("parking_spaces inválido"); site_parking = None
    try:
        ev_observed = _opt_int(obs.get("ev_observed"))
    except (TypeError, ValueError):
        errs.append("ev_observed inválido"); ev_observed = None

    norm_zones = []
    for i, z in enumerate(zones_in):
        if not isinstance(z, dict):
            errs.append(f"zona {i}: debe ser objeto"); continue
        zname = (z.get("zone") or "").strip()
        if not zname:
            errs.append(f"zona {i}: falta 'zone'")
        chargers = []
        for j, c in enumerate(z.get("chargers", []) or []):
            try:
                cnt = int(c.get("count", 0))
            except (TypeError, ValueError):
                errs.append(f"zona {i} cargador {j}: 'count' inválido"); continue
            if cnt < 0:
                errs.append(f"zona {i} cargador {j}: 'count' negativo"); continue
            status = c.get("status", "operational")
            if status not in VALID_STATUS:
                errs.append(f"zona {i} cargador {j}: status inválido '{status}'"); continue
            brands = [str(b).strip() for b in (c.get("brands") or []) if str(b).strip()]
            kw = c.get("kw")
            try:
                kw = float(kw) if kw not in (None, "") else None
            except (TypeError, ValueError):
                kw = None
            chargers.append({"count": cnt, "brands": brands, "status": status,
                             "connector": (c.get("connector") or None), "kw": kw})
        vehicles = []
        for v in z.get("vehicles_charging", []) or []:
            if isinstance(v, str):
                vehicles.append({"make": v.strip(), "type": None})
            elif isinstance(v, dict) and (v.get("make") or "").strip():
                vehicles.append({"make": v["make"].strip(), "type": (v.get("type") or None)})
        try:
            zparking = _opt_int(z.get("parking_spaces"))
        except (TypeError, ValueError):
            errs.append(f"zona {i}: parking_spaces inválido"); zparking = None
        norm_zones.append({"zone": zname, "section": z.get("section"),
                           "level": z.get("level"), "parking_spaces": zparking,
                           "chargers": chargers, "vehicles_charging": vehicles})

    if errs:
        return False, errs, None

    oid = (obs.get("id") or "").strip() or f"{_slug(name)}-{obs.get('observed_at') or 'sf'}"
    norm = {
        "id": oid, "name": name, "lat": lat, "lon": lon,
        "address": obs.get("address") or "", "site_type": site_type,
        "parking_spaces": site_parking, "ev_observed": ev_observed,
        "observed_at": obs.get("observed_at") or "", "observer": obs.get("observer") or "",
        "source": "field_survey", "zones": norm_zones,
    }
    return True, [], norm


def _is_fast(connector, kw):
    if kw and kw >= FAST_KW:
        return True
    if connector and any(h in connector.upper() for h in FAST_CONNECTOR_HINTS):
        return True
    return False


def summarize(obs):
    """Resumen agregado de una observación (para el análisis por radio)."""
    oper = planned = oos = 0
    brands, vehicles = set(), []
    zparking = 0
    for z in obs["zones"]:
        for c in z["chargers"]:
            if c["status"] == "operational": oper += c["count"]
            elif c["status"] == "planned": planned += c["count"]
            elif c["status"] == "out_of_service": oos += c["count"]
            brands.update(c["brands"])
        for v in z["vehicles_charging"]:
            vehicles.append(v["make"] + (f' ({v["type"]})' if v.get("type") else ""))
        zparking += z.get("parking_spaces") or 0
    parking = obs.get("parking_spaces") or (zparking or None)
    return {
        "name": obs["name"], "lat": obs["lat"], "lon": obs["lon"],
        "operational": oper, "planned": planned, "out_of_service": oos,
        "parking_spaces": parking, "ev_observed": obs.get("ev_observed"),
        "brands": sorted(b for b in brands if b), "vehicles": vehicles,
        "site_type": obs.get("site_type"),
    }


def expand_to_chargers(obs):
    """Expande una observación a puntos tipo 'charger' para el índice espacial.
    SOLO zonas con cargadores OPERATIVOS cuentan como oferta; sitios sin carga
    operativa (planeados / fuera de servicio / vacíos) NO inflan la oferta y se
    tratan como candidatos en otra parte."""
    pts = []
    retail = obs["site_type"] in ("mall", "mixed")
    for i, z in enumerate(obs["zones"]):
        oper = sum(c["count"] for c in z["chargers"] if c["status"] == "operational")
        planned = sum(c["count"] for c in z["chargers"] if c["status"] == "planned")
        oos = sum(c["count"] for c in z["chargers"] if c["status"] == "out_of_service")
        if oper <= 0:
            continue  # sin oferta operativa → no es un punto de carga
        brands = sorted({b for c in z["chargers"] for b in c["brands"]})
        connectors = sorted({c["connector"] for c in z["chargers"] if c["connector"]})
        kws = [c["kw"] for c in z["chargers"] if c["kw"]]
        kw = max(kws) if kws else None
        is_fast = any(_is_fast(c["connector"], c["kw"]) for c in z["chargers"])
        vehicles = [f'{v["make"]}' + (f' ({v["type"]})' if v.get("type") else "")
                    for v in z["vehicles_charging"]]
        # jitter determinista ~ pocos metros por zona
        dlat = (i % 3 - 1) * 0.00025
        dlon = (i // 3 - 1) * 0.00025
        pts.append({
            "id": f'{obs["id"]}::z{i}',
            "name": f'{obs["name"]} — {z["zone"]}',
            "lat": obs["lat"] + dlat, "lon": obs["lon"] + dlon,
            "network": ", ".join(brands) if brands else "Levantamiento de campo",
            "class": "public",
            "is_fast": is_fast,
            "tesla": False,
            "kilowatts": kw,
            "station_count": oper,
            "connectors": connectors,
            "amenities": ["Shopping"] if retail else [],
            "retail": retail,
            "score": None, "reviews": 0,
            "vehicles": vehicles,
            "url": "",
            # metadatos de campo
            "source": "field",
            "site": obs["name"],
            "section": z.get("section"),
            "level": z.get("level"),
            "brands": brands,
            "units_operational": oper,
            "units_planned": planned,
            "units_out_of_service": oos,
        })
    return pts


class ObservationStore:
    def __init__(self, path=STORE):
        self.path = path
        self.items = []
        self.load()

    def load(self):
        self.items = []
        if os.path.exists(self.path):
            try:
                self.items = json.load(open(self.path, encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                self.items = []
        return self.items

    def save(self):
        json.dump(self.items, open(self.path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

    def add(self, obs):
        ok, errs, norm = validate(obs)
        if not ok:
            return False, errs, None
        # upsert por id
        self.items = [x for x in self.items if x.get("id") != norm["id"]]
        self.items.append(norm)
        self.save()
        return True, [], norm

    def all_chargers(self):
        out = []
        for obs in self.items:
            ok, _, norm = validate(obs)
            if ok:
                out.extend(expand_to_chargers(norm))
        return out
