# Reglas de Calidad de Datos (DQ)

Cada regla se evalúa en Transform (Bronze → Silver, o Silver → Gold según corresponda) y se registra en `gold.dq_results` con `run_id`, `regla`, `dataset`, `filas_evaluadas`, `filas_fallidas`, `estado`.

## Bronze → Silver

| Regla | Dataset | Descripción | Acción si falla |
|---|---|---|---|
| Completitud de llave | marcaciones (api/txt) | `empleado_id`, `timestamp_marca`, `tipo_marca` no nulos | Fila va a `bronze/_quarantine/` |
| Unicidad de marca | silver_marcaciones | No duplicar `(empleado_id, timestamp_marca, tipo_marca)` | Deduplicar, conservar el registro más reciente por `ingestion_date` |
| Rango de fecha | marcaciones (api/txt) | `timestamp_marca` no puede ser futuro ni anterior a la fecha de contratación del empleado | Marcar como sospechosa, no descartar automáticamente |
| Tipo de marca válido | marcaciones (api/txt) | `tipo_marca` ∈ {entrada, salida, inicio_refrigerio, fin_refrigerio} | Fila va a cuarentena |
| Empleado existe | todas las fuentes | `empleado_id` debe existir en `bronze_empleados_permisos` | Alertar; no bloquea el pipeline pero se marca `empleado_no_encontrado=true` |
| Esquema del Excel | bronze_empleados_permisos | Columnas obligatorias presentes y tipadas según `data_contracts/bronze_schema.json` | Rechazar el archivo completo, alertar a RRHH |
| Turno único por día | bronze_turnos | Un empleado no puede tener dos turnos activos el mismo `fecha` | Fila va a cuarentena, se usa el último turno recibido mientras se resuelve |

## Silver → Gold

| Regla | Dataset | Descripción | Acción si falla |
|---|---|---|---|
| Marca con turno asociado | fact_asistencia_diaria | Toda marca debe cruzar con un `silver_turnos` para ese empleado/fecha | Si no hay turno, se excluye del cálculo de horas extra/nocturnas y se reporta como excepción |
| Falta vs. ausencia justificada | fact_asistencia_diaria | Antes de marcar "falta", verificar que no exista un registro vigente en `silver_ausencias` | Reclasificar como "ausencia justificada" si aplica |
| Horas trabajadas no negativas | fact_asistencia_diaria | `hora_salida - hora_entrada >= 0` | Fila va a cuarentena, requiere revisión manual (posible marca faltante) |
| Consistencia de ausencias | fact_ausentismo | `fecha_inicio <= fecha_fin` en cada periodo de ausencia | Rechazar registro, alertar a RRHH |

## Ventana de reproceso (backfill)
Si `silver_turnos` o `silver_ausencias` se actualizan después de que Gold ya calculó una fecha, esa fecha entra a una cola de reproceso automático (máx. 7 días hacia atrás) para recalcular `fact_asistencia_diaria`.
