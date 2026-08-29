"""
Business case de un sitio de carga: CapEx, OpEx, ingresos, payback y ROI a 9 años.

Modelo por sitio (hub de 360kW), tomado del "Modelo de Negocios" del proveedor.
Escala linealmente por número de sitios (todos idénticos). Todo tunable en
app/config.py -> BUSINESS_CASE.

Cosas de la fuente que NO se portaron (documentadas para que no parezcan un olvido):
 - La curva "tiempo esperado de utilización" del Excel no alimentaba ninguna fórmula
   de energía/ingreso/costo ahí — solo la curva de "utilización esperada" se usa aquí.
 - El ROI acumulado de la fuente restaba una celda de reinversión en el año 6 que
   nunca se llenó — no se modela ninguna reinversión a mitad de vida.
 - El precio al usuario es el mismo en horario punta y valle en la fuente (a pesar de
   una etiqueta que sugiere +25% en punta que no se refleja en el valor).
 - Las comisiones de venta (VIP/Vendedor/Arquitecto) no estaban conectadas a la hoja
   de ROI en la fuente — aquí se devuelven aparte, informativas, sin restar del
   retorno del inversionista.
"""
from . import config


def _commissions(capex_total, sites):
    c = config.BUSINESS_CASE["commissions"]
    return {
        "vip_usd": round(capex_total * c["vip_pct_of_capex"]),
        "vendedor_usd": round(c["vendedor_flat_usd"] * sites),
        "arquitecto_usd": round(c["arquitecto_flat_usd"] * sites),
        "recurring_note": c["recurring_note"],
    }


def compute(sites, ctx):
    """ctx: {metro, ses_index, util (0..1), cp(optional)} — metro/ses_index/cp ya no
    afectan el cálculo (el modelo por sitio es nacional/plano); se mantienen en la
    firma por compatibilidad con los llamadores existentes."""
    bc = config.BUSINESS_CASE
    sites = max(1, int(sites))

    capex_total = sites * bc["site_capex_usd"]
    capacity = bc["site_capacity_kw"]
    peak_h, offpeak_h = bc["peak_hours_per_day"], bc["offpeak_hours_per_day"]
    # overrides para análisis de sensibilidad (precio al usuario / costo de servicio agregado)
    price = ctx.get("price_per_kwh", bc["price_per_kwh_user"])
    service_pct = ctx.get("service_opex_pct",
                          bc["payment_gateway_pct"] + bc["maintenance_pct"] + bc["platform_pct"])
    loss = 1 + bc["electrical_loss_ratio"]
    elec_peak = bc["electricity_cost_peak_per_kwh"] * loss
    elec_offpeak = bc["electricity_cost_offpeak_per_kwh"] * loss
    landlord_share = bc["landlord_profit_share"]

    util = max(0.0, min(1.0, ctx.get("util", 0.5)))
    util_eff = bc["util_floor"] + (1 - bc["util_floor"]) * util

    years = []
    cumulative_investor = -capex_total
    for i, util_year in enumerate(bc["utilization_by_year"]):
        utilization = util_year * util_eff
        kw_peak = capacity * utilization * peak_h
        kw_offpeak = capacity * utilization * offpeak_h
        revenue = (kw_peak * price + kw_offpeak * price) * 365 * sites

        electricity_cost = (kw_peak * elec_peak + kw_offpeak * elec_offpeak) * 365 * sites
        service_cost = revenue * service_pct
        opex = electricity_cost + service_cost

        gross_profit = revenue - opex
        landlord_profit = gross_profit * landlord_share
        investor_profit = gross_profit - landlord_profit
        cumulative_investor += investor_profit

        years.append({
            "year": i + 1,
            "utilization": round(utilization, 3),
            "revenue": round(revenue),
            "opex": round(opex),
            "opex_breakdown": {
                "electricidad": round(electricity_cost),
                "mantenimiento_plataforma_pasarela": round(service_cost),
            },
            "gross_profit": round(gross_profit),
            "landlord_profit": round(landlord_profit),
            "investor_profit": round(investor_profit),
            "cumulative_investor_profit": round(cumulative_investor),
        })

    # payback: primer año en que el acumulado del inversionista cruza a positivo
    payback_years = None
    prev_cum = -capex_total
    for y in years:
        if y["cumulative_investor_profit"] >= 0:
            span = y["cumulative_investor_profit"] - prev_cum
            frac = (0 - prev_cum) / span if span else 0
            payback_years = round((y["year"] - 1) + frac, 2)
            break
        prev_cum = y["cumulative_investor_profit"]

    year1, year9 = years[0], years[-1]
    horizon = bc["horizon_years"]
    roi = round(year9["cumulative_investor_profit"] / capex_total, 2) if capex_total else None

    avg_electricity_per_kwh = (elec_peak * peak_h + elec_offpeak * offpeak_h) / (peak_h + offpeak_h)
    service_cost_per_kwh = round(price * service_pct, 3)
    contribution_margin_per_kwh = round(price - avg_electricity_per_kwh - service_cost_per_kwh, 3)

    return {
        "currency": bc["currency"],
        "sites": sites,
        "capex_total": capex_total,
        "horizon_years": horizon,
        "years": years,
        "year1": year1,
        "year9": year9,
        "revenue_annual": year1["revenue"],
        "opex_annual": year1["opex"],
        "opex_breakdown": year1["opex_breakdown"],
        "gross_profit_annual": year1["gross_profit"],
        "payback_years": payback_years,
        "break_even_months": round(payback_years * 12, 1) if payback_years is not None else None,
        "roi_horizon_years": horizon,
        "roi": roi,
        "contribution_margin_per_kwh": contribution_margin_per_kwh,
        "service_cost_per_kwh": service_cost_per_kwh,
        "commissions": _commissions(capex_total, sites),
        "local_factors": {
            "electricity_peak_usd_kwh": round(elec_peak, 3),
            "electricity_offpeak_usd_kwh": round(elec_offpeak, 3),
            "price_per_kwh_user": price,
            "utilization": round(util_eff, 2),
        },
    }
