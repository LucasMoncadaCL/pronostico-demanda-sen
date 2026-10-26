# Demostración pública del dashboard

Preparé esta aplicación para demostrar la estructura de cuatro vistas del explorador. Los ejemplos sintéticos deterministas se generan en `data_access.py`; la aplicación no carga archivos de `data/`, no importa código de entrenamiento ni consulta la API del CEN.

Las fechas, valores, perfiles y métricas son ficticios. No representan observaciones, feriados reales, errores ni resultados del estudio de 2024–2025.

## Ejecutar

Desde la raíz:

```powershell
uv sync --locked --extra dashboard
uv run --locked streamlit run dashboard/app.py
```
