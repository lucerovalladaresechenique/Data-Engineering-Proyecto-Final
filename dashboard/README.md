# Dashboard de Asistencia de Personal

Sesión 5 · Python Certified Data Engineer · BSG Institute

Dashboard en Streamlit que consume las tablas de la capa **gold** de tu
pipeline de asistencia (mismo proyecto GCP: `proyecto-final-505619`,
mismo bucket `proyecto-final-505619-asistencia`, dataset `gold`):

- **KPIs generales**: % asistencia, % faltas, % tardanzas, horas trabajadas
  promedio, horas extra totales
- **Ranking de faltas por empleado**
- **Tendencia diaria/mensual de asistencia**
- **Ausentismo por tipo de permiso** (vacaciones, licencias, etc.)
- **Filtros**: rango de fechas y área

Reutiliza el mismo patrón de arquitectura que te dio el profesor
(Service Layer + Decorator de caché + Dataclasses + componentes
modulares + Docker en `ops/`), adaptado a leer BigQuery en vez de yfinance.

---

## Schema de datos (gold)

Star schema confirmado:

| Tabla | Columnas | Grano |
|---|---|---|
| `dim_empleado` | `empleado_id`, `empleado_codigo`, `empleado_nombre`, `area` | 1 fila por empleado |
| `dim_turno` | `turno_nombre`, `hora_inicio`, `hora_fin`, `es_nocturno` | catálogo (no vinculada aún — sin FK a fact) |
| `fact_asistencia_diaria` | `empleado_id`, `fecha`, `hora_entrada`, `hora_salida`, `horas_trabajadas`, `horas_extra`, `horas_nocturnas`, `tardanza_minutos`, `tipo_dia` | 1 fila por día esperado por empleado (incluye ausentes con nulls) |
| `fact_ausentismo` | `empleado_codigo`, `empleado_nombre`, `tipo_ausencia`, `fecha_inicio`, `fecha_fin`, `dias_ausencia` | 1 fila por evento de permiso |

**Lógica clave:**
- El estado de asistencia (Normal / Falta / Tardanza) viene **ya calculado**
  en `fact_asistencia_diaria.tipo_dia` — no se recalcula en la app.
- `% asistencia` = (Normal + Tardanza) / total de días esperados.
- El desglose de ausentismo (`fact_ausentismo`) se une a `dim_empleado`
  por `empleado_codigo`. **Ojo:** según tu `dq_rules.md`, este cruce
  tiene ~40% de match real entre sistemas — el dashboard lo advierte
  como cifra referencial, no exacta.
- `dim_turno` no se usa todavía (no tiene FK directa a
  `fact_asistencia_diaria` en el schema actual). Si en algún momento
  agregas un `turno_nombre` o `turno_id` a `fact_asistencia_diaria`,
  avísame y agrego el JOIN para mostrar métricas por turno.

Si algo de esto no coincide exactamente con tu tabla real, ajusta los
nombres en `.env` (copiando `.env.example`) — están centralizados en
`app/config/settings.py`.

---

## Instalación local

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# editar .env con tus valores reales

export GOOGLE_APPLICATION_CREDENTIALS=/ruta/a/tu/service-account-key.json
python run.py
```

Abre http://localhost:8501

## Modo offline (sin BigQuery)

Si quieres probar la UI sin conexión a GCP, usa el fallback a Parquet:

```bash
# en .env
DATA_SOURCE=parquet
LOCAL_PARQUET_GLOB=data/gold/fact_asistencia_diaria*.parquet
LOCAL_PARQUET_AUSENTISMO_GLOB=data/gold/fact_ausentismo*.parquet
```

Descarga los Parquet de gold desde GCS:

```bash
mkdir -p data/gold
gsutil cp gs://proyecto-final-505619-asistencia/gold/fact_asistencia_diaria*.parquet data/gold/
gsutil cp gs://proyecto-final-505619-asistencia/gold/fact_ausentismo*.parquet data/gold/
gsutil cp gs://proyecto-final-505619-asistencia/gold/dim_empleado*.parquet data/gold/
```

(Si tus Parquet de `fact_asistencia_diaria` no traen ya `empleado_nombre`
y `area` denormalizados, el servicio los une automáticamente con
`dim_empleado*.parquet` en la misma carpeta.)

## Docker

```bash
docker build -f ops/Dockerfile -t asistencia-dashboard .
docker run -p 8501:8501 --env-file .env \
  -v /ruta/a/key.json:/secrets/gcp-key.json:ro \
  -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp-key.json \
  asistencia-dashboard
```

O con docker-compose:

```bash
cd ops
GOOGLE_APPLICATION_CREDENTIALS_HOST=/ruta/a/key.json docker compose up --build
```

## Tests

```bash
pytest tests/ -v
```

Los tests corren contra el fallback de Parquet con datos de ejemplo del
schema real (no requieren credenciales GCP).

---

## Estructura del proyecto

```
app/
  components/       # UI modular: sidebar, metrics, charts
  config/           # Settings (Singleton) — nombres de tabla GCP
  services/         # Service Layer: AttendanceDataService, cache decorator
  main.py           # Entry point Streamlit
ops/
  Dockerfile
  docker-compose.yml
tests/
  test_attendance_data.py
```

## Patrones de diseño

| Patrón | Dónde | Beneficio |
|---|---|---|
| Service Layer | `AttendanceDataService` | Desacopla UI de BigQuery/Parquet |
| Decorator | `@cached` | La función no sabe que está cacheada |
| Singleton | `get_settings()` | Fuente única de config |
| Dataclass | `AttendanceKPIs`, `RankingFaltasRow`, `TendenciaRow`, `AusentismoTipoRow` | Contratos de datos tipados |
| Retry | `@retry` (tenacity) sobre `_run_query` | Resiliencia ante fallos transitorios de BigQuery |
