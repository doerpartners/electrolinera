# EV Siting MX — Recomendador de ubicaciones para cargadores EV

Demo local que sugiere **dónde instalar bloques de 6 estaciones de carga** para
autos eléctricos en México (foco: Monterrey y Guadalajara), y que responde la
pregunta de la app móvil: **"¿aquí es una buena ubicación?"** con estadísticas
locales y a 5 km a la redonda.

Corre **sin dependencias externas** (solo Python 3 estándar + `openpyxl` para el ETL)
y expone una **API JSON** lista para embeberse en una app móvil.

---

## 1. Cómo correr

```bash
cd ev-siting-demo
python3 run.py            # corre ETL si hace falta y levanta el server en :8000
# abre http://127.0.0.1:8000
```

Puerto alterno: `python3 run.py 8077`.
Si openpyxl no está: `pip install openpyxl`.

Reconstruir datos (cuando lleguen archivos nuevos a `~/Downloads`):

```bash
python3 etl/build_dataset.py
```

---

## 1.b La interfaz (5 pestañas)

Abre `http://127.0.0.1:8000` — el mapa vive a la derecha; el panel izquierdo tiene:

- **Explorar** — clic en el mapa = *"¿aquí es buena ubicación?"*. Toggles de **Cargadores** y **Capa NSE**.
- **Candidatos** — top 15 de ubicaciones sugeridas (sitios Tesla, malls sin carga, huecos de demanda); clic para evaluar.
- **Insights** — dashboard del mercado (ICCT/AMIA/INEGI): EV share, precios, adopción por estado y **armadora × NSE**.
- **Ajustes** — sliders de **pesos del scoring** (se aplican en vivo) y administración de la **capa NSE** (tabla + recarga + cómo cargar datos oficiales).
- **Ayuda** — guía de uso y de la API dentro de la app.

## 1.c Cargar polígonos NSE oficiales (INEGI/AMAI)

```bash
# desde shapefile -> GeoJSON (o usa mapshaper.org)
ogr2ogr -f GeoJSON zonas.geojson zonas.shp
# normalizar al esquema del sistema (--append para sumar a los existentes)
python3 etl/load_nse.py zonas.geojson
```
Luego, en la pestaña **Ajustes**, pulsa **Recargar NSE** (o `GET /api/nse/reload`).
El cargador mapea campos comunes (`NOMGEO`, `ESTRATO`, `NSE`, `AMAI`…), soporta
Polygon/MultiPolygon e infiere metro por centroide.

## 1.d Agregar información de campo (levantamientos)

Mecanismo validado y **extensible** para datos que **no** vienen de scrapers: un
observador reporta un sitio con zonas (sótanos, corporativo/comercial), marcas por
cargador, estado (**operativo / planeado / fuera de servicio**), vehículos vistos
cargando, **cajones de estacionamiento** (`parking_spaces`) y **EVs observados**
en el lote (`ev_observed`) — estos dos como *dato duro / ground truth*.

Reglas clave:
- Solo los cargadores **operativos** cuentan como oferta. Un sitio con carga
  descompuesta, planeada o inexistente **no infla la oferta** y se vuelve **candidato**
  automáticamente (`kind: field_gap`).
- `parking_spaces` y `ev_observed` se reportan como datos reales junto a las
  estimaciones del modelo, y `parking_spaces` refuerza el ancla comercial del sitio.

Tres vías (todas validan contra el mismo esquema de `app/observations.py`):

- **UI** → pestaña **Agregar**: formulario guiado con zonas dinámicas; botón *Ejemplo Samara*; fija coordenadas con clic en el mapa.
- **API** → `POST /api/observations` con el JSON de la observación (422 + lista de errores si es inválida).
- **CLI** → `python3 etl/add_observation.py etl/examples/samara.json`.

Las observaciones se guardan en `data/observations.json`, se **expanden a puntos**
en el índice espacial (una por zona) y el análisis por radio reporta
`field_observations`: unidades **operativas**, **planeadas**, marcas y vehículos.
Los cargadores planeados se muestran como *capacidad por venir* (no duplicar inversión).

Ejemplos incluidos en `etl/examples/`:
- **Samara** (Santa Fe): 9 operativos (Siemens/BYD/ClipperCreek/ChargeNow) + 8 planeados; vehículos: BYD, Tesla, Toyota.
- **Parque Delta** (Narvarte): ~5,000 cajones, 0 operativos, 2 fuera de servicio (anexo PGJ) → candidato prioritario.
- **Pabellón del Valle** (Del Valle): sin carga, 20 EV observados → candidato prioritario.

## 2. Fuentes de datos

| Fuente | Qué aporta |
|---|---|
| **PlugShare** (3 scrapes) | 1,267 cargadores únicos: lat/lon, conectores, kW, red, rápido/no, Tesla, amenities, reviews con tipo de vehículo. |
| **INEGI RAIAVL** | Ventas mensuales 2026 de BEV+PHEV por entidad → índice de adopción estatal. |
| **ICCT Market Spotlight 2025** | EV = 7.1% del mercado; precios (BEV MX$822k vs ICE MX$554k → EV = premium); marca→segmento; origen. |
| **AMIA Ene–Abr 2026** | Ranking de ventas híbrido+PHEV+EV por estado (NL 10.5%, JAL 8.5%). |

El ETL normaliza todo a `data/processed/*.json`. Los cargadores se **clasifican**
en `public` vs `residential` (por conector NEMA/Wall + amenities) y se marca `tesla`
(fabricante Tesla, red Tesla o conector NACS).

---

## 3. Modelo de scoring (tunable en `app/config.py`)

Score final 0–100 = suma ponderada de 5 sub-scores:

| Sub-score | Peso | Idea |
|---|---|---|
| **demand** | 0.34 | EVs estimados en el radio (escala log). |
| **gap** | 0.28 | EVs por cargador público — subatendido = bueno. |
| **ses** | 0.16 | Nivel socioeconómico (proxy). |
| **retail_anchor** | 0.12 | Cercanía a mall / dining / grocery. |
| **tesla_opportunity** | 0.10 | Sitio Tesla-only → oportunidad multi-estándar. |

**Estaciones recomendadas** = múltiplo de 6 (1–4 bloques) según demanda, brecha y NSE.

**Veredicto**: EXCELENTE ≥75 · BUENA ≥60 · MODERADA ≥45 · BAJA <45.

### Estacionamiento como factor de demanda
Cuando hay `parking_spaces` observados en el radio, el sub-score de **demanda** suma
un *potencial por estacionamiento*: `cajones × penetración_EV × rotación`
(`PARKING_DEMAND_TURNOVER`, def. 4). Así un lote de 5,000 cajones pesa más que uno
de 500 en la misma zona. Se reporta en `estimation.parking_ev_potential`.

### Business case (CapEx / OpEx / payback / ROI)
Cada evaluación calcula el caso de negocio para las estaciones recomendadas
(`app/business.py`, tunable en `config.BUSINESS_CASE`). Punto de partida:
**~MXN $4,000,000 total por bloque de 6**.

- **CapEx** (escala por estación + fijos): equipo, obra civil/eléctrica, mano de obra local, plataforma (setup), permisos/ingeniería, viáticos, contingencia.
- **OpEx anual**: **electricidad** (tarifa MXN/kWh por **código postal**/región), **renta** (escala con **NSE**), **mantenimiento** de equipos, **renta de plataforma**, **mano de obra** de operación (escala por metro), seguros/otros.
- **Costo del servicio (parametrizable)**: costo variable de proveer la carga aparte de la electricidad (comisión de pago, red/roaming, soporte), en MXN/kWh y/o MXN/sesión (`config.BUSINESS_CASE["service"]`). Reduce el margen de contribución.
- **Ingresos / rentabilidad**: energía anual × precio al usuario; la **utilización** se liga al score del sitio.

**KPI principal — Punto de equilibrio (meses):** `break_even_months = CapEx / utilidad_mensual`.
Además se calcula el **equilibrio operativo** (`operational_break_even`): sesiones/kWh
al mes para cubrir los costos fijos con el margen de contribución
(`precio − electricidad − costo_servicio`), y su % sobre el volumen proyectado.
También se reportan `payback_years` y `roi`.

**Análisis de sensibilidad (pricing óptimo):** `GET /api/sensitivity?lat=&lon=&radius=&cp=`
devuelve una matriz de punto de equilibrio (meses) variando el **precio de carga**
(filas) × **costo del servicio** (columnas), manteniendo fijos CapEx, electricidad
(por CP), renta (NSE) y utilización del sitio. En la UI se muestra como un **heatmap**
(verde ≤36m → rojo >120m/∞) con el punto operativo actual marcado, para decidir el
precio de carga óptimo por sitio de un vistazo.

Costos variables por ubicación: la electricidad se toma del **CP** (parámetro
`cp` en `/api/analyze` o el campo en la UI), la renta del **NSE** del polígono, y
la mano de obra de la **metrópoli**. Ajustables en vivo con `POST /api/business`
o en la pestaña **Ajustes**. Los candidatos muestran **CapEx y payback** por sitio.

### Nivel socioeconómico por polígonos (NSE)
El sub-score **ses** usa polígonos NSE reales vía point-in-polygon:

- `data/nse_polygons.geojson` — FeatureCollection con zonas NSE (clasificación **AMAI**: A/B, C+, C, D+, D/E) y un `ses_index` 0–1 por zona. Semilla curada para MTY/GDL/CDMX (15 zonas).
- `Engine.ses_context()` resuelve el NSE del punto con el polígono; si el punto **no** está cubierto, cae al proxy por señales locales (Tesla/rápido/retail). La respuesta indica `nse.source` = `polygon` | `signal_proxy`.
- En el mapa: botón **Capa NSE** pinta las zonas por color; los polígonos son no-interactivos (el clic evalúa el punto).
- **Reemplazable por datos oficiales**: sustituir el GeoJSON por AGEB/INEGI o NSE (AMAI) manteniendo `properties {name, metro, nse, ses_index}`. Cero cambios de lógica.

Endpoint: `GET /api/nse` devuelve el GeoJSON.

### Estimación de parque vehicular (transparente)
No existe registro vehicular geolocalizado, así que `cars_est` / `ev_est` /
`home_chargers_est` se **modelan** con supuestos explícitos (densidad urbana ×
área × penetración base × multiplicador de adopción estatal × multiplicador NSE).
Todos los supuestos viajan en la respuesta bajo `estimation.assumptions` y están
en `VEHICLE_MODEL`. **Reemplazables por datos reales** sin tocar el motor.

---

## 4. Generación de candidatos

Tres estrategias combinadas (`Engine.generate_candidates`):

1. **`tesla_upgrade`** — sitios con carga Tesla existente → candidatos para bloque multi-estándar (CCS/J-1772).
2. **`mall_gap`** — centros comerciales (lista semilla en `config.SEED_MALLS`) **sin** carga pública multi-estándar cercana (o solo Tesla).
3. **`grid_gap`** — rejilla de ~3 km sobre cada metrópoli; celdas con ≤1 cargador público = huecos de demanda.

Cada candidato se puntúa con el mismo motor, se ordena por score y se deduplica a >2 km.

---

## 5. API (para la app móvil)

Todos los endpoints devuelven JSON con `Access-Control-Allow-Origin: *`.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado. |
| GET | `/api/meta` | Totales del dataset. |
| GET | `/api/insights` | Constantes de reportes (marca→NSE, precios, carga en casa). |
| GET | `/api/nse` | Polígonos NSE (GeoJSON) para el mapa. |
| GET | `/api/config` | Pesos y parámetros vigentes. |
| GET/POST | `/api/analyze?lat=&lon=&radius=&cp=` | **"¿aquí es buena ubicación?"** (+ business case; `cp` = código postal para tarifa eléctrica) |
| GET | `/api/candidates?metro=&top=` | Sugerencias de instalación rankeadas. |
| GET | `/api/chargers?metro=` | Cargadores para el mapa. |
| GET | `/api/armadora-nse` | Cruce derivado marca → segmento/NSE/precio/carga-en-casa. |
| GET | `/api/demand` | Adopción EV+PHEV por entidad (RAIAVL). |
| POST | `/api/weights` | Ajusta los pesos del scoring en vivo (se normalizan). |
| GET | `/api/nse/reload` | Recarga los polígonos NSE desde disco. |
| GET | `/api/observations` | Lista observaciones de campo. |
| POST | `/api/observations` | Agrega una observación (valida; 422 si inválida). |
| GET | `/api/business-config` | Supuestos del business case. |
| POST | `/api/business` | Ajusta CapEx base / precio / costo de servicio / sesiones en vivo. |
| GET | `/api/sensitivity?lat=&lon=&radius=&cp=` | Matriz de equilibrio (meses) precio × costo de servicio. |

Ejemplo:

```bash
curl "http://127.0.0.1:8000/api/analyze?lat=25.625&lon=-100.308&radius=5"
```

Respuesta (extracto): `score`, `verdict`, `recommended_stations`, `subscores`,
`chargers` (público/residencial/rápido/Tesla, EV por cargador), `connector_types`,
`vehicles_seen`, `estimation` (autos/EV/carga-en-casa + supuestos), `ses_proxy`,
`nearest_chargers`, `insights` (texto en español).

---

## 6. Roadmap — alimentar insights nuevos

El sistema está diseñado para irse puliendo. Ganchos ya listos en `app/config.py`
e `insights.json`:

- **Marca ↔ NSE**: `insights.brand_ses` (tier 1–3 por marca). Ajustar con datos de ventas reales por colonia.
- **Ventas armadora ↔ NSE**: ✅ implementado en `/api/armadora-nse` y pestaña Insights (marca→segmento/NSE/precio/carga-en-casa). Afinar `brand_ses` con ventas reales por colonia.
- **Carga en casa ↔ NSE ↔ armadora**: `home_charging_propensity` por tier — hoy es un supuesto; reemplazar con encuestas/telemetría.
- **NSE real**: ✅ ya usa polígonos (`data/nse_polygons.geojson`). Ampliar/reemplazar con **AGEB/INEGI** o NSE (AMAI) oficial para cobertura completa; hoy hay 15 zonas semilla y el resto cae al proxy por señales.
- **Parque vehicular real**: reemplazar `VEHICLE_MODEL` por registro vehicular o padrón por AGEB.
- **Inventario de malls**: ampliar `SEED_MALLS` o cargar un CSV (`name,lat,lon,metro`).

Cada mejora es un cambio de datos/config, no de lógica.

---

## 7. Estructura

```
ev-siting-demo/
├── run.py                 # entrypoint
├── etl/build_dataset.py   # normaliza fuentes → data/processed/*.json
├── etl/load_nse.py        # ingiere GeoJSON NSE oficial → data/nse_polygons.geojson
├── etl/add_observation.py # valida y guarda un levantamiento de campo (JSON)
├── etl/examples/samara.json   # observación de ejemplo
├── app/observations.py    # esquema + validación + expansión de levantamientos
├── app/
│   ├── config.py          # pesos, umbrales, metros, malls semilla, modelo vehicular
│   ├── geo.py             # haversine + índice espacial
│   ├── scoring.py         # motor: analyze_point() y generate_candidates()
│   ├── business.py        # business case: CapEx/OpEx/ingresos/payback/ROI
│   ├── observations.py    # levantamientos de campo (esquema + validación)
│   └── server.py          # API JSON + estáticos (stdlib, sin deps)
├── web/                   # frontend: mapa Leaflet + UI de 5 pestañas
├── data/nse_polygons.geojson  # zonas NSE (semilla; reemplazable por oficial)
└── data/processed/        # JSON generado por el ETL
```
