# Contribuir

Este repositorio separa el código y la documentación originales de datos oficiales de terceros. Mantén esta separación en cualquier cambio.

## Reglas

- No añadas respuestas de API, series horarias observadas, exportaciones del CEN, archivos mixtos observación-pronóstico, errores invertibles ni gráficos que expongan curvas reales.
- Usa entradas sintéticas pequeñas para pruebas. Identifícalas en el nombre, la documentación y las etiquetas visibles.
- No añadas claves API, tokens ni archivos de configuración local.
- No presentes la demostración sintética como resultados del estudio real.
- No vuelvas a ejecutar la evaluación congelada de 2025.

## Verificación

Desde la raíz, instala las dependencias necesarias con `uv sync --locked --extra dev --extra dashboard`. Ejecuta las pruebas unitarias con `uv run --locked python -m unittest discover -s tests -p 'test_*.py' -v` y revisa los cambios con `git diff --check`.

Los permisos del código y documentación están descritos en `LICENSE` y `LICENSE-DOCS.md`. No amplíes esas licencias a los datos, calendarios externos u otros materiales de terceros.
