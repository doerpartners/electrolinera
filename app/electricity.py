"""
Tarifa eléctrica real por ubicación: código postal -> municipio (catálogo SEPOMEX) -> división
tarifaria de CFE -> tarifa GDMTH (Gran Demanda Media Tensión Horaria) en MXN. Reemplaza el supuesto
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
    """cp (código postal, opcional) -> tarifa eléctrica resuelta para el sitio, en MXN."""
    e = config.ELECTRICITY
    municipio_key = _municipio_key_for_cp(cp)
    confirmed = municipio_key in e["municipio_division"]
    division_name = e["municipio_division"].get(municipio_key, FALLBACK_DIVISION)
    div = e["divisions"][division_name]

    return {
        "punta_mxn_kwh": div["punta"],
        "intermedia_mxn_kwh": div["intermedia"],
        "base_mxn_kwh": div["base"],
        "demand_mxn_kw_month": div["demanda_mxn_kw"],
        "fixed_mxn_month": div["cargo_fijo_mxn"],
        "dap": e["municipio_dap"].get(municipio_key),
        "division": division_name,
        "municipio": municipio_key,
        "confidence": "confirmado" if confirmed else "promedio nacional (sin confirmar por ubicación)",
        "source": div.get("source"),
        "as_of": div.get("as_of"),
    }


def dap_annual_mxn(dap_cfg, energy_cost_annual_mxn):
    """Monto anual del DAP (Derecho de Alumbrado Público) en MXN, según la fórmula del municipio."""
    if not dap_cfg or dap_cfg.get("type") == "none":
        return 0.0
    t = dap_cfg["type"]
    if t == "flat_mxn_month":
        return dap_cfg["amount_mxn"] * 12
    if t == "pct_of_energy_cost":
        return energy_cost_annual_mxn * dap_cfg["pct"]
    if t == "pct_of_energy_cost_capped":
        pct_amount = energy_cost_annual_mxn * dap_cfg["pct"]
        cap_annual_mxn = dap_cfg["cap_mxn_month"] * 12
        return min(pct_amount, cap_annual_mxn)
    return 0.0
