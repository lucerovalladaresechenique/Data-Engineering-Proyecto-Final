# 0001 - Selección de proveedor cloud

## Título
Uso de Google Cloud Platform (GCP) como proveedor principal de implementación.

## Contexto
El proyecto sigue un enfoque vendor-agnostic: una sola arquitectura lógica (Sources → Extract → Bronze → Transform → Silver → Gold), con una implementación de referencia en un solo proveedor y equivalencias conceptuales documentadas para AWS y Azure (de ahí `requirements-aws.txt` y `requirements-azure.txt` en el repo, mantenidos como referencia pero no ejecutados).

Opciones evaluadas:
- **AWS:** Lambda/ECS, S3, Glue/EMR, Athena/Redshift, Step Functions.
- **GCP:** Cloud Run/Functions, GCS, Dataflow/Dataproc, BigQuery, Composer.
- **Azure:** Azure Functions, ADLS Gen2, Synapse/Databricks, ADF.

Criterios: curva de aprendizaje del equipo, calidad de BigQuery para analítica serving, costo en tier gratuito para un proyecto académico, y disponibilidad de Cloud Run para jobs de ingesta ligeros (extracción de API + archivos).

## Decisión
Se elige **GCP** como proveedor de implementación de referencia:
- Ingesta: Cloud Run Jobs
- Raw/Bronze y Curated/Silver: Cloud Storage (Parquet)
- Transform: Dataflow (o Dataproc si se requiere Spark)
- Serving/Gold: BigQuery
- Orquestación: Cloud Composer
- Observabilidad: Cloud Monitoring + Cloud Logging

## Status
Aceptada.

## Consecuencias
**Ganamos:**
- BigQuery simplifica la capa Gold para analítica ad-hoc sin gestionar infraestructura de cómputo.
- Cloud Run Jobs es ligero y barato para extractores batch (API + archivos).
- Buena integración nativa entre GCS, Dataflow y BigQuery (menos "pegamento" custom).

**Perdemos / trade-offs:**
- Portar el pipeline a AWS o Azure requeriría reescribir los adaptadores de ingesta y el paso a BigQuery (no es 100% plug-and-play a pesar del diseño vendor-agnostic).
- Dataflow tiene una curva de aprendizaje mayor que un simple script Python si el volumen de datos no la justifica (para este proyecto, el volumen es bajo, por lo que se evalúa como alternativa un job Python simple sobre Cloud Run en vez de Dataflow — ver notas de implementación en `src/`).
