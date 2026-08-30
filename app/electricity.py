"""
Tarifa eléctrica real por ubicación: código postal -> municipio (catálogo SEPOMEX) -> división
tarifaria de CFE -> tarifa GDMTH (Gran Demanda Media Tensión Horaria) en USD. Reemplaza el supuesto
plano nacional anterior. Ver app/config.py -> ELECTRICITY para las cifras, fuentes y fechas citadas,
y qué tan completo está el "esqueleto" (6 municipios confirmados; el resto cae a un promedio
nacional explícitamente marcado como no confirmado).
"""
import json, os
from . import config

HERE = os.path.dirname(os.path.abspath(__file__))
PROC = os.path.join(os.path.dirname(HERE), "data", "processed")
FALLBACK_DIVISION = "Nacional (promedio, sin confirmar)"

_cp_municipio_cache = None


def _cp_municipio():
    global _cp_municipio_cache
    if _cp_municipio_cache is None:
        path = os.path.join(PROC, "cp_municipio.json")
        _cp_municipio_cache = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    return _cp_municipio_cache


def _municipio_key_for_cp(cp):
    if not cp:
        return None
    row = _cp_municipio().get(str(cp).strip())
    return f"{row['municipio']}|{row['estado']}" if row else None


def resolve(cp):
    """cp (código postal, opcional) -> tarifa eléctrica resuelta para el sitio, ya en USD."""
    e = config.ELECTRICITY
    fx = e["mxn_usd_fx_rate"]
    municipio_key = _municipio_key_for_cp(cp)
    confirmed = municipio_key in e["municipio_division"]
    division_name = e["municipio_division"].get(municipio_key, FALLBACK_DIVISION)
    div = e["divisions"][division_name]

    return {
        "punta_usd_kwh": round(div["punta"] / fx, 4),
        "intermedia_usd_kwh": round(div["intermedia"] / fx, 4),
        "base_usd_kwh": round(div["base"] / fx, 4),
        "demand_usd_kw_month": round(div["demanda_mxn_kw"] / fx, 3),
        "fixed_usd_month": round(div["cargo_fijo_mxn"] / fx, 3),
        "dap": e["municipio_dap"].get(municipio_key),
        "division": division_name,
        "municipio": municipio_key,
        "confidence": "confirmado" if confirmed else "promedio nacional (sin confirmar por ubicación)",
        "source": div.get("source"),
        "as_of": div.get("as_of"),
    }


def dap_annual_usd(dap_cfg, energy_cost_annual_usd):
    """Monto anual del DAP (Derecho de Alumbrado Público) en USD, según la fórmula del municipio."""
    if not dap_cfg or dap_cfg.get("type") == "none":
        return 0.0
    fx = config.ELECTRICITY["mxn_usd_fx_rate"]
    t = dap_cfg["type"]
    if t == "flat_mxn_month":
        return dap_cfg["amount_mxn"] * 12 / fx
    if t == "pct_of_energy_cost":
        return energy_cost_annual_usd * dap_cfg["pct"]
    if t == "pct_of_energy_cost_capped":
        pct_amount = energy_cost_annual_usd * dap_cfg["pct"]
        cap_annual_usd = dap_cfg["cap_mxn_month"] * 12 / fx
        return min(pct_amount, cap_annual_usd)
    return 0.0
