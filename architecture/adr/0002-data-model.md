# 0002 - Modelo de datos (Bronze / Silver / Gold)

## Título
Diseño del modelo de datos por capas para el control de asistencia (GeoVictoria).

## Contexto
Existen 4 fuentes heterogéneas, todas provenientes de GeoVictoria pero en formatos distintos:
1. **API** — marcaciones biométricas (huella/rostro) en línea: entrada, salida, inicio/fin de refrigerio.
2. **Texto plano** — export histórico/batch de marcaciones del mismo reloj biométrico.
3. **CSV** — turnos asignados por empleado.
4. **Excel** — maestro de empleados y permisos (vacaciones, suspensiones, licencias), mantenido manualmente por RRHH.

El pipeline debe producir métricas de negocio: horas trabajadas, horas extra, horas nocturnas, tardanzas y faltas — cruzando marcas reales contra el turno asignado y contra los permisos/ausencias justificadas.

## Decisión

**Bronze (una tabla/prefijo por fuente, sin transformar):**
- `bronze_marcaciones_api`
- `bronze_marcaciones_txt`
- `bronze_turnos`
- `bronze_empleados_permisos`

**Silver (conformado, deduplicado, tipado, en UTC):**
- `silver_marcaciones` — unifica API + texto plano en un solo esquema, con `fuente` como columna de linaje.
- `silver_turnos` — turno asignado por empleado/fecha, con flag `es_turno_nocturno` derivado.
- `silver_ausencias` — permisos/vacaciones/licencias/suspensiones normalizados.

**Gold (listo para consumo):**
- `fact_asistencia_diaria` — grano: 1 fila por empleado por día. Contiene horas trabajadas, horas extra, horas nocturnas, tardanza en minutos y clasificación del día (normal / falta / ausencia justificada).
- `fact_ausentismo` — grano: 1 fila por empleado por periodo de ausencia.
- `dim_empleado`, `dim_turno` — dimensiones de soporte.

La deduplicación de marcas usa la llave `(empleado_id, timestamp_marca, tipo_marca)`. La clasificación de "falta" vs "ausencia justificada" se resuelve en Transform cruzando `silver_marcaciones` contra `silver_ausencias` antes de escribir a Gold — nunca se marca una falta sin antes verificar que no exista un permiso vigente.

## Status
Aceptada.

## Consecuencias
**Ganamos:**
- Al separar `silver_marcaciones` (unificando API+texto plano) del resto, el resto del pipeline no necesita saber de dónde vino cada marca.
- El cruce contra `silver_ausencias` antes de clasificar faltas evita el riesgo principal identificado en `architecture.md` (falsas faltas por fallo biométrico).

**Perdemos / trade-offs:**
- Unificar dos formatos de marcación (API y texto plano) en `silver_marcaciones` implica mantener dos parsers distintos en Transform, aunque el esquema de salida sea el mismo.
- El esquema de Gold depende de que `silver_turnos` esté siempre actualizado antes de calcular horas extra/nocturnas del día — si el CSV de turnos llega tarde, esa fecha debe reprocesarse (ver `dq_rules.md`).
