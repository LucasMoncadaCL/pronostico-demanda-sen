# Demostración pública del dashboard

Esta aplicación reproduce la estructura de cuatro vistas del explorador original, pero se alimenta exclusivamente de ejemplos sintéticos generados por `data_access.py`. No carga archivos de `data/`, no importa código de entrenamiento y no consulta la API del CEN.

Las fechas, valores, perfiles y métricas que aparecen en pantalla son ficticios. No deben interpretarse como observaciones, feriados reales, errores ni resultados del estudio de 2024–2025.

## Ejecutar

Desde la raíz:

```powershell
uv sync --locked --extra dashboard
uv run --locked streamlit run dashboard/app.py
```
