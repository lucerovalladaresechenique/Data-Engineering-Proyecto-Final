# Proyecto Final — Control de Asistencia (GeoVictoria → GCP)

## Resumen del problema

Pipeline de datos para **control de asistencia de personal**: consolida marcación
de entrada/salida y refrigerios, turnos asignados, horas extras, horas nocturnas,
faltas y ausencias justificadas (vacaciones, suspensiones, licencias) a partir de
GeoVictoria (reloj biométrico), integrando **API**, **Excel de marcaciones** y
**Excel de permisos** en un lakehouse GCP (Bronze → Silver → Gold), empaquetado
en Docker y automatizado con Cloud Run Job + Cloud Scheduler.

## Arquitectura lógica

Ver `architecture/architecture.md` y el diagrama `architecture/diagrams/pipeline.mmd`.
En resumen:

```
API GeoVictoria (AttendanceBook) ─┐
Excel Marcaciones (GCS)           ├─→ Bronze (GCS) → Transform → Silver (GCS) → Gold (BigQuery)
Excel Permisos (GCS)              ─┘
```

- **Bronze** (`gs://<bucket>/bronze/`): datos crudos, sin transformar. `bronze_marcaciones_api`
  guarda el JSON completo de la API (columna `raw_json`) para máxima trazabilidad.
- **Silver** (`gs://<bucket>/silver/`): limpio, tipado, con el cruce de medianoche
  corregido y los 20 tipos de permiso mapeados a 4 categorías de negocio.
- **Gold** (BigQuery, dataset `gold`): `fact_asistencia_diaria`, `fact_ausentismo`,
  `dim_empleado`, `dim_turno`.

## Empaquetado y automatización

El pipeline corre dentro de un contenedor Docker (`Dockerfile` en la raíz),
pensado para ejecutarse igual en cualquier servidor Linux con Docker — no
depende del entorno local de quien lo desarrolló.

**Cadena de automatización:**

```
Cloud Scheduler (cron diario)
    → invoca → Cloud Run Job (imagen Docker, en Artifact Registry)
        → corre run_daily.py (procesa el día anterior por defecto)
            → API GeoVictoria: 100% automática (sin intervención humana)
            → Excel: semi-automática — RRHH sube el export a
              gs://<bucket>/raw-uploads/permisos/ y raw-uploads/marcaciones/
              cuando lo tiene; el Job siempre toma el archivo MÁS RECIENTE de
              esas carpetas en cada corrida, sin que nadie indique la ruta.
```

Credenciales de GeoVictoria (`GEOVICTORIA_API_KEY`/`SECRET`) se guardan en
**Secret Manager**, no como variables de entorno en texto plano — el Job las
inyecta automáticamente al arrancar.

### Construir y desplegar la imagen

```bash
docker build -t asistencia-etl .

# Registrar en Artifact Registry
gcloud artifacts repositories create asistencia-repo --repository-format=docker --location=us-central1
gcloud auth configure-docker us-central1-docker.pkg.dev
docker tag asistencia-etl us-central1-docker.pkg.dev/<project_id>/asistencia-repo/asistencia-etl:latest
docker push us-central1-docker.pkg.dev/<project_id>/asistencia-repo/asistencia-etl:latest
```

### Secretos (una sola vez)

```bash
gcloud services enable secretmanager.googleapis.com
gcloud secrets create geovictoria-api-key --data-file=key.txt
gcloud secrets create geovictoria-api-secret --data-file=secret.txt
gcloud secrets add-iam-policy-binding geovictoria-api-key --member="serviceAccount:<sa-email>" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding geovictoria-api-secret --member="serviceAccount:<sa-email>" --role="roles/secretmanager.secretAccessor"
```

### Crear y probar el Cloud Run Job

```bash
gcloud run jobs create asistencia-etl-job \
  --image=us-central1-docker.pkg.dev/<project_id>/asistencia-repo/asistencia-etl:latest \
  --region=us-central1 \
  --service-account=<sa-email> \
  --set-env-vars="GCP_PROJECT_ID=<project_id>,GCS_BUCKET=<bucket>,BQ_DATASET=gold,GEOVICTORIA_BASE_URL=https://customerapi.geovictoria.com" \
  --set-secrets="GEOVICTORIA_API_KEY=geovictoria-api-key:latest,GEOVICTORIA_API_SECRET=geovictoria-api-secret:latest"

# Ejecutar manualmente para probar (una fecha específica)
gcloud run jobs execute asistencia-etl-job --region=us-central1 --update-env-vars=FECHA=2026-06-01
```

### Programar la ejecución diaria (Cloud Scheduler)

```bash
gcloud scheduler jobs create http asistencia-etl-scheduler \
  --schedule="0 6 * * *" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/<project_id>/jobs/asistencia-etl-job:run" \
  --http-method=POST \
  --oauth-service-account-email=<sa-email> \
  --location=us-central1
```
Esto dispara el Job todos los días a las 6:00 AM, procesando automáticamente el
día anterior (comportamiento por defecto de `run_daily.py` si no se le pasa `FECHA`).

## Cómo ejecutar localmente (sin Docker, para desarrollo)

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
pip install -r requirements.txt

# copiar .env.example a .env y completar credenciales

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

## Cómo ejecutar con Docker localmente

```bash
docker build -t asistencia-etl .

docker run --rm \
  -e CLOUD_PROVIDER=local -e OUTPUT_DIR=/app/out -e FECHA=2026-06-01 \
  -e ARCHIVO_MARCACIONES=/app/data_samples/Marcaciones_GeoVictoria.xlsx \
  -e ARCHIVO_PERMISOS=/app/data_samples/HistorialdeSolicitudes.xlsx \
  -v ${PWD}/out:/app/out \
  asistencia-etl
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
- **Docker + Cloud Run Job** en vez de una VM o script cron tradicional: mismo
  contenedor corre igual en cualquier servidor Linux (incluida la máquina de
  evaluación del profesor), y Cloud Run solo cobra por el tiempo real de
  ejecución (no hay servidor corriendo 24/7 esperando).
- **Automatización asimétrica, por diseño**: la API es 100% automatizable (no
  depende de que una persona haga algo); los Excel de RRHH no pueden serlo del
  todo porque dependen de un export manual desde GeoVictoria — se resolvió con
  una carpeta `raw-uploads/` en GCS donde el Job siempre toma el archivo más
  reciente, minimizando la intervención humana a solo "subir el archivo".
- **Credenciales en Secret Manager**, no en variables de entorno planas, para
  el Cloud Run Job.

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

- **Costos**: GCS, BigQuery y Cloud Run se mantienen dentro del tier gratuito de
  GCP para los volúmenes de este proyecto (~250K marcas, ~1,500 permisos, 2,121
  empleados, 1 ejecución diaria de pocos minutos).
- **Seguridad**:
  - La clave de la cuenta de servicio (`credentials/*.json`) nunca se sube a
    control de versiones (`.gitignore`); en Cloud Run no hace falta ni existe —
    se usa la identidad de la cuenta de servicio adjunta al Job.
  - Las credenciales de la API GeoVictoria viven en Secret Manager, inyectadas
    solo en tiempo de ejecución.
  - El bucket usa acceso uniforme a nivel de bucket (IAM), sin ACLs heredadas
    ni acceso público.