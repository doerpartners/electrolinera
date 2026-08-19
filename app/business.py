"""
Business case de una instalación de carga: CapEx, OpEx, ingresos, payback y ROI.

Costos variables por ubicación:
 - electricidad: tarifa MXN/kWh por código postal / región
 - renta: escala con el NSE de la zona
 - mano de obra / viáticos: escala con la metrópoli
 - mantenimiento, plataforma, seguros: por estación / por sitio

Punto de partida (config): ~MXN $4,000,000 total para un bloque de 6 estaciones.
Todo es tunable en app/config.py → BUSINESS_CASE.
"""
from . import config


def electricity_tariff(cp=None, metro=None):
    bc = config.BUSINESS_CASE
    if cp:
        pref = str(cp).strip()[:2]
        if pref in bc["electricity_by_cp2"]:
            return bc["electricity_by_cp2"][pref], f"CP {pref}xxx"
    if metro and metro in bc["electricity_by_metro"]:
        return bc["electricity_by_metro"][metro], metro
    return bc["electricity_default"], "default"


def capex(stations):
    bc = config.BUSINESS_CASE
    ref, refn = bc["reference_total_capex"], bc["reference_stations"]
    breakdown = {}
    for comp, spec in bc["capex_components"].items():
        amount_ref = spec["share"] * ref
        if spec["scaling"] == "per_station":
            val = (amount_ref / refn) * stations
        else:
            val = amount_ref
        breakdown[comp] = round(val)
    return sum(breakdown.values()), breakdown


def compute(stations, ctx):
    """ctx: {metro, ses_index, util (0..1), cp(optional)}."""
    bc = config.BUSINESS_CASE
    o, r = bc["opex"], bc["revenue"]
    stations = max(1, int(stations))

    # --- CapEx ---
    capex_total, capex_bd = capex(stations)

    # --- factores locales ---
    tariff, tariff_src = electricity_tariff(ctx.get("cp"), ctx.get("metro"))
    rent_mult = round(bc["rent_ses_base"] + ctx.get("ses_index", 0.5), 3)
    labor_mult = bc["labor_by_metro"].get(ctx.get("metro"), 1.0)

    # --- energía anual (utilización ligada al score/demanda del sitio) ---
    util = max(0.0, min(1.0, ctx.get("util", 0.5)))
    util_eff = r["util_floor"] + (1 - r["util_floor"]) * util
    sessions_day = r["base_sessions_per_station_day"] * util_eff
    energy_kwh = sessions_day * r["kwh_per_session"] * stations * 365

    sessions_year = sessions_day * stations * 365
    svc = bc.get("service", {})
    # precio y costo del servicio: se pueden sobrescribir vía ctx (análisis de sensibilidad)
    price_user = ctx.get("price_per_kwh", r["price_per_kwh_user"])
    svc_kwh = ctx.get("service_cost_per_kwh", svc.get("cost_per_kwh", 0.0))
    svc_session = svc.get("cost_per_session", 0.0)

    # --- costos VARIABLES (escalan con el volumen) ---
    elec = energy_kwh * tariff                                   # electricidad
    service_cost = energy_kwh * svc_kwh + sessions_year * svc_session  # costo del servicio
    variable_total = elec + service_cost

    # --- costos FIJOS (no dependen del volumen) ---
    rent = o["rent_monthly_base"] * rent_mult * 12
    maint = o["maintenance_annual_per_station"] * stations
    platform = o["platform_monthly_per_station"] * stations * 12
    labor = o["ops_labor_annual_base"] * labor_mult
    insurance = o["insurance_other_annual"]
    fixed_total = rent + maint + platform + labor + insurance

    opex_bd = {
        "electricidad": round(elec), "costo_servicio": round(service_cost),
        "renta": round(rent), "mantenimiento": round(maint),
        "plataforma_software": round(platform), "mano_obra_operacion": round(labor),
        "seguros_otros": round(insurance),
    }
    opex_total = variable_total + fixed_total

    # --- ingresos / rentabilidad ---
    revenue = energy_kwh * price_user
    gross_profit = revenue - opex_total
    monthly_net = gross_profit / 12.0

    # --- PUNTO DE EQUILIBRIO ---
    # (a) meses para recuperar la inversión (CapEx)
    break_even_months = round(capex_total / monthly_net, 1) if monthly_net > 0 else None
    # (b) equilibrio operativo: volumen para cubrir costos fijos con el margen de contribución
    margin_per_kwh = price_user - tariff - svc_kwh
    fixed_monthly = fixed_total / 12.0
    be_kwh_month = fixed_monthly / margin_per_kwh if margin_per_kwh > 0 else None
    be_sessions_month = (be_kwh_month / r["kwh_per_session"]) if be_kwh_month else None
    energy_month = energy_kwh / 12.0
    op_break_even_pct = round(100 * (be_kwh_month / energy_month), 0) if (be_kwh_month and energy_month) else None

    payback = round(capex_total / gross_profit, 1) if gross_profit > 0 else None
    horizon = bc["horizon_years"]
    roi = round((horizon * gross_profit - capex_total) / capex_total, 2) if capex_total else None

    return {
        "currency": bc["currency"],
        "stations": stations,
        "capex_total": capex_total,
        "capex_breakdown": capex_bd,
        "opex_annual": round(opex_total),
        "opex_breakdown": opex_bd,
        "opex_fixed_annual": round(fixed_total),
        "opex_variable_annual": round(variable_total),
        "revenue_annual": round(revenue),
        "gross_profit_annual": round(gross_profit),
        "break_even_months": break_even_months,
        "payback_years": payback,
        "roi_horizon_years": horizon,
        "roi": roi,
        "contribution_margin_per_kwh": round(margin_per_kwh, 2),
        "operational_break_even": {
            "kwh_month": round(be_kwh_month) if be_kwh_month else None,
            "sessions_month": round(be_sessions_month) if be_sessions_month else None,
            "pct_of_projected_volume": op_break_even_pct,
        },
        "energy_kwh_year": round(energy_kwh),
        "sessions_per_station_day": round(sessions_day, 1),
        "service_cost_per_kwh": svc_kwh,
        "local_factors": {
            "electricity_mxn_kwh": tariff, "electricity_source": tariff_src,
            "rent_mult": rent_mult, "labor_mult": labor_mult,
            "utilization": round(util_eff, 2),
        },
    }
