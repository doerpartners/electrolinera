"""
Motor de recomendación de ubicaciones para cargadores EV.

Dos capacidades:
  1) analyze_point(lat, lon, radius) -> "¿aquí es buena ubicación?" (API móvil)
  2) generate_candidates(metro) -> sugerencias de dónde instalar sitios de carga.

El modelo es transparente y tunable vía app/config.py.
"""
import json, math, os
from collections import Counter

from . import config
from .geo import haversine_km, SpatialIndex
from .nse import NSELayer
from .observations import ObservationStore, summarize as obs_summarize
from . import business

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.join(os.path.dirname(HERE), "data", "processed")


def _load(name):
    return json.load(open(os.path.join(PROC, name), encoding="utf-8"))


class Engine:
    def __init__(self):
        self.chargers = _load("chargers.json")
        self.demand = _load("demand_state.json")
        self.insights = _load("insights.json")
        self.meta = _load("meta.json")
        self.nse = NSELayer()
        self.obs = ObservationStore()
        # normalizador de adopción estatal
        shares = [d["share_national"] for d in self.demand.values()] or [1]
        self.max_state_share = max(shares)
        self._build_index()

    def _build_index(self):
        """Combina cargadores base (PlugShare) + observaciones de campo."""
        field = self.obs.all_chargers()
        self.all_points = self.chargers + field
        self.field_count = len(field)
        self.index = SpatialIndex(self.all_points)

    def add_observation(self, obs):
        ok, errs, norm = self.obs.add(obs)
        if ok:
            self._build_index()
        return ok, errs, norm

    def sensitivity(self, lat, lon, radius=None, cp=None, prices=None, services=None):
        """Matriz de punto de equilibrio (meses) variando precio de carga (filas)
        y costo de servicio agregado (columnas, % de facturación). Para decidir el
        pricing óptimo por sitio."""
        a = self.analyze_point(lat, lon, radius, cp)
        sites = a["recommended_sites"]
        ctx0 = {"metro": a["query"]["metro"], "ses_index": a["ses_proxy"],
                "util": a["score"] / 100.0, "cp": cp}
        prices = prices or [0.30, 0.36, 0.42, 0.46, 0.52, 0.58, 0.65]
        services = services or [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
        grid = []
        for p in prices:
            row = []
            for s in services:
                b = business.compute(sites, {**ctx0, "price_per_kwh": p,
                                             "service_opex_pct": s})
                row.append(b["break_even_months"])
            grid.append(row)
        bc = config.BUSINESS_CASE
        current_service_pct = bc["payment_gateway_pct"] + bc["maintenance_pct"] + bc["platform_pct"]
        return {
            "sites": sites,
            "prices": prices, "services": services, "grid": grid,
            "current": {"price": bc["price_per_kwh_user"], "service": current_service_pct},
            "site": {"score": a["score"], "verdict": a["verdict"],
                     "metro": a["query"]["metro"],
                     "electricity": a["business_case"]["local_factors"]["electricity_peak_usd_kwh"]},
        }

    def obs_in_radius(self, lat, lon, r):
        """Observaciones de campo (por centro de sitio) dentro del radio."""
        out = []
        for o in self.obs.items:
            d = haversine_km(lat, lon, o["lat"], o["lon"])
            if d <= r:
                out.append((obs_summarize(o), d))
        out.sort(key=lambda t: t[1])
        return out

    # ---------- helpers de contexto ----------
    def metro_of(self, lat, lon):
        for name, m in config.METROS.items():
            if m["lat"][0] <= lat <= m["lat"][1] and m["lon"][0] <= lon <= m["lon"][1]:
                return name, m
        return None, None

    def state_adoption_mult(self, state_key):
        d = self.demand.get(state_key)
        if not d:
            return 1.0
        norm = d["share_national"] / self.max_state_share if self.max_state_share else 0
        return 1.0 + norm * (config.VEHICLE_MODEL["state_adoption_boost_max"] - 1.0)

    def ses_context(self, lat, lon, nearby):
        """NSE del punto. Prioriza el polígono NSE real (AGEB/AMAI); si el punto
        no está cubierto, cae al proxy por señales locales. Devuelve dict con
        index (0..1), source y zona."""
        zone = self.nse.nse_at(lat, lon)
        if zone:
            return {"index": float(zone.get("ses_index", 0.5)),
                    "source": "polygon",
                    "zone": zone.get("name"),
                    "nse": zone.get("nse")}
        return {"index": self._ses_signal_proxy(nearby),
                "source": "signal_proxy", "zone": None, "nse": None}

    def _ses_signal_proxy(self, nearby):
        """Fallback: proxy de NSE (0..1) por señales locales (Tesla/rápido/retail)."""
        if not nearby:
            return 0.3
        tesla = sum(1 for p, _ in nearby if p["tesla"])
        fast = sum(1 for p, _ in nearby if p["is_fast"])
        retail = sum(1 for p, _ in nearby if p["retail"])
        n = len(nearby)
        signal = (0.5 * tesla + 0.3 * fast + 0.2 * retail) / max(n, 1)
        return max(0.2, min(1.0, 0.25 + 1.6 * signal))

    # ---------- estimadores de parque vehicular (modelados) ----------
    def estimate_vehicles(self, lat, lon, radius_km, state_key, ses):
        vm = config.VEHICLE_MODEL
        metro, _ = self.metro_of(lat, lon)
        density = vm["cars_per_km2_urban"] if metro else 150
        area = math.pi * radius_km ** 2
        cars = int(density * area)
        state_mult = self.state_adoption_mult(state_key)
        ses_mult = 1.0 + ses * (vm["ses_boost_max"] - 1.0)
        pen = vm["base_ev_penetration"] * state_mult * ses_mult
        pen = min(pen, 0.25)
        evs = int(cars * pen)
        # carga en casa: interpolar propensión por NSE
        hp = self.insights["home_charging_propensity"]
        tier = 3 if ses > 0.66 else (2 if ses > 0.4 else 1)
        home_prop = hp[str(tier)]
        home_chargers = int(evs * home_prop)
        return {
            "cars_est": cars,
            "ev_est": evs,
            "ev_penetration_pct": round(pen * 100, 2),
            "home_chargers_est": home_chargers,
            "home_charging_propensity": home_prop,
            "urban": bool(metro),
            "assumptions": {
                "cars_per_km2": density,
                "state_adoption_mult": round(state_mult, 2),
                "ses_mult": round(ses_mult, 2),
            },
        }

    # ---------- análisis principal ----------
    def analyze_point(self, lat, lon, radius_km=None, cp=None):
        radius_km = radius_km or config.DEFAULT_RADIUS_KM
        nearby = self.index.query_radius(lat, lon, radius_km)
        metro, m = self.metro_of(lat, lon)
        state_key = m["state"] if m else None

        public = [(p, d) for p, d in nearby if p["class"] == "public"]
        residential = [(p, d) for p, d in nearby if p["class"] == "residential"]
        obs_near = self.obs_in_radius(lat, lon, radius_km)
        fast = [(p, d) for p, d in nearby if p["is_fast"]]
        tesla = [(p, d) for p, d in nearby if p["tesla"]]
        retail = [(p, d) for p, d in nearby if p["retail"]]

        # desgloses
        connectors = Counter()
        networks = Counter()
        vehicles = Counter()
        for p, _ in nearby:
            for c in p["connectors"]:
                connectors[c] += 1
            if p["network"]:
                networks[p["network"]] += 1
            for v in p["vehicles"]:
                vehicles[v] += 1

        # resumen de observaciones de campo en el radio (datos duros / ground truth)
        parking_tot = sum(s["parking_spaces"] or 0 for s, _ in obs_near)
        ev_obs_tot = sum(s["ev_observed"] or 0 for s, _ in obs_near)
        field_summary = {
            "sites": [s["name"] for s, _ in obs_near],
            "count": len(obs_near),
            "units_operational": sum(s["operational"] for s, _ in obs_near),
            "units_planned": sum(s["planned"] for s, _ in obs_near),
            "units_out_of_service": sum(s["out_of_service"] for s, _ in obs_near),
            "parking_spaces": parking_tot or None,
            "ev_observed": ev_obs_tot or None,
            "brands": sorted({b for s, _ in obs_near for b in s["brands"]}),
            "detail": [
                {"site": s["name"], "operational": s["operational"], "planned": s["planned"],
                 "out_of_service": s["out_of_service"], "parking_spaces": s["parking_spaces"],
                 "ev_observed": s["ev_observed"], "brands": s["brands"],
                 "vehicles": s["vehicles"], "dist_km": round(d, 2)}
                for s, d in obs_near
            ],
        }

        ses_ctx = self.ses_context(lat, lon, nearby)
        ses = ses_ctx["index"]
        veh = self.estimate_vehicles(lat, lon, radius_km, state_key, ses)

        # estacionamiento observado como factor de demanda:
        # cajones × penetración EV × rotación = potencial de EVs que usarían el sitio
        parking = field_summary["parking_spaces"] or 0
        pen = veh["ev_penetration_pct"] / 100.0
        parking_potential = int(parking * pen * config.PARKING_DEMAND_TURNOVER)
        veh["parking_ev_potential"] = parking_potential

        # --- sub-scores 0..100 ---
        # demanda (EVs estimados + potencial por estacionamiento, escala log)
        REF_EVS = config.SATURATION_EVS
        demand_basis = veh["ev_est"] + parking_potential
        demand_score = min(100, 100 * math.log1p(demand_basis) / math.log1p(REF_EVS))

        # brecha oferta/demanda pública
        npub = len(public)
        healthy = config.HEALTHY_EV_PER_PUBLIC_CHARGER
        if npub == 0:
            gap_score = 90 if veh["ev_est"] > 50 else 45
            ev_per_charger = None
        else:
            ev_per_charger = veh["ev_est"] / npub
            gap_score = max(0, min(100, 50 * ev_per_charger / healthy))

        ses_score = ses * 100

        # ancla comercial: mall semilla o cargador retail cercano
        nearest_retail = min((d for _, d in retail), default=None)
        seed_near = self._nearest_seed_mall(lat, lon)
        obs_anchor = min((d for s, d in obs_near if s["parking_spaces"] or s["site_type"] in ("mall", "mixed")), default=None)
        anchor_d = min([x for x in [nearest_retail, seed_near[1] if seed_near else None, obs_anchor] if x is not None], default=None)
        if anchor_d is None:
            retail_anchor_score = 20
        else:
            retail_anchor_score = max(0, 100 - anchor_d / radius_km * 100)

        # oportunidad Tesla: hay Tesla pero poca carga pública multi-estándar
        ntesla = len(tesla)
        non_tesla_public = sum(1 for p, _ in public if not p["tesla"])
        if ntesla > 0 and non_tesla_public <= ntesla:
            tesla_opp_score = min(100, 40 + 20 * ntesla)
        elif ntesla > 0:
            tesla_opp_score = 40
        else:
            tesla_opp_score = 10

        sub = {
            "demand": round(demand_score, 1),
            "gap": round(gap_score, 1),
            "ses": round(ses_score, 1),
            "retail_anchor": round(retail_anchor_score, 1),
            "tesla_opportunity": round(tesla_opp_score, 1),
        }
        W = config.WEIGHTS
        total = sum(sub[k] * W[k] for k in W)
        total = round(total, 1)

        verdict, verdict_msg = self._verdict(total)
        sites = 1  # siempre 1 set de 6 cargadores (6 autos simultáneos); no se proponen más

        # business case para el set de 6 cargadores
        biz = business.compute(sites, {"metro": metro, "ses_index": ses,
                                       "util": total / 100.0, "cp": cp})

        insights_txt = self._insights_text(metro, state_key, veh, sub, npub, ntesla, ses_ctx)
        if obs_near:
            fs = field_summary
            parts = [f"Levantamiento de campo: {', '.join(fs['sites'])} — "
                     f"{fs['units_operational']} cargadores operativos"]
            if fs["units_out_of_service"]:
                parts.append(f", {fs['units_out_of_service']} FUERA DE SERVICIO")
            if fs["units_planned"]:
                parts.append(f", {fs['units_planned']} planeados")
            if fs["parking_spaces"]:
                parts.append(f"; ~{fs['parking_spaces']:,} cajones de estacionamiento")
            if fs["ev_observed"]:
                parts.append(f"; {fs['ev_observed']} EV observados en sitio (dato real)")
            insights_txt.insert(0, "".join(parts) + ".")
            veh["ev_observed_in_radius"] = fs["ev_observed"]
            veh["parking_spaces_in_radius"] = fs["parking_spaces"]

        return {
            "query": {"lat": lat, "lon": lon, "radius_km": radius_km,
                      "metro": metro, "state": state_key},
            "score": total,
            "verdict": verdict,
            "verdict_msg": verdict_msg,
            "recommended_sites": sites,
            "subscores": sub,
            "weights": W,
            "business_case": biz,
            "chargers": {
                "total": len(nearby),
                "public": npub,
                "residential_observed": len(residential),
                "fast": len(fast),
                "tesla": ntesla,
                "retail": len(retail),
                "ev_per_public_charger": round(ev_per_charger, 1) if ev_per_charger else None,
            },
            "field_observations": field_summary,
            "connector_types": connectors.most_common(),
            "networks": networks.most_common(6),
            "vehicles_seen": vehicles.most_common(10),
            "estimation": veh,
            "ses_proxy": round(ses, 2),
            "nse": {"index": round(ses, 2), "source": ses_ctx["source"],
                    "zone": ses_ctx["zone"], "nse": ses_ctx["nse"]},
            "nearest_chargers": [
                {"name": p["name"] or p["address"][:40], "class": p["class"],
                 "tesla": p["tesla"], "fast": p["is_fast"], "dist_km": round(d, 2),
                 "connectors": p["connectors"], "lat": p["lat"], "lon": p["lon"]}
                for p, d in nearby[:8]
            ],
            "insights": insights_txt,
            "disclaimer": "cars_est/ev_est/home_chargers_est son estimaciones modeladas "
                          "(no registro vehicular real). Ver estimation.assumptions.",
        }

    # ---------- insight: armadora × NSE ----------
    def armadora_nse(self):
        """Cruce derivado (ICCT 2025 + AMAI): marca → segmento, NSE, precio,
        carga en casa e implicación para siting. Ilustrativo y tunable."""
        ins = self.insights
        bs = ins["brand_ses"]
        share = ins.get("bev_brand_share_2025", {})
        prices = ins["avg_price_mxn"]
        hp = ins["home_charging_propensity"]
        tier_label = {1: "medio", 2: "medio-alto", 3: "alto"}

        brands = []
        for brand, d in bs.items():
            tier = d["ses_tier"]
            seg = d["segment"]
            prop = hp[str(tier)]
            impl = ("NSE alto: alta carga en casa → priorizar carga de destino/retail (mall, no de necesidad)."
                    if tier == 3 else
                    "NSE medio-alto: mezcla casa/calle → buen candidato para carga pública semirrápida."
                    if tier == 2 else
                    "NSE medio: baja carga en casa → mayor dependencia de carga pública (necesidad).")
            brands.append({
                "brand": brand, "segment": seg, "ses_tier": tier,
                "ses_label": tier_label[tier],
                "market_share_bev": share.get(brand),
                "price_mxn": prices.get(seg),
                "home_charging_prop": prop,
                "siting_implication": impl,
                "note": d.get("note", ""),
            })
        brands.sort(key=lambda b: (-b["ses_tier"], -(b["market_share_bev"] or 0)))

        # agregado por tier
        by_tier = {}
        for t in (3, 2, 1):
            bl = [b for b in brands if b["ses_tier"] == t]
            share_sum = sum(b["market_share_bev"] or 0 for b in bl)
            by_tier[str(t)] = {
                "label": tier_label[t],
                "brands": [b["brand"] for b in bl],
                "bev_share_sum": round(share_sum, 3),
                "home_charging_prop": hp[str(t)],
            }
        return {
            "brands": brands,
            "by_tier": by_tier,
            "prices": prices,
            "notes": [
                "EVs son premium (BEV ~MX$822k vs ICE ~MX$554k): la adopción se concentra en NSE alto.",
                "NSE alto carga más en casa (80%) → la carga pública ahí es de destino/retail, no de necesidad.",
                "NSE medio depende más de carga pública → mayor urgencia de infraestructura de necesidad.",
                "Tesla/Volvo/BMW = NSE alto; BYD = líder cross-NSE (medio-alto); JAC = entrada (medio).",
            ],
        }

    # ---------- generación de candidatos ----------
    def _nearest_seed_mall(self, lat, lon):
        best = None
        for mall in config.SEED_MALLS:
            d = haversine_km(lat, lon, mall["lat"], mall["lon"])
            if best is None or d < best[1]:
                best = (mall, d)
        return best

    def generate_candidates(self, metro=None, top_n=15):
        metros = [metro] if metro else list(config.METROS.keys())
        cands = []

        # (A) Sitios Tesla existentes -> candidatos de upgrade multi-estándar
        for p in self.chargers:
            if not p["tesla"]:
                continue
            mname, m = self.metro_of(p["lat"], p["lon"])
            if not mname or (metro and mname != metro):
                continue
            cands.append({"lat": p["lat"], "lon": p["lon"], "kind": "tesla_upgrade",
                          "label": p["name"] or p["address"][:40] or "Sitio Tesla",
                          "reason": "Centro con carga Tesla — candidato para bloque multi-estándar (CCS/J-1772)."})

        # (B) Malls semilla sin cargador público cercano (o solo Tesla)
        for mall in config.SEED_MALLS:
            if metro and mall["metro"] != metro:
                continue
            near = self.index.query_radius(mall["lat"], mall["lon"], 0.5)
            pub = [p for p, _ in near if p["class"] == "public" and not p["tesla"]]
            tesla_only = [p for p, _ in near if p["tesla"]]
            if not pub:
                reason = ("Centro comercial sin carga pública multi-estándar cercana"
                          + (" (solo Tesla)" if tesla_only else "") + " — candidato greenfield.")
                cands.append({"lat": mall["lat"], "lon": mall["lon"], "kind": "mall_gap",
                              "label": mall["name"], "reason": reason})

        # (D) Observaciones de campo SIN carga operativa → candidatos directos
        for o in self.obs.items:
            mname, _ = self.metro_of(o["lat"], o["lon"])
            if not mname or (metro and mname != metro):
                continue
            s = obs_summarize(o)
            if s["operational"] > 0:
                continue
            reason = "Levantamiento de campo: sin carga operativa"
            if s["out_of_service"]:
                reason += f"; {s['out_of_service']} fuera de servicio"
            if s["parking_spaces"]:
                reason += f"; ~{s['parking_spaces']:,} cajones"
            if s["ev_observed"]:
                reason += f"; {s['ev_observed']} EV observados"
            cands.append({"lat": o["lat"], "lon": o["lon"], "kind": "field_gap",
                          "label": o["name"], "reason": reason + "."})

        # (C) Rejilla: huecos de alta demanda / baja oferta
        for mname in metros:
            m = config.METROS[mname]
            lat0, lat1 = m["lat"]; lon0, lon1 = m["lon"]
            step = 0.03  # ~3 km
            la = lat0
            while la <= lat1:
                lo = lon0
                while lo <= lon1:
                    near = self.index.query_radius(la, lo, config.DEFAULT_RADIUS_KM)
                    pub = sum(1 for p, _ in near if p["class"] == "public")
                    if pub <= 1:  # subatendido
                        cands.append({"lat": round(la, 4), "lon": round(lo, 4),
                                      "kind": "grid_gap", "label": f"Hueco {mname}",
                                      "reason": "Zona urbana con baja cobertura pública — hueco de demanda."})
                    lo += step
                la += step

        # Puntuar y deduplicar por cercanía
        scored = []
        for c in cands:
            a = self.analyze_point(c["lat"], c["lon"])
            scored.append({**c, "score": a["score"], "verdict": a["verdict"],
                           "recommended_sites": a["recommended_sites"],
                           "chargers": a["business_case"]["chargers"],
                           "metro": a["query"]["metro"],
                           "ev_est": a["estimation"]["ev_est"],
                           "public_chargers": a["chargers"]["public"],
                           "subscores": a["subscores"],
                           "capex": a["business_case"]["capex_total"],
                           "payback_years": a["business_case"]["payback_years"],
                           "break_even_months": a["business_case"]["break_even_months"]})
        scored.sort(key=lambda x: x["score"], reverse=True)

        deduped = []
        for c in scored:
            if any(haversine_km(c["lat"], c["lon"], d["lat"], d["lon"]) < 2.0 for d in deduped):
                continue
            deduped.append(c)
            if len(deduped) >= top_n:
                break
        return deduped

    # ---------- textos / bandas ----------
    def _verdict(self, total):
        for th, name, msg in config.VERDICT_BANDS:
            if total >= th:
                return name, msg
        return "BAJA", ""

    def _insights_text(self, metro, state_key, veh, sub, npub, ntesla, ses_ctx):
        ses = ses_ctx["index"]
        out = []
        if ses_ctx["source"] == "polygon":
            out.append(f"NSE (polígono oficial): {ses_ctx['zone']} — nivel {ses_ctx['nse']} "
                       f"(índice {round(ses,2)}).")
        d = self.demand.get(state_key)
        if d:
            out.append(f"Adopción estatal ({d['entidad']}): {d['ev_units_period']} EV/PHEV "
                       f"en el periodo ({round(d['share_national']*100,1)}% nacional).")
        out.append(f"Parque estimado en el radio: ~{veh['cars_est']:,} autos, "
                   f"~{veh['ev_est']:,} eléctricos/PHEV (penetración {veh['ev_penetration_pct']}%).")
        out.append(f"Carga en casa estimada: ~{veh['home_chargers_est']:,} cargadores residenciales "
                   f"(propensión NSE: {int(veh['home_charging_propensity']*100)}%).")
        if npub == 0:
            out.append("No hay carga pública en el radio: brecha total de oferta.")
        else:
            out.append(f"{npub} cargadores públicos en el radio.")
        if ntesla:
            out.append(f"{ntesla} sitios con carga Tesla — oportunidad de complementar con multi-estándar.")
        tier = "alto" if ses > 0.66 else ("medio-alto" if ses > 0.4 else "medio")
        if ses_ctx["source"] != "polygon":
            out.append(f"NSE (proxy por señales): {tier} — punto fuera de polígonos NSE cargados.")
        out.append("EVs en México son premium (BEV ~MX$822k vs ICE ~MX$554k), correlacionados con NSE alto.")
        return out


# instancia global (carga perezosa)
_engine = None
def get_engine():
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine
