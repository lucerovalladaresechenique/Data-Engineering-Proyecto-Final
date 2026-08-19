# Manual de Usuario — Proyecto de Control de Asistencia (GeoVictoria)

Guía para ejecutar y verificar el proyecto en una máquina Linux con Docker.
No requiere credenciales de GCP para la prueba básica — corre en modo local
usando los datos de ejemplo incluidos.

---

## Requisitos previos

- Docker instalado y corriendo (`docker --version` debe responder).
- ~500 MB libres en disco (imagen + datos de prueba).

No se necesita Python instalado en la máquina host — todo corre dentro del
contenedor.

## Contenido del proyecto

```
Proyecto_Lucero/
├── Dockerfile
├── run_daily.py              ← punto de entrada usado por Docker
├── run_pipeline.py / run_gold_pipeline.py   ← para correr sin Docker (opcional)
├── requirements.txt
├── data_samples/              ← Excel de ejemplo (ya incluidos)
│   ├── HistorialdeSolicitudes.xlsx
│   └── Marcaciones_GeoVictoria.xlsx
├── empleados.txt              ← lista de IDs para consultar la API (opcional)
├── src/                       ← código del pipeline
└── architecture/              ← documentación de arquitectura y decisiones
```

## Prueba rápida (recomendada) — Docker en modo local

No requiere ningún archivo `.env` ni credenciales. Guarda los resultados en
una carpeta `out/` dentro del proyecto.


  ### Paso 1: Abrir consola PowerShell y navegar hasta la carpeta del proyecto
  ```bash
  cd (Ruta del proyecto )
  ```

  ### Paso 2:. Ejecutar comando para construir la imagen
  ```bash
  docker build -t asistencia-etl .
  ```
  ### Paso3: Ejecutar comando para ejecutar el pipeline completo (Bronze -> Silver -> Gold) para un día
  ```bash
  docker run --rm -e CLOUD_PROVIDER=local -e OUTPUT_DIR=/app/out -e FECHA=2026-06-01 -e ARCHIVO_MARCACIONES=/app/data_samples/Marcaciones_GeoVictoria.xlsx -e ARCHIVO_PERMISOS=/app/data_samples/HistorialdeSolicitudes.xlsx -v ${PWD}/out:/app/out asistencia-etl
  ```
  #### Nota:
    **Tiempo esperado:** 2-5 minutos (procesa ~250,000 marcas y ~1,500 solicitudes
    de permiso reales).

  #### Qué debería pasar

    En la terminal se ven logs estructurados por etapa:
    ```
    === Ejecución automatizada — fecha: 2026-06-01 | ... empleados ===
    ✓ Bronze aterrizado: [...]
    === Transformación completa === {...}
    === Pipeline completo === stats={...}
    === Pipeline Gold completo === stats={...}
    === Ejecución automatizada completa ===
    ```

    Si termina sin ninguna línea `Traceback` ni `Error`, la ejecución fue exitosa.

  ### Paso 4: Ejecutar comando para verificar los resultados

  Linux:
  ```bash
  find out/ -name "*.parquet" 
  ```
  Windows:
  ```bash
  Get-ChildItem -Recurse out\*.parquet
  ```

  #### Debería listar archivos en 3 capas:
    
    ```
    out/bronze/bronze_permisos/ingestion_date=2026-06-01/data.parquet
    out/bronze/bronze_marcaciones_excel/ingestion_date=2026-06-01/data.parquet
    out/silver/silver_permisos.../data.parquet
    out/silver/silver_marcaciones_excel/.../data.parquet
    out/gold/fact_asistencia_diaria/ingestion_date=2026-06-01/data.parquet
    out/gold/fact_ausentismo/.../data.parquet
    out/gold/dim_empleado/.../data.parquet
    out/gold/dim_turno/.../data.parquet   (abriendo el archivo se encontrará 0 filas: no se consultó la API en esta prueba, ver sección 6)
    ```

  #### Inspeccionar el contenido (opcional, requiere Python + pandas)

  Linux:

    ```bash
    python3 -c "
    import pandas as pd
    df = pd.read_parquet('out/gold/fact_asistencia_diaria/ingestion_date=2026-06-01/data.parquet')
    print(df.shape)
    print(df.head())
    print(df['tipo_dia'].value_counts())
    "
    ```

  Windows:

    ```bash
    python -c "
    import pandas as pd
    df = pd.read_parquet('out/gold/fact_asistencia_diaria/ingestion_date=2026-06-01/data.parquet')
    print(df.shape)
    print(df.head())
    print(df['tipo_dia'].value_counts())
    "
    ```
    

  ## Proceso Alternativo. Ingresar comandos para ejecutar pipeline sin Docker desde vs code.

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```
  ```bash
  python3 list_empleados.py data_samples/Marcaciones_GeoVictoria.xlsx  # genera empleados.txt
  ```
  ```bash
  python3 run_pipeline.py --fecha-inicio 2026-06-01 --fecha-fin 2026-06-30 \
      --empleados-file empleados.txt \
      --archivo-permisos data_samples/HistorialdeSolicitudes.xlsx \
      --archivo-marcaciones data_samples/Marcaciones_GeoVictoria.xlsx
  ```
  ```bash
  python3 run_gold_pipeline.py --fecha 2026-06-01
  ```

## Sobre la parte de API y la nube (GCP)

Esta prueba local **no incluye** la extracción vía API de GeoVictoria (por
eso `dim_turno` sale vacío) ni la carga real a Google Cloud Storage/BigQuery,
porque ambas requieren credenciales propias del proyecto (API Key/Secreto de
GeoVictoria, cuenta de servicio de GCP) que no se comparten en esta entrega
por seguridad.

Esa parte del proyecto — Cloud Run Job + Cloud Scheduler + Secret Manager +
BigQuery — está documentada y demostrada en el video de entrega, y el código
completo (`src/extract/api_extractor.py`, `src/load/gcp_loader.py`,
`src/load/bq_loader.py`) está disponible para revisión en el repositorio,
aunque no se ejecute en esta prueba local.

## Documentación de referencia

- `README.md` — resumen técnico completo, decisiones y limitaciones conocidas
- `architecture/architecture.md` — arquitectura y diagrama
- `architecture/0001-provider-selection.md`, `0002-data-model.md` — ADRs
- `architecture/dq_rules.md` — reglas de calidad de datos, incluyendo el
  hallazgo cuantificado sobre el cruce de nombres (limitación conocida)

## Problemas comunes

| Síntoma | Causa probable |
|---|---|
| `docker: command not found` | Docker no está instalado en la máquina |
| Error de permisos al montar `-v $(pwd)/out` | Correr con `sudo`, o ajustar permisos de la carpeta `out/` |
| El contenedor tarda mucho sin salida | Normal — procesa ~250K registros; no está colgado, dar tiempo |
| `ValueError: Worksheet named ... not found` | Los archivos en `data_samples/` no deben renombrarse ni moverse |
