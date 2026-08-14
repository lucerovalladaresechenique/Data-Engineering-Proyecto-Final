# Architecture Decision Record (Registro de Decisiones de Arquitectura).

## ¿Qué debe contener un ADR?
Cada archivo dentro de esta carpeta suele seguir una estructura estándar:

- **Título:** La decisión breve (ej. "Uso de BigQuery para el Data Warehouse").
- **Contexto:** Qué problema estamos resolviendo y qué opciones había.
- **Decisión:** Cuál fue la opción elegida.
- **Status:** Si la decisión es "Propuesta", "Aceptada", "Superada" (por otra decisión posterior) o "Rechazada".
- **Consecuencias:** Qué ganamos y qué perdemos con esta elección (los trade-offs).

## ¿Por qué es útil esta estructura?
Los ADRs son clave por lo siguiente:
- **Justificación de Proveedor (0001-provider-selection.md):** Explica por qué eligieron GCP o AWS o Azure (considerando que tienes carpetas para los tres en infra/).
- **Modelo de Datos (0002-data-model.md):** Explica por qué se diseñó el esquema de las capas Bronze, Silver y Gold de esa manera específica.

## Nota: El uso de números (0001, 0002) es una convención para mantener el orden cronológico de las decisiones a medida que el proyecto evoluciona.