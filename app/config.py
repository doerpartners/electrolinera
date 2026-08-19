"""
Configuración tunable del sistema de recomendación.
Todo lo que aquí vive puede ajustarse conforme se alimenten insights nuevos,
sin tocar la lógica del motor de scoring.
"""

# --- Radio de análisis por defecto (la app móvil pregunta "a la redonda") ---
DEFAULT_RADIUS_KM = 5.0

# --- Múltiplos de estaciones a recomendar según demanda ---
STATION_BLOCK = 6
MAX_BLOCKS = 4  # hasta 24 estaciones

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
}

# --- Business case: costos, ingresos y payback (todo tunable) ---
# Punto de partida: costo total promedio de ~MXN $4,000,000 para un bloque de 6.
BUSINESS_CASE = {
    "currency": "MXN",
    "reference_total_capex": 4_000_000,   # costo total de referencia…
    "reference_stations": 6,              # …para 6 estaciones (punto de partida)
    # Descomposición del CapEx (shares suman 1.0). scaling: por estación o fijo por sitio.
    "capex_components": {
        "equipo_cargadores":    {"share": 0.45, "scaling": "per_station", "desc": "Hardware de cargadores"},
        "obra_civil_electrica": {"share": 0.25, "scaling": "per_station", "desc": "Obra civil, transformador, cableado"},
        "mano_de_obra_local":   {"share": 0.10, "scaling": "per_station", "desc": "Instalación (mano de obra local)"},
        "plataforma_setup":     {"share": 0.05, "scaling": "fixed",       "desc": "Integración de plataforma (setup)"},
        "permisos_ingenieria":  {"share": 0.05, "scaling": "fixed",       "desc": "Permisos e ingeniería"},
        "viaticos":             {"share": 0.04, "scaling": "fixed",       "desc": "Viáticos del equipo"},
        "contingencia":         {"share": 0.06, "scaling": "fixed",       "desc": "Contingencia"},
    },
    # OpEx (costos recurrentes)
    "opex": {
        "rent_monthly_base": 45_000,            # renta mensual por sitio (se escala por NSE)
        "maintenance_annual_per_station": 18_000,  # mantenimiento de equipos
        "platform_monthly_per_station": 1_200,  # renta de plataforma de software
        "ops_labor_annual_base": 180_000,       # mano de obra de operación (se escala por metro)
        "insurance_other_annual": 60_000,       # seguros y otros
    },
    # Ingresos (para payback / ROI / punto de equilibrio)
    "revenue": {
        "base_sessions_per_station_day": 6,     # sesiones/estación/día a utilización plena
        "util_floor": 0.30,                     # piso de utilización (sitio de bajo score)
        "kwh_per_session": 22,
        "price_per_kwh_user": 8.5,              # precio de carga al usuario (MXN/kWh)
    },
    # Costo del servicio (parametrizable): costo variable de proveer la carga,
    # aparte de la electricidad — comisión de pago, red/roaming, soporte, etc.
    # Afecta el margen de contribución y por tanto el punto de equilibrio.
    "service": {
        "cost_per_kwh": 1.0,        # MXN/kWh (variable)
        "cost_per_session": 0.0,    # MXN/sesión (variable, opcional)
    },
    # Costo de electricidad (MXN/kWh) — varía por código postal / región
    "electricity_default": 3.2,
    "electricity_by_cp2": {  # prefijo de CP (2 dígitos) → tarifa
        "64": 3.4, "65": 3.4, "66": 3.4, "67": 3.4,            # Nuevo León
        "44": 3.1, "45": 3.1, "46": 3.1, "47": 3.1,            # Jalisco
        "01": 3.6, "02": 3.6, "03": 3.6, "04": 3.6, "05": 3.6, "06": 3.6,
        "07": 3.6, "08": 3.6, "09": 3.6, "10": 3.6, "11": 3.6, "12": 3.6,
        "13": 3.6, "14": 3.6, "15": 3.6, "16": 3.6,            # CDMX
        "97": 3.3,                                             # Yucatán (Mérida)
        "58": 3.2, "59": 3.2,                                  # Michoacán (Morelia)
        "37": 3.2,                                             # Guanajuato (San Miguel Allende)
    },
    "electricity_by_metro": {"Monterrey": 3.4, "Guadalajara": 3.1, "CDMX": 3.6,
                             "Mérida": 3.3, "Morelia": 3.2, "San Miguel de Allende": 3.2},
    "labor_by_metro": {"Monterrey": 1.05, "Guadalajara": 1.00, "CDMX": 1.15,
                       "Mérida": 0.95, "Morelia": 0.95, "San Miguel de Allende": 1.00},
    "rent_ses_base": 0.60,   # renta_mult = rent_ses_base + índice_NSE (NSE alto → renta más cara)
    "horizon_years": 5,
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
