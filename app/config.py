"""
Configuración tunable del sistema de recomendación.
Todo lo que aquí vive puede ajustarse conforme se alimenten insights nuevos,
sin tocar la lógica del motor de scoring.
"""

# --- Radio de análisis: cuánto se mueve la gente diario alrededor de su casa ---
# Ya no es un valor fijo elegido por el usuario — se determina automáticamente según si el
# punto cae dentro de una metrópoli conocida (config.METROS) o no (urbano vs. rural/disperso).
# Base calibrada con datos reales: INEGI Encuesta Origen-Destino 2017 (ZMVM), base reprocesada
# por WRI México con distancia de viaje por localidad (TLOC 1=más urbano..4=más disperso):
#   TLOC=1 (más urbano): 4.19km promedio ponderado -> base de "urbano"
#   TLOC=4 (más disperso): 7.15km promedio ponderado -> base de "rural", redondeado un poco al
#   alza porque metros más pequeños/dispersos que la ZMVM (ej. San Miguel de Allende y todo lo
#   que cae fuera de las 6 metrópolis cubiertas) pueden ser más dispersos que cualquier zona
#   TLOC=4 capturada ahí — extrapolación documentada, no medida directamente.
# Fuera de la ZMVM esto es una aproximación (solo tenemos el dato real para esa zona), pero es
# consistente con la literatura internacional de "activity space" (~2x urbano/rural, no 5-10x).
#
# Encima de esa base medida se aplica un "premio de búsqueda EV": un dueño de auto eléctrico
# tiene una motivación adicional (autonomía, planeación de ruta, pocos cargadores convenientes)
# para buscar un cargador más allá de su radio normal de circulación diaria — no viene de la
# EOD, es un supuesto explícito y ajustable (no medido).
MOBILITY_RADIUS_KM_BASE = {"urbano_km": 4.2, "rural_km": 8.0}  # medido (ver detalle arriba)
EV_SEARCH_PREMIUM_PCT = 0.50  # % adicional sobre el radio normal de circulación
MOBILITY_RADIUS_KM = {
    "urbano_km": round(MOBILITY_RADIUS_KM_BASE["urbano_km"] * (1 + EV_SEARCH_PREMIUM_PCT), 2),
    "rural_km": round(MOBILITY_RADIUS_KM_BASE["rural_km"] * (1 + EV_SEARCH_PREMIUM_PCT), 2),
}

# --- Unidad de despliegue: siempre 1 set de 6 cargadores (6 autos simultáneos) ---
# No se recomiendan sitios/sets adicionales aunque la demanda sea alta.

# --- Pesos del score de idoneidad (suman 1.0). Tunables. ---
WEIGHTS = {
    "demand": 0.34,        # EVs estimados en el radio (adopción estatal + NSE)
    "gap": 0.28,           # brecha oferta pública vs demanda (subatendido = bueno)
    "ses": 0.16,           # nivel socioeconómico / poder adquisitivo (proxy)
    "retail_anchor": 0.12, # ancla comercial (mall, dining, grocery)
    "tesla_opportunity": 0.10,  # sitio Tesla-only => oportunidad multi-estándar
}

# --- Umbrales para el veredicto textual ---
VERDICT_BANDS = [
    (75, "EXCELENTE", "Ubicación de alta prioridad para instalar."),
    (60, "BUENA", "Ubicación recomendable; revisar detalles de sitio."),
    (45, "MODERADA", "Viable pero con reservas; validar demanda local."),
    (0,  "BAJA", "No recomendada por ahora; poca demanda o saturación."),
]

# --- Saturación: EVs estimados por cargador público en el radio ---
# Menos cargadores por EV = más saturado. Referencia: se considera sano ~15 EV/cargador.
HEALTHY_EV_PER_PUBLIC_CHARGER = 15

# EVs estimados en el radio que "saturan" el score de demanda (=100).
SATURATION_EVS = 2500

# Estacionamiento como factor de demanda: cajones × penetración EV × rotación
# = potencial de EVs que usarían el sitio. Un lote de 5,000 pesa más que uno de 500.
PARKING_DEMAND_TURNOVER = 4  # vehículos distintos por cajón al día (rotación)

# --- Metros objetivo para generación de candidatos (bounding boxes) ---
METROS = {
    "Monterrey":  {"lat": (25.40, 25.95), "lon": (-100.60, -100.00), "state": "NL"},
    "Guadalajara":{"lat": (20.40, 20.90), "lon": (-103.60, -103.20), "state": "JAL"},
    "CDMX":       {"lat": (19.20, 19.70), "lon": (-99.40, -98.90),   "state": "CDMX"},
    "Mérida":     {"lat": (20.85, 21.10), "lon": (-89.80, -89.45),   "state": "YUC"},
    "Morelia":    {"lat": (19.60, 19.80), "lon": (-101.32, -101.05), "state": "MIC"},
    "San Miguel de Allende": {"lat": (20.82, 21.00), "lon": (-100.85, -100.62), "state": "GTO"},
}

# --- Modelo de estimación de parque vehicular (transparente, tunable) ---
# No existe registro vehicular geolocalizado; se modela con supuestos explícitos.
VEHICLE_MODEL = {
    # Autos por km² en zona urbana metropolitana (densidad base aprox.).
    "cars_per_km2_urban": 700,
    # % de esos autos que son EV/PHEV — se escala por adopción estatal e índice NSE.
    "base_ev_penetration": 0.004,   # ~0.4% base del parque circulante (stock, no ventas)
    # Multiplicadores por índice de adopción estatal (share AMIA normalizado).
    "state_adoption_boost_max": 2.5,
    # Multiplicador por NSE (proxy local): NSE alto => más EVs.
    "ses_boost_max": 2.0,
    # % de crecimiento anual del parque EV+PHEV — alimenta la curva de utilización
    # a 9 años del business case (ver BUSINESS_CASE.utilization_ceiling_pct).
    # Default calibrado para reproducir de cerca la curva original del proveedor (23%→40%).
    "ev_fleet_growth_pct_yoy": 0.097,
}

# --- Business case: costos, ingresos y payback (todo tunable) ---
# Siempre 1 set de 6 cargadores (360kW ≈ 6 × 60kW, 6 autos cargando simultáneamente),
# a 9 años — vida media asumida de un cargador EV. No se proponen sets adicionales.
# Fuente: modelo de negocios del proveedor (Excel "Modelo de Negocios", 9 años).
BUSINESS_CASE = {
    "currency": "USD",
    "horizon_years": 9,
    "site_capex_usd": 250_000,   # transformador + 6 cargadores + cable + instalación, el set completo
    "site_capacity_kw": 360,     # 6 cargadores × ~60kW
    "chargers_per_site": 6,
    # Curva de utilización año 1..9: arranca en utilization_year1_pct y crece cada año
    # al ritmo de VEHICLE_MODEL.ev_fleet_growth_pct_yoy, con tope en utilization_ceiling_pct
    # (capacidad física realista del set de 6 cargadores). Reemplaza la lista fija original
    # del proveedor (23%→40%) por una fórmula ligada al crecimiento real del parque EV.
    "utilization_year1_pct": 0.23,
    "utilization_ceiling_pct": 0.40,
    "util_floor": 0.30,   # piso: multiplica la curva de arriba según el score del sitio (no viene del Excel)
    "price_per_kwh_user": 0.46,               # mismo precio en los 3 periodos (así viene calculado en la fuente)
    "electrical_loss_ratio": 0.10,             # pérdida eléctrica aplicada al costo de energía
    "bank_commission_pct": 0.0,                # comisión bancaria/pasarela de pago, % de facturación (sin costo en la fuente)
    "maintenance_pct": 0.10,                   # % de facturación
    "platform_pct": 0.13,                      # % de facturación
    "landlord_profit_share": 0.16,             # resto (84%) es del inversionista
    "inflation_pct": 0.0,                      # inflación anual nominal: escala precio y costo de electricidad por igual
    "discount_rate_pct": 0.12,                 # tasa de descuento para NPV (WACC / tasa mínima esperada, asunción — ajustable)
    "residual_value_pct": 0.20,                # valor residual del hardware al año 9, % del CapEx, para el inversionista
    # Comisiones de venta por sitio implementado — informativas, no restan del ROI del inversionista
    # (en la fuente tampoco están conectadas a la hoja de ROI).
    "commissions": {
        "vip_pct_of_capex": 0.05,
        "vendedor_flat_usd": 2_500,
        "arquitecto_flat_usd": 2_500,
        "recurring_note": ("Comisión recurrente mensual (0.5% VIP + 0.5% vendedor) solo aplica a "
                            "clientes con cartera de 100+ sitios; no se calcula por sitio individual."),
    },
}

# --- Tarifa eléctrica real por ubicación (CFE, tarifa GDMTH — Gran Demanda Media Tensión ---
# Horaria) para consumo comercial/industrial. Reemplaza el supuesto plano anterior.
# CP -> municipio (data/processed/cp_municipio.json, catálogo SEPOMEX) -> división CFE -> tarifa.
# Fuente de las 6 divisiones abajo: DOF, "Tarifas finales del Suministro Básico" (boletines
# 2025-11-28 y 2026-07-31). Cifras en MXN; se convierten a USD con mxn_usd_fx_rate en electricity.py.
# El catálogo SEPOMEX registra el municipio de CDMX como la alcaldía (no "Ciudad de México"),
# de ahí las 16 claves explícitas abajo — todas caen en la misma división/DAP (aproximación
# documentada; CDMX tiene 3 sub-divisiones reales, ver nota más abajo).
_CDMX_ALCALDIAS = ["Álvaro Obregón", "Azcapotzalco", "Benito Juárez", "Coyoacán",
                   "Cuajimalpa de Morelos", "Cuauhtémoc", "Gustavo A. Madero", "Iztacalco",
                   "Iztapalapa", "La Magdalena Contreras", "Miguel Hidalgo", "Milpa Alta",
                   "Tláhuac", "Tlalpan", "Venustiano Carranza", "Xochimilco"]
_CDMX_KEYS = [f"{a}|Ciudad de México" for a in _CDMX_ALCALDIAS]

ELECTRICITY = {
    "mxn_usd_fx_rate": 18.5,  # aproximado — actualizar con el tipo de cambio Banxico vigente
    # ⚠️ Ventanas horarias sin confirmar con el anexo metodológico CRE/CNE (no está en los
    # boletines de tarifas) — split genérico ampliamente citado (punta 18-22h, base 00-06h).
    # Tunable; reemplazar si se consigue el anexo real por división/temporada.
    "period_hours": {"punta": 4, "intermedia": 14, "base": 6},
    "divisions": {
        # punta/intermedia/base: MXN/kWh. demanda_mxn_kw: MXN/kW de capacidad/mes. cargo_fijo: MXN/mes.
        "Golfo Norte": {"punta": 1.6634, "intermedia": 1.5333, "base": 0.9904,
                        "demanda_mxn_kw": 444.11, "cargo_fijo_mxn": 502.03,
                        "source": "DOF 2026-07-31", "as_of": "2026-07"},
        "Jalisco": {"punta": 2.1829, "intermedia": 1.9387, "base": 1.0810,
                    "demanda_mxn_kw": 589.41, "cargo_fijo_mxn": 372.38,
                    "source": "DOF 2025-11-28", "as_of": "2025-11"},
        "Peninsular": {"punta": 2.4864, "intermedia": 2.2270, "base": 1.3180,
                       "demanda_mxn_kw": 516.95, "cargo_fijo_mxn": 421.57,
                       "source": "DOF 2025-11-28", "as_of": "2025-11"},
        "Centro Occidente": {"punta": 2.0412, "intermedia": 1.8132, "base": 1.0206,
                             "demanda_mxn_kw": 532.42, "cargo_fijo_mxn": 252.50,
                             "source": "DOF 2026-07-31", "as_of": "2026-07"},
        "Bajío": {"punta": 2.0620, "intermedia": 1.8107, "base": 1.0228,
                  "demanda_mxn_kw": 475.04, "cargo_fijo_mxn": 427.19,
                  "source": "DOF 2026-07-31", "as_of": "2026-07"},
        "Valle de México Centro": {"punta": 2.2908, "intermedia": 1.9601, "base": 1.1823,
                                    "demanda_mxn_kw": 496.78, "cargo_fijo_mxn": 466.83,
                                    "source": "DOF 2025-11-28", "as_of": "2025-11"},
        # Fallback para CP fuera de las 6 divisiones confirmadas: promedio simple de las 6 de arriba.
        # No es una tarifa real de ninguna división — se marca explícitamente como no confirmada.
        "Nacional (promedio, sin confirmar)": {"punta": 2.1211, "intermedia": 1.8805, "base": 1.1025,
                                                "demanda_mxn_kw": 509.12, "cargo_fijo_mxn": 407.08,
                                                "source": "promedio de las 6 divisiones confirmadas",
                                                "as_of": None},
    },
    # Municipio -> división. Clave "Municipio|Estado" (coincide con el catálogo SEPOMEX).
    "municipio_division": {
        "Monterrey|Nuevo León": "Golfo Norte",
        "Guadalajara|Jalisco": "Jalisco",
        "Mérida|Yucatán": "Peninsular",
        "Morelia|Michoacán de Ocampo": "Centro Occidente",  # SEPOMEX usa el nombre oficial completo
        "San Miguel de Allende|Guanajuato": "Bajío",
        # CDMX tiene 3 sub-divisiones (Centro/Norte/Sur, ±5-8% entre sí); "Centro" es el default
        # documentado — afinar por alcaldía es un refinamiento futuro.
        **{k: "Valle de México Centro" for k in _CDMX_KEYS},
    },
    # DAP (Derecho de Alumbrado Público): lo fija cada municipio, no CFE. A escala de consumo
    # comercial (~360kW) casi siempre es marginal frente al costo de energía/demanda de arriba.
    # type: "none" (confirmado que no aplica) | "flat_mxn_month" | "pct_of_energy_cost" |
    # "pct_of_energy_cost_capped" (con tope en pesos/mes). Sin entrada = sin confirmar -> no se aplica.
    "municipio_dap": {
        "Guadalajara|Jalisco": {"type": "none", "source": "Ley de Ingresos Guadalajara 2026 (confirmado, sin DAP)"},
        **{k: {"type": "none", "source": "Código Fiscal CDMX (confirmado, sin DAP)"} for k in _CDMX_KEYS},
        "Morelia|Michoacán de Ocampo": {"type": "flat_mxn_month", "amount_mxn": 25.00,
                                        "source": "Ley de Ingresos Morelia 2026, Art. 18"},
        "San Miguel de Allende|Guanajuato": {"type": "pct_of_energy_cost_capped", "pct": 0.12,
                                            "cap_mxn_month": 1111.09,
                                            "source": "Ley de Ingresos SMA 2026, Arts. 32/56"},
        "Mérida|Yucatán": {"type": "pct_of_energy_cost", "pct": 0.05,
                          "source": ("Ley de Ingresos Mérida 2026, Arts. 104-109 — tope legal; el monto "
                                     "real es per-cápita y probablemente menor, no reproducible sin el "
                                     "padrón de usuarios de CFE. Se usa el tope como aproximación conservadora.")},
        # Monterrey: sin confirmar (no se localizó la Ley de Ingresos estatal 2026 de NL) — sin
        # entrada = no se aplica DAP para este municipio hasta tener el dato real.
    },
}

# --- Lista semilla curada de centros comerciales (candidatos greenfield) ---
# name, lat, lon, metro. Ampliable / reemplazable por CSV.
SEED_MALLS = [
    # Monterrey
    {"name": "Galerías Valle Oriente", "lat": 25.6250, "lon": -100.3080, "metro": "Monterrey"},
    {"name": "Paseo San Pedro", "lat": 25.6560, "lon": -100.4020, "metro": "Monterrey"},
    {"name": "Plaza Fiesta San Agustín", "lat": 25.6510, "lon": -100.3560, "metro": "Monterrey"},
    {"name": "Nuevo Sur", "lat": 25.6080, "lon": -100.2960, "metro": "Monterrey"},
    {"name": "Punto Valle", "lat": 25.6430, "lon": -100.3620, "metro": "Monterrey"},
    {"name": "Esfera City Center", "lat": 25.6710, "lon": -100.3720, "metro": "Monterrey"},
    {"name": "Galerías Monterrey", "lat": 25.6890, "lon": -100.3350, "metro": "Monterrey"},
    {"name": "Plaza Real Cumbres", "lat": 25.7370, "lon": -100.3900, "metro": "Monterrey"},
    # Guadalajara
    {"name": "Andares", "lat": 20.7090, "lon": -103.4160, "metro": "Guadalajara"},
    {"name": "La Gran Plaza", "lat": 20.6720, "lon": -103.4020, "metro": "Guadalajara"},
    {"name": "Galerías Guadalajara", "lat": 20.7050, "lon": -103.3890, "metro": "Guadalajara"},
    {"name": "Plaza del Sol", "lat": 20.6480, "lon": -103.4090, "metro": "Guadalajara"},
    {"name": "Punto Sur", "lat": 20.5330, "lon": -103.4360, "metro": "Guadalajara"},
    {"name": "Midtown Jalisco", "lat": 20.6960, "lon": -103.3760, "metro": "Guadalajara"},
    {"name": "Plaza Patria", "lat": 20.6960, "lon": -103.3660, "metro": "Guadalajara"},
    # CDMX
    {"name": "Antara Polanco", "lat": 19.4400, "lon": -99.2050, "metro": "CDMX"},
    {"name": "Centro Santa Fe", "lat": 19.3600, "lon": -99.2600, "metro": "CDMX"},
    {"name": "Perisur", "lat": 19.3030, "lon": -99.1900, "metro": "CDMX"},
    {"name": "Plaza Satélite", "lat": 19.5090, "lon": -99.2360, "metro": "CDMX"},
    {"name": "Parque Toreo", "lat": 19.4560, "lon": -99.2200, "metro": "CDMX"},
]
