# Pronóstico de demanda eléctrica del SEN de Chile

Proyecto aplicado de Data Science que estudia pronósticos horarios de demanda sistémica agregada para el día calendario siguiente. La investigación compara un benchmark de medias históricas por día de semana e índice de período con una regla de calendario para feriados nacionales hábiles.

## Resultado resumido del estudio

En la evaluación cronológica de 2025, el MAE agregado pasó de **488,96 a 479,91** (reducción observada de **1,85 %**), sobre 8.760 períodos. La extensión modificó 288 períodos de feriados hábiles; nueve fechas mejoraron y tres empeoraron. Son métricas agregadas derivadas, presentadas con atribución a la fuente de demanda del Coordinador Eléctrico Nacional (CEN); no se distribuyen observaciones ni pares observación-pronóstico.

La evaluación tiene límites: el MAE del benchmark de 2025 era conocido antes de evaluar la extensión, los valores de demanda son retrospectivos y no se reconstruyó qué versiones estaban disponibles al emitir cada pronóstico. El resultado no demuestra utilidad operacional ni estabilidad interanual.

## Dashboard de demostración

La aplicación muestra cuatro vistas interactivas con datos sintéticos deterministas. **Toda curva, fecha y métrica del dashboard es ficticia** y sirve únicamente para demostrar la interfaz. No representa resultados de 2025 ni observaciones del CEN.

```powershell
uv sync --locked --extra dashboard
uv run --locked --extra dashboard streamlit run dashboard/app.py
```

Requiere Python 3.11 o superior y `uv`.

## Código y metodología

- `src/`: benchmark, modelos candidatos, reglas de evaluación y auditorías.
- `tests/`: pruebas unitarias con ejemplos pequeños y sintéticos.
- `docs/protocol/`: protocolo y especificaciones congeladas disponibles para revisión.
- `dashboard/`: aplicación de demostración pública, aislada de los datos del estudio.
- `data/`: solo documentación; la demostración sintética se genera en memoria y no contiene series históricas del CEN.

Las métricas históricas resumidas se publican para comunicar el resultado, con atribución; esto no constituye una confirmación de derechos de redistribución sobre los datos fuente. La reproducción numérica completa requiere acceder legítimamente a los datos históricos, que no se distribuyen aquí. Los scripts científicos se ofrecen para inspección metodológica y algunos requieren artefactos privados ausentes en esta distribución. Las pruebas públicas usan exclusivamente ejemplos sintéticos y no vuelven a calcular la evaluación archivada.

## Fuentes y licencias

La fuente de la serie fue el [Coordinador Eléctrico Nacional](https://www.coordinador.cl/), en particular su producto de demanda sistémica real. El código original está bajo [MIT](LICENSE) y la documentación original bajo [CC BY 4.0](LICENSE-DOCS.md). Esas licencias no cubren datos ni materiales de terceros.

Este es un proyecto independiente y no representa una herramienta operacional ni una publicación oficial del CEN.

## Verificaciones públicas

La integración continua ejecuta estas comprobaciones en cada `push` y `pull request`:

```powershell
uv sync --locked --extra dashboard --extra modeling --extra dev
uv run --locked --no-sync python -B -m unittest discover -s tests -p 'test_*.py' -v
uv run --locked --no-sync ruff check dashboard tests scripts
uv run --locked --no-sync python scripts/verify_public_tree.py
```

Las pruebas no necesitan datos privados. La verificación del árbol falla si se rastrean formatos o rutas reservados para las observaciones y artefactos históricos.
