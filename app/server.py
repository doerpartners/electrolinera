"""
Servidor HTTP sin dependencias (stdlib) que expone la API JSON y sirve el
frontend. Pensado para embeberse después en una app móvil vía estos endpoints.

Endpoints:
  GET  /api/health
  GET  /api/meta
  GET  /api/insights
  GET  /api/analyze?lat=..&lon=..&radius=..     "¿aquí es buena ubicación?"
  POST /api/analyze   {lat, lon, radius}
  GET  /api/candidates?metro=Monterrey&top=15   sugerencias de instalación
  GET  /api/chargers?metro=Monterrey            cargadores para el mapa
  GET  /                                          frontend (web/index.html)
"""
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .scoring import get_engine
from . import config

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")

_engine_lock = threading.Lock()


def engine():
    with _engine_lock:
        return get_engine()


class Handler(BaseHTTPRequestHandler):
    server_version = "EVSiting/1.0"

    # ---------- helpers ----------
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, {"error": msg})

    def log_message(self, fmt, *args):
        pass  # silencio

    def do_OPTIONS(self):
        self._send(204, b"")

    # ---------- routing ----------
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        try:
            if path == "/api/health":
                return self._send(200, {"status": "ok"})
            if path == "/api/meta":
                return self._send(200, engine().meta)
            if path == "/api/insights":
                return self._send(200, engine().insights)
            if path == "/api/nse":
                return self._send(200, engine().nse.geojson())
            if path == "/api/nse/reload":
                engine().nse.load()
                return self._send(200, {"reloaded": engine().nse.loaded()})
            if path == "/api/armadora-nse":
                return self._send(200, engine().armadora_nse())
            if path == "/api/demand":
                return self._send(200, engine().demand)
            if path == "/api/business-config":
                return self._send(200, config.BUSINESS_CASE)
            if path == "/api/observations":
                e = engine()
                return self._send(200, {"count": len(e.obs.items),
                                        "field_points": e.field_count,
                                        "observations": e.obs.items})
            if path == "/api/config":
                return self._send(200, {"weights": config.WEIGHTS,
                                        "station_block": config.STATION_BLOCK,
                                        "default_radius_km": config.DEFAULT_RADIUS_KM,
                                        "metros": list(config.METROS.keys())})
            if path == "/api/analyze":
                return self._handle_analyze(
                    float(q["lat"][0]), float(q["lon"][0]),
                    float(q.get("radius", [config.DEFAULT_RADIUS_KM])[0]),
                    q.get("cp", [None])[0])
            if path == "/api/sensitivity":
                return self._send(200, engine().sensitivity(
                    float(q["lat"][0]), float(q["lon"][0]),
                    float(q.get("radius", [config.DEFAULT_RADIUS_KM])[0]),
                    q.get("cp", [None])[0]))
            if path == "/api/candidates":
                metro = q.get("metro", [None])[0]
                top = int(q.get("top", [15])[0])
                return self._send(200, {"candidates": engine().generate_candidates(metro, top)})
            if path == "/api/chargers":
                return self._handle_chargers(q)
            # estáticos
            return self._serve_static(path)
        except (KeyError, ValueError) as e:
            return self._err(400, f"parámetro inválido: {e}")
        except Exception as e:  # noqa
            return self._err(500, str(e))

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/api/analyze":
                return self._handle_analyze(float(data["lat"]), float(data["lon"]),
                                            float(data.get("radius", config.DEFAULT_RADIUS_KM)),
                                            data.get("cp"))
            if u.path == "/api/business":
                return self._handle_business(data)
            if u.path == "/api/weights":
                return self._handle_weights(data)
            if u.path == "/api/observations":
                ok, errs, norm = engine().add_observation(data)
                if not ok:
                    return self._send(422, {"ok": False, "errors": errs})
                return self._send(201, {"ok": True, "observation": norm,
                                        "field_points": engine().field_count})
            return self._err(404, "no encontrado")
        except (KeyError, ValueError, json.JSONDecodeError) as e:
            return self._err(400, f"cuerpo inválido: {e}")

    def _handle_business(self, data):
        """Ajusta supuestos del business case en vivo (CapEx base, precio, sesiones…)."""
        bc = config.BUSINESS_CASE
        if "reference_total_capex" in data:
            bc["reference_total_capex"] = max(0, float(data["reference_total_capex"]))
        rev = data.get("revenue", {})
        for k in ("price_per_kwh_user", "base_sessions_per_station_day", "kwh_per_session"):
            if k in rev:
                bc["revenue"][k] = float(rev[k])
        svc = data.get("service", {})
        for k in ("cost_per_kwh", "cost_per_session"):
            if k in svc:
                bc.setdefault("service", {})[k] = float(svc[k])
        return self._send(200, {"business_case": bc})

    def _handle_weights(self, data):
        """Actualiza pesos del scoring en vivo. Se normalizan a suma 1.0."""
        w = data.get("weights", data)
        valid = set(config.WEIGHTS.keys())
        clean = {k: float(v) for k, v in w.items() if k in valid and float(v) >= 0}
        if not clean:
            return self._err(400, "sin pesos válidos")
        total = sum(clean.values()) or 1.0
        for k in config.WEIGHTS:
            if k in clean:
                config.WEIGHTS[k] = round(clean[k] / total, 4)
        # re-normaliza todo el vector para que sume 1.0
        s = sum(config.WEIGHTS.values()) or 1.0
        for k in config.WEIGHTS:
            config.WEIGHTS[k] = round(config.WEIGHTS[k] / s, 4)
        return self._send(200, {"weights": config.WEIGHTS})

    # ---------- handlers ----------
    def _handle_analyze(self, lat, lon, radius, cp=None):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return self._err(400, "lat/lon fuera de rango")
        radius = max(0.5, min(radius, 25))
        return self._send(200, engine().analyze_point(lat, lon, radius, cp))

    def _handle_chargers(self, q):
        e = engine()
        metro = q.get("metro", [None])[0]
        pts = e.chargers  # solo PlugShare; las observaciones van en /api/observations
        if metro and metro in config.METROS:
            m = config.METROS[metro]
            pts = [p for p in pts if m["lat"][0] <= p["lat"] <= m["lat"][1]
                   and m["lon"][0] <= p["lon"] <= m["lon"][1]]
        light = [{"lat": p["lat"], "lon": p["lon"], "class": p["class"],
                  "tesla": p["tesla"], "fast": p["is_fast"], "retail": p["retail"],
                  "name": p["name"] or p.get("address", "")[:40],
                  "connectors": p["connectors"]}
                 for p in pts]
        return self._send(200, {"count": len(light), "chargers": light})

    def _serve_static(self, path):
        if path == "/" or path == "":
            path = "/index.html"
        rel = path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB, rel))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._err(404, "no encontrado")
        ext = os.path.splitext(full)[1]
        ctype = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8"}.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)


def run(host="127.0.0.1", port=8000):
    engine()  # precarga
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"\n  EV Siting demo corriendo en  http://{host}:{port}\n")
    print("  API:  /api/analyze?lat=25.625&lon=-100.308")
    print("        /api/candidates?metro=Monterrey")
    print("  Ctrl+C para detener.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    import sys
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run(port=p)
