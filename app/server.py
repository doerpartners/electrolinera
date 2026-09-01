"""
Servidor HTTP sin dependencias (stdlib) que expone la API JSON y sirve el
frontend. Pensado para embeberse después en una app móvil vía estos endpoints.

Endpoints:
  GET  /api/health
  GET  /api/meta
  GET  /api/insights
  GET  /api/analyze?lat=..&lon=..&case=full|partial   "¿aquí es buena ubicación?" (radio auto: urbano/rural)
  POST /api/analyze   {lat, lon, case}
  GET  /api/candidates?metro=Monterrey&top=15   sugerencias de instalación (excluye sitios con
       <2 cargadores rápidos cercanos — riesgo de tráfico muy alto sin esa señal)
  GET  /api/candidates/portfolio?metro=Monterrey&pool=30   igual, pero priorizado a nivel
       portafolio: descuenta canibalización de demanda entre candidatos cercanos y marca
       `portfolio_viable: false` donde deja de ser buen negocio abrir más sitios
  GET  /api/chargers?metro=Monterrey            cargadores para el mapa
  GET  /api/export/business-case?lat=..&lon=..&case=full|partial  descarga el business case (.xlsx)

  case=full (default): 1 set de 6 cargadores, OpEx completo (contrato CFE + renta al predio).
  case=partial: 4 cargadores, sin contrato de demanda CFE ni renta — ver
  config.BUSINESS_CASE_PARTIAL_OVERRIDES.
  GET  /                                          frontend (web/index.html)
"""
import json, os, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .scoring import get_engine
from . import config, export_xlsx

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")

_engine_lock = threading.Lock()


def engine():
    with _engine_lock:
        return get_engine()


class Handler(BaseHTTPRequestHandler):
    server_version = "CSEnergy/1.0"

    # ---------- helpers ----------
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra_headers=None):
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
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, {"error": msg})

    def _case(self, raw):
        return raw if raw in ("full", "partial") else "full"

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
                case = self._case(q.get("case", [None])[0])
                bc = {**config.BUSINESS_CASE,
                      **(config.BUSINESS_CASE_PARTIAL_OVERRIDES if case == "partial" else {})}
                return self._send(200, {**bc, "case": case,
                                        "ev_fleet_growth_pct_yoy": config.VEHICLE_MODEL["ev_fleet_growth_pct_yoy"],
                                        "period_hours": config.ELECTRICITY["period_hours"]})
            if path == "/api/observations":
                e = engine()
                return self._send(200, {"count": len(e.obs.items),
                                        "field_points": e.field_count,
                                        "observations": e.obs.items})
            if path == "/api/config":
                return self._send(200, {"weights": config.WEIGHTS,
                                        "charger_set_size": 6,
                                        "mobility_radius_km": config.MOBILITY_RADIUS_KM,
                                        "metros": list(config.METROS.keys())})
            if path == "/api/analyze":
                radius = q.get("radius", [None])[0]
                return self._handle_analyze(
                    float(q["lat"][0]), float(q["lon"][0]),
                    float(radius) if radius is not None else None,
                    q.get("cp", [None])[0], self._case(q.get("case", [None])[0]))
            if path == "/api/sensitivity":
                radius = q.get("radius", [None])[0]
                return self._send(200, engine().sensitivity(
                    float(q["lat"][0]), float(q["lon"][0]),
                    float(radius) if radius is not None else None,
                    q.get("cp", [None])[0], case=self._case(q.get("case", [None])[0])))
            if path == "/api/candidates":
                metro = q.get("metro", [None])[0]
                top = int(q.get("top", [15])[0])
                return self._send(200, {"candidates": engine().generate_candidates(metro, top)})
            if path == "/api/candidates/portfolio":
                metro = q.get("metro", [None])[0]
                pool = int(q.get("pool", [30])[0])
                return self._send(200, {"candidates": engine().prioritize_portfolio(metro, pool)})
            if path == "/api/chargers":
                return self._handle_chargers(q)
            if path == "/api/export/business-case":
                radius = q.get("radius", [None])[0]
                return self._handle_export_business_case(
                    float(q["lat"][0]), float(q["lon"][0]),
                    float(radius) if radius is not None else None,
                    q.get("cp", [None])[0], self._case(q.get("case", [None])[0]))
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
                radius = data.get("radius")
                return self._handle_analyze(float(data["lat"]), float(data["lon"]),
                                            float(radius) if radius is not None else None,
                                            data.get("cp"), self._case(data.get("case")))
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
        """Ajusta supuestos del business case en vivo (CapEx por sitio, precio, tarifas…)."""
        bc = config.BUSINESS_CASE
        if "site_capex_mxn" in data and data["site_capex_mxn"] is not None:
            bc["site_capex_mxn"] = max(0, float(data["site_capex_mxn"]))
        for k in ("price_per_kwh_user", "maintenance_pct", "platform_pct",
                  "bank_commission_pct", "landlord_profit_share", "inflation_pct",
                  "discount_rate_pct", "residual_value_pct", "utilization_year1_pct",
                  "utilization_ceiling_pct", "avg_kwh_per_charge_session"):
            if k in data and data[k] is not None:
                bc[k] = float(data[k])
        if "ev_fleet_growth_pct_yoy" in data and data["ev_fleet_growth_pct_yoy"] is not None:
            config.VEHICLE_MODEL["ev_fleet_growth_pct_yoy"] = float(data["ev_fleet_growth_pct_yoy"])
        ph = data.get("period_hours")
        if ph:
            for k in ("punta", "intermedia", "base"):
                if k in ph and ph[k] is not None:
                    config.ELECTRICITY["period_hours"][k] = float(ph[k])
        return self._send(200, {"business_case": bc, "vehicle_model": config.VEHICLE_MODEL,
                                "electricity": config.ELECTRICITY})

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
    def _handle_analyze(self, lat, lon, radius, cp=None, case="full"):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return self._err(400, "lat/lon fuera de rango")
        if radius is not None:
            radius = max(0.5, min(radius, 25))  # override explícito (ej. pruebas); si no se manda, se autocalcula
        return self._send(200, engine().analyze_point(lat, lon, radius, cp, case))

    def _handle_export_business_case(self, lat, lon, radius, cp=None, case="full"):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return self._err(400, "lat/lon fuera de rango")
        if radius is not None:
            radius = max(0.5, min(radius, 25))
        a = engine().analyze_point(lat, lon, radius, cp, case)
        xlsx_bytes = export_xlsx.build_business_case_xlsx(a)
        fname = f"business_case_{lat:.4f}_{lon:.4f}.xlsx".replace("-", "m")
        return self._send(200, xlsx_bytes,
                          ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          extra_headers={"Content-Disposition": f'attachment; filename="{fname}"'})

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
    print(f"\n  CS Energy demo corriendo en  http://{host}:{port}\n")
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
