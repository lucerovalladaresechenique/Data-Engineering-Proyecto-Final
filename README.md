# Proyecto Final — Control de Asistencia (GeoVictoria → GCP)

## Resumen del problema

Pipeline de datos para **control de asistencia de personal**: consolida marcación
de entrada/salida y refrigerios, turnos asignados, horas extras, horas nocturnas,
faltas y ausencias justificadas (vacaciones, suspensiones, licencias) a partir de
GeoVictoria (reloj biométrico), integrando **API**, **Excel de marcaciones** y
**Excel de permisos** en un lakehouse GCP (Bronze → Silver → Gold).

## Arquitectura lógica

Ver `architecture/architecture.md` y el diagrama `architecture/diagrams/pipeline.mmd`.
En resumen:

```
API GeoVictoria (AttendanceBook) ─┐
Excel Marcaciones                 ├─→ Bronze (GCS) → Transform → Silver (GCS) → Gold (BigQuery)
Excel Permisos                    ─┘
```

- **Bronze** (`gs://<bucket>/bronze/`): datos crudos, sin transformar. `bronze_marcaciones_api`
  guarda el JSON completo de la API (columna `raw_json`) para máxima trazabilidad.
- **Silver** (`gs://<bucket>/silver/`): limpio, tipado, con el cruce de medianoche
  corregido y los 20 tipos de permiso mapeados a 4 categorías de negocio.
- **Gold** (BigQuery, dataset `gold`): `fact_asistencia_diaria`, `fact_ausentismo`,
  `dim_empleado`, `dim_turno`.

## Cómo ejecutar localmente

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt

# copiar .env.example a .env y completar credenciales (ver sección siguiente)

python run_pipeline.py --fecha-inicio 2026-06-01 --fecha-fin 2026-06-30 \
    --empleados-file empleados.txt \
    --archivo-permisos data_samples/HistorialdeSolicitudes.xlsx \
    --archivo-marcaciones data_samples/Marcaciones_GeoVictoria.xlsx

python run_gold_pipeline.py --fecha 2026-06-01
```

`empleados.txt` se genera una vez con:
```bash
python list_empleados.py data_samples/Marcaciones_GeoVictoria.xlsx
```

## Cómo ejecutar en GCP

Con `CLOUD_PROVIDER=gcp` en `.env`, los mismos comandos de arriba cargan
directamente a GCS (Bronze/Silver) y BigQuery (Gold) en vez de a disco local.

Configuración necesaria (una sola vez):
1. Bucket de GCS: `gsutil mb -l US-CENTRAL1 gs://<bucket>`
2. Dataset de BigQuery: `bq mk --dataset --location=US-CENTRAL1 <project_id>:gold`
3. Cuenta de servicio con roles `Storage Object Admin` (a nivel del bucket),
   `BigQuery Data Editor` y `BigQuery Job User` (a nivel de proyecto).
4. `.env`:
   ```
   CLOUD_PROVIDER=gcp
   GCP_PROJECT_ID=<tu-project-id>
   GCS_BUCKET=<tu-bucket>
   BQ_DATASET=gold
   GOOGLE_APPLICATION_CREDENTIALS=./credentials/<archivo>.json
   GEOVICTORIA_BASE_URL=https://customerapi.geovictoria.com
   GEOVICTORIA_API_KEY=<tu Clave Api>
   GEOVICTORIA_API_SECRET=<tu Secreto>
   ```

## Estructura de datos (Bronze / Silver / Gold)

Ver `data_contracts/bronze_schema.json`, `silver_schema.json`, `gold_schema.json`
para el detalle completo de campos y tipos por capa.

## Decisiones clave

- **GCP como proveedor de referencia** (BigQuery simplifica Gold, Cloud Run es
  liviano para ingesta) — ver `architecture/0001-provider-selection.md`.
- **Turnos vía API, no CSV**: `AttendanceBook` ya trae el turno asignado del día
  en la misma llamada que las marcas — se descartó el CSV planeado originalmente.
- **Corrección de cruce de medianoche**: turnos nocturnos registrados bajo una
  sola fecha en el Excel requieren sumar 1 día a la marca de salida — ver
  `architecture/dq_rules.md`.
- **Mapeo de 20 tipos de permiso a 4 categorías de negocio** (vacaciones,
  licencia, suspension, capacitacion) — definido en `src/transform/transformer.py`.
- **Batching de la API**: GeoVictoria limita a 200 usuarios y 1,500 registros
  (usuarios × días) por llamada a `AttendanceBook` — el extractor parte
  automáticamente por lotes de empleados y ventanas de fechas.

## Limitación conocida (no resuelta, documentada)

El cruce entre `silver_ausencias` (identificada por nombre+código/RUT, viene del
Excel de permisos) y `silver_marcaciones`/`silver_turnos` (identificadas por
`Identifier` numérico, vienen de GeoVictoria) se hace por **nombre normalizado**,
no por una llave real. Impacto medido con datos reales de junio 2026: solo ~40%
de los empleados con permisos cruzan correctamente, lo que probablemente infla
el 24% de "falta" reportado en `fact_asistencia_diaria` (ver detalle cuantificado
en `architecture/dq_rules.md`). Solución correcta identificada pero no
implementada por tiempo: traer el catálogo de empleados vía `User/List`
(requiere autenticación OAuth 1.0, distinta a la usada en el resto del pipeline).

## Costos y seguridad

- **Costos**: GCS y BigQuery se mantienen dentro del tier gratuito de GCP para
  los volúmenes de este proyecto (~250K marcas, ~1,500 permisos, 2,121 empleados).
- **Seguridad**: la clave de la cuenta de servicio (`credentials/*.json`) nunca
  se sube a control de versiones (`.gitignore`). El acceso a la API GeoVictoria
  usa credenciales propias (Clave Api/Secreto) distintas de las de GCP.