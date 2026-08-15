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

## Nota de implementación (API GeoVictoria)
`metodo_captura` (huella/rostro) queda `NULL` para las marcas provenientes de la API,
porque `AttendanceBook` (autenticación Token) no expone ese dato — solo lo entrega
`Punch/ListPendingCheckPoint` vía OAuth 1.0. Si el proyecto requiere reportar el método
de captura, se debe migrar ese extractor a OAuth 1.0.

## Notas de implementación (archivos reales)

**Cruce de medianoche en marcaciones (Excel):** en el export real, un turno nocturno
(ej. entra 20:07, sale 09:00 al día siguiente) queda registrado bajo una sola `Fecha`.
Al combinar hora + fecha ingenuamente, la marca de salida queda con timestamp ANTERIOR
a la de entrada. Regla DQ agregada:
- Si `timestamp_marca` de una salida (secuencia par) es menor que el `timestamp_marca`
  de la entrada correspondiente (secuencia impar previa) del mismo `empleado_id`+`fecha`,
  sumar 1 día a la salida antes de calcular horas trabajadas/nocturnas.

**Tipos de permiso reales (20 valores):** el Excel de permisos no usa las 3 categorías
simples (vacaciones/suspension/licencia) sino 20 valores textuales de GeoVictoria
(ej. "Descansos Vacacionales", "Licencia sin Goce de Haber", "Subsidio por Accidente",
"Permiso: Cuidarte es primero"). Se guardan tal cual en `bronze_permisos.tipo_permiso`;
la clasificación a las 4 categorías de negocio (vacaciones/licencia/suspension/
capacitacion) se hace en Silver con la tabla de mapeo definida en
`src/transform/transformer.py` (TIPO_PERMISO_MAP).

**Solo "Solicitud aprobada" excusa una falta.** Los estados "rechazada por administrador",
"rechazada por jefe" y "esperando autorizacion final" NO deben usarse para justificar
ausencias en `silver_ausencias` — solo pasan a Silver los registros con
`estado_solicitud == "Solicitud aprobada"`.

## Limitación conocida: cruce empleado_id vs. empleado_codigo (Gold)
`silver_ausencias` (Excel de permisos) identifica al empleado por nombre+código (RUT);
`silver_marcaciones_excel`/`silver_turnos` (GeoVictoria) usan el `Identifier` numérico.
No existe llave común directa. `gold_transformer.py` cruza por nombre normalizado
(mayúsculas, sin tildes, espacios colapsados) como solución provisional — es sensible
a diferencias de orden de apellidos o tildes, e infla el conteo de "falta" en
`fact_asistencia_diaria` cuando el cruce no calza. Solución recomendada pendiente:
traer el catálogo real de empleados vía el método `User/List` de la API GeoVictoria
(requiere autenticación OAuth 1.0, no implementada aún) para un cruce confiable por
`Identifier`.
