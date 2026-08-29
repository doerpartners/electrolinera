"""
Configuración tunable del sistema de recomendación.
Todo lo que aquí vive puede ajustarse conforme se alimenten insights nuevos,
sin tocar la lógica del motor de scoring.
"""

# --- Radio de análisis por defecto (la app móvil pregunta "a la redonda") ---
DEFAULT_RADIUS_KM = 5.0

# --- Sitios de carga a recomendar según demanda (cada sitio = hub de 360kW) ---
MAX_BLOCKS = 4  # hasta 4 sitios por ubicación

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
# Modelo por sitio (hub de 360kW), a 9 años — vida media asumida de un cargador EV.
# Fuente: modelo de negocios del proveedor (Excel "Modelo de Negocios", 9 años).
BUSINESS_CASE = {
    "currency": "USD",
    "horizon_years": 9,
    "site_capex_usd": 250_000,   # transformador + cargador + cable + instalación, por sitio
    "site_capacity_kw": 360,
    # Utilización esperada año 1..9 (curva del proveedor; meseta desde año 7).
    "utilization_by_year": [0.23, 0.26, 0.28, 0.32, 0.35, 0.38, 0.40, 0.40, 0.40],
    "util_floor": 0.30,   # piso: multiplica la curva de arriba según el score del sitio (no viene del Excel)
    "peak_hours_per_day": 12.5,
    "offpeak_hours_per_day": 11.5,
    "price_per_kwh_user": 0.46,               # mismo precio en horario punta y valle (así viene calculado en la fuente)
    "electricity_cost_peak_per_kwh": 0.17,
    "electricity_cost_offpeak_per_kwh": 0.15,
    "electrical_loss_ratio": 0.10,             # pérdida eléctrica aplicada a ambos costos
    "payment_gateway_pct": 0.0,                # sin costo de pasarela de pago modelado (igual que la fuente)
    "maintenance_pct": 0.10,                   # % de facturación
    "platform_pct": 0.13,                      # % de facturación
    "landlord_profit_share": 0.16,             # resto (84%) es del inversionista
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
