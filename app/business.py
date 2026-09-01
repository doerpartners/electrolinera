"""
Business case de 1 set de 6 cargadores (6 autos cargando simultáneamente):
CapEx, OpEx, ingresos, payback, NPV y ROI a 9 años.

Modelo tomado del "Modelo de Negocios" del proveedor (hub de 360kW ≈ 6 cargadores
de ~60kW). `compute()` recibe `sites` por compatibilidad pero siempre se llama con
1 — no se recomiendan/escalan sets adicionales aunque la demanda sea alta. Todo
tunable en app/config.py -> BUSINESS_CASE.

`compute()` también recibe `case` ("full" por default, o "partial"): el caso parcial
es un despliegue de 4 cargadores (no 6), sin contrato de demanda CFE ni renta al
predio — usa config.BUSINESS_CASE_PARTIAL_OVERRIDES, que hoy recorta el OpEx completo
a un 25% plano como placeholder (ver comentario ahí) hasta tener un desglose de OpEx
propio para este caso.

Cosas de la fuente que NO se portaron (documentadas para que no parezcan un olvido):
 - La curva "tiempo esperado de utilización" del Excel no alimentaba ninguna fórmula
   de energía/ingreso/costo ahí — solo la curva de "utilización esperada" se usa aquí.
 - El ROI acumulado de la fuente restaba una celda de reinversión en el año 6 que
   nunca se llenó — no se modela ninguna reinversión a mitad de vida.
 - El precio al usuario es el mismo en los 3 periodos horarios en la fuente (a pesar
   de una etiqueta que sugiere +25% en punta que no se refleja en el valor).
 - Las comisiones de venta (VIP/Vendedor/Arquitecto) no estaban conectadas a la hoja
   de ROI en la fuente — aquí se devuelven aparte, informativas, sin restar del
   retorno del inversionista.

Extensiones agregadas sobre la fuente (no vienen del Excel):
 - Inflación anual nominal, aplicada por igual a precio y costos de electricidad.
 - NPV a la tasa de descuento configurada, además del payback/ROI simples ya existentes.
 - Valor residual del hardware al año 9 (% del CapEx), que se suma al flujo del
   inversionista solo en ese último año.
 - La curva de utilización (antes una lista fija de 9 valores tomada del Excel) ahora
   se genera con `utilization_year1_pct * (1 + ev_fleet_growth_pct_yoy)^año`, con tope
   en `utilization_ceiling_pct` — liga el ritmo de adopción real de EV/PHEV (parámetro
   compartido con VEHICLE_MODEL en scoring.py) a la proyección de ingresos del ROI, en
   vez de una curva arbitraria y fija.
 - El costo de electricidad ya NO es un supuesto plano: viene de app/electricity.py,
   que resuelve la tarifa real de CFE (GDMTH, 3 periodos horarios + cargo por demanda
   + cargo fijo + DAP municipal) según el código postal del sitio. Incluye el cargo
   por demanda ($/kW de capacidad contratada, ~360kW) — un costo real de GDMTH que el
   modelo anterior no consideraba y que puede ser el componente más grande del OpEx.
 - `estimated_daily_charging_cars` por año: la energía diaria que el sitio dispensa
   (capacidad × utilización × 24h) dividida entre `avg_kwh_per_charge_session` (30kWh
   por default) — ancla el caso de negocio a un número de "coches cargando al día" en
   vez de solo revenue/kWh, a pedido explícito del cliente (más fácil de contrastar
   contra la inversión que un total de EVs en el radio).

Todo el caso de negocio vive en MXN (pesos) — ver app/config.py -> BUSINESS_CASE para la nota
sobre el tipo de cambio de un solo uso con el que se convirtieron las cifras originales en USD
de la fuente. No hay ninguna conversión de moneda en tiempo de ejecución en este módulo.
"""
from . import config, electricity


def _commissions(capex_total, sites):
    c = config.BUSINESS_CASE["commissions"]
    return {
        "vip_mxn": round(capex_total * c["vip_pct_of_capex"]),
        "vendedor_mxn": round(c["vendedor_flat_mxn"] * sites),
        "arquitecto_mxn": round(c["arquitecto_flat_mxn"] * sites),
        "recurring_note": c["recurring_note"],
    }


def compute(sites, ctx, case="full"):
    """ctx: {metro, ses_index, util (0..1), cp(optional), electricity(optional, ya resuelto)}.
    case: "full" (1 set de 6 cargadores, OpEx completo con contrato CFE + renta) |
    "partial" (4 cargadores, sin contrato de demanda CFE ni renta al predio — ver
    config.BUSINESS_CASE_PARTIAL_OVERRIDES)."""
    bc = {**config.BUSINESS_CASE, **(config.BUSINESS_CASE_PARTIAL_OVERRIDES if case == "partial" else {})}
    opex_multiplier = bc.get("opex_multiplier", 1.0)
    sites = max(1, int(sites))

    capex_total = sites * bc["site_capex_mxn"]
    capacity = bc["site_capacity_kw"]
    ph = config.ELECTRICITY["period_hours"]
    punta_h, intermedia_h, base_h = ph["punta"], ph["intermedia"], ph["base"]
    # overrides para análisis de sensibilidad (precio al usuario / costo de servicio agregado)
    price0 = ctx.get("price_per_kwh", bc["price_per_kwh_user"])
    service_pct_override = ctx.get("service_opex_pct")
    bank_pct = bc["bank_commission_pct"]
    maint_pct = bc["maintenance_pct"]
    platform_pct = bc["platform_pct"]

    elec = ctx.get("electricity") or electricity.resolve(ctx.get("cp"))
    loss = 1 + bc["electrical_loss_ratio"]
    punta0 = elec["punta_mxn_kwh"] * loss
    intermedia0 = elec["intermedia_mxn_kwh"] * loss
    base0 = elec["base_mxn_kwh"] * loss
    demand0 = elec["demand_mxn_kw_month"] * capacity * 12 * sites  # cargo por capacidad contratada
    fixed0 = elec["fixed_mxn_month"] * 12 * sites

    landlord_share = bc["landlord_profit_share"]
    inflation = bc["inflation_pct"]
    discount_rate = bc["discount_rate_pct"]
    residual_value = capex_total * bc["residual_value_pct"]

    util = max(0.0, min(1.0, ctx.get("util", 0.5)))
    util_eff = bc["util_floor"] + (1 - bc["util_floor"]) * util

    ev_growth = config.VEHICLE_MODEL["ev_fleet_growth_pct_yoy"]
    utilization_ceiling = bc["utilization_ceiling_pct"]
    utilization_by_year = [min(utilization_ceiling, bc["utilization_year1_pct"] * (1 + ev_growth) ** i)
                            for i in range(bc["horizon_years"])]
    avg_kwh_per_charge = bc.get("avg_kwh_per_charge_session", 30)

    years = []
    cumulative_investor = -capex_total
    investor_cashflows = [-capex_total]
    for i, util_year in enumerate(utilization_by_year):
        infl_mult = (1 + inflation) ** i
        price = price0 * infl_mult
        punta, intermedia, base = punta0 * infl_mult, intermedia0 * infl_mult, base0 * infl_mult
        demand_charge, fixed_charge = demand0 * infl_mult, fixed0 * infl_mult

        utilization = util_year * util_eff
        kw_punta = capacity * utilization * punta_h
        kw_intermedia = capacity * utilization * intermedia_h
        kw_base = capacity * utilization * base_h
        kw_total = kw_punta + kw_intermedia + kw_base
        revenue = kw_total * price * 365 * sites
        estimated_daily_cars = round(kw_total * sites / avg_kwh_per_charge) if avg_kwh_per_charge else None

        energy_cost = (kw_punta * punta + kw_intermedia * intermedia + kw_base * base) * 365 * sites
        dap_cost = electricity.dap_annual_mxn(elec["dap"], energy_cost)

        if service_pct_override is not None:
            opex_breakdown = {
                "electricidad_energia": round(energy_cost),
                "electricidad_demanda": round(demand_charge),
                "electricidad_cargo_fijo": round(fixed_charge),
                "electricidad_dap": round(dap_cost),
                "servicio": round(revenue * service_pct_override),
            }
        else:
            opex_breakdown = {
                "electricidad_energia": round(energy_cost),
                "electricidad_demanda": round(demand_charge),
                "electricidad_cargo_fijo": round(fixed_charge),
                "electricidad_dap": round(dap_cost),
                "comision_bancaria": round(revenue * bank_pct),
                "mantenimiento": round(revenue * maint_pct),
                "plataforma_software": round(revenue * platform_pct),
            }
        if opex_multiplier != 1.0:
            opex_breakdown = {k: round(v * opex_multiplier) for k, v in opex_breakdown.items()}
        opex = sum(opex_breakdown.values())

        gross_profit = revenue - opex
        landlord_profit = gross_profit * landlord_share
        investor_profit = gross_profit - landlord_profit
        is_last_year = (i == len(utilization_by_year) - 1)
        year_residual = residual_value if is_last_year else 0
        cumulative_investor += investor_profit + year_residual
        investor_cashflows.append(investor_profit + year_residual)

        years.append({
            "year": i + 1,
            "utilization": round(utilization, 3),
            "estimated_daily_charging_cars": estimated_daily_cars,
            "revenue": round(revenue),
            "opex": round(opex),
            "opex_breakdown": opex_breakdown,
            "gross_profit": round(gross_profit),
            "landlord_profit": round(landlord_profit),
            "investor_profit": round(investor_profit),
            "residual_value": round(year_residual),
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
    npv = round(sum(cf / (1 + discount_rate) ** y for y, cf in enumerate(investor_cashflows)))

    avg_electricity_per_kwh = (punta0 * punta_h + intermedia0 * intermedia_h + base0 * base_h) / 24
    service_pct_display = service_pct_override if service_pct_override is not None else (bank_pct + maint_pct + platform_pct)
    service_cost_per_kwh = round(price0 * service_pct_display, 3)
    contribution_margin_per_kwh = round(price0 - avg_electricity_per_kwh - service_cost_per_kwh, 3)

    return {
        "currency": bc["currency"],
        "case": case,
        "sites": sites,
        "chargers": bc["chargers_per_site"] * sites,
        "capex_total": capex_total,
        "horizon_years": horizon,
        "years": years,
        "year1": year1,
        "year9": year9,
        "revenue_annual": year1["revenue"],
        "opex_annual": year1["opex"],
        "opex_breakdown": year1["opex_breakdown"],
        "gross_profit_annual": year1["gross_profit"],
        "estimated_daily_charging_cars": year1["estimated_daily_charging_cars"],
        "payback_years": payback_years,
        "break_even_months": round(payback_years * 12, 1) if payback_years is not None else None,
        "roi_horizon_years": horizon,
        "roi": roi,
        "npv": npv,
        "discount_rate_pct": discount_rate,
        "residual_value": round(residual_value),
        "contribution_margin_per_kwh": contribution_margin_per_kwh,
        "service_cost_per_kwh": service_cost_per_kwh,
        "commissions": _commissions(capex_total, sites),
        "local_factors": {
            "electricity_punta_mxn_kwh": round(punta0, 4),
            "electricity_intermedia_mxn_kwh": round(intermedia0, 4),
            "electricity_base_mxn_kwh": round(base0, 4),
            "electricity_demand_mxn_kw_month": elec["demand_mxn_kw_month"],
            "electricity_division": elec["division"],
            "electricity_confidence": elec["confidence"],
            "electricity_source": elec["source"],
            "electricity_as_of": elec["as_of"],
            "price_per_kwh_user": price0,
            "utilization": round(util_eff, 2),
            "inflation_pct": inflation,
            "ev_fleet_growth_pct_yoy": ev_growth,
            "landlord_profit_share": landlord_share,
            "avg_kwh_per_charge_session": avg_kwh_per_charge,
        },
    }
