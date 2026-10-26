# Pronóstico de demanda eléctrica del SEN de Chile

**Python · Series temporales · Validación cronológica · scikit-learn · Streamlit · Plotly**

Desarrollé este proyecto para estudiar el pronóstico horario de demanda sistémica agregada del Sistema Eléctrico Nacional (SEN). La pregunta central fue si una regla sencilla de calendario podía mejorar un benchmark basado en perfiles históricos por día de semana e índice de período.

## Resultado principal

En la evaluación retrospectiva de 2025, la extensión de feriados redujo el MAE de **488,96 a 479,91** (**−1,85 %**) frente al benchmark semanal, sobre **8.760 períodos**.

| Método | MAE | Cobertura |
| --- | ---: | ---: |
| Benchmark semanal | 488,96 | 8.760 períodos |
| Benchmark + perfil de feriados | 479,91 | 8.760 períodos |
| Cambio observado | −9,05 (−1,85 %) | Se trataron 288 períodos |

Estas cifras resumen la evaluación histórica. No incluyo las observaciones del CEN ni los pares de demanda observada y predicción. La evaluación no fue completamente ciega: ya conocía el resultado del benchmark de 2025 antes de evaluar la extensión.

## Hallazgos principales

- **Probé una regla concreta y auditable:** en feriados nacionales de lunes a viernes usé el perfil histórico de domingo del mismo índice de período. Los demás pronósticos quedaron intactos.
- **El beneficio fue desigual:** nueve de los doce feriados tratados mejoraron y tres empeoraron. Este resultado de 2025 no demuestra estabilidad entre años.
- **Las especificaciones más complejas no mejoraron la referencia:** Ridge y árboles potenciados, que probé durante el desarrollo de 2024, no superaron al benchmark en esa ventana.
- **La regla tiene límites ante eventos extraordinarios:** no cambia los pronósticos durante perturbaciones de la red ni demuestra utilidad operacional.

## Cómo funciona la comparación

Definí el **benchmark** como el promedio histórico de cada combinación de día de semana e índice de período. La **extensión** usa esa misma referencia, salvo en feriados nacionales de lunes a viernes: ahí sustituye el perfil por el promedio de domingo del mismo índice. Comparé ambas reglas sobre exactamente los mismos objetivos.

Audité las series horarias de 2024 y 2025, diseñé una validación cronológica, comparé métodos y analicé sus errores. También preparé una demostración interactiva. Como usé demanda descargada retrospectivamente, no pude reconstruir qué versiones habrían estado disponibles en cada emisión. Por eso, esta evaluación no equivale a una simulación operacional.

En el [caso de estudio](docs/caso-de-estudio.md) explico el protocolo, la regla de feriados, el flujo de investigación y sus límites.

## Demostración visual

Preparé la aplicación pública con **datos 100 % sintéticos** generados en memoria. La ilustración estática muestra esa demostración; no es una captura de la evaluación real y sus curvas, fecha y métricas no corresponden a observaciones del CEN.

![Vista ilustrativa de la aplicación pública con datos sintéticos](docs/assets/dashboard-demostracion-sintetica.svg)

Para recorrer las cuatro vistas localmente:

```powershell
uv sync --locked --extra dashboard
uv run --locked --extra dashboard streamlit run dashboard/app.py
```

Requiere Python 3.11 o superior y [uv](https://docs.astral.sh/uv/).

## Tecnologías y reproducibilidad

- **Análisis y modelos:** Python, pandas, NumPy y scikit-learn.
- **Visualización interactiva:** Streamlit y Plotly.
- **Calidad:** unittest, Ruff y GitHub Actions.
- **Pruebas públicas:** escribí pruebas con ejemplos sintéticos para verificar que el paquete no incorpore artefactos históricos reservados.

La aplicación pública no accede a la API del CEN ni a archivos privados. Dejé los scripts científicos para inspeccionar el método; algunos requieren artefactos del archivo científico privado y no pueden ejecutarse de extremo a extremo con esta copia. La evaluación numérica histórica no debe relanzarse como una nueva corrida desde este paquete. Su reproducción requiere acceso legítimo a los datos de origen.

La integración continua ejecuta estas comprobaciones públicas en cada `push` y `pull request`:

```powershell
uv sync --locked --extra dashboard --extra modeling --extra dev
uv run --locked --no-sync python -B -m unittest discover -s tests -p 'test_*.py' -v
uv run --locked --no-sync ruff check dashboard tests scripts
uv run --locked --no-sync python scripts/verify_public_tree.py
```

## Documentación

- [Caso de estudio](docs/caso-de-estudio.md)
- [Protocolo experimental](docs/protocol/README.md)
- [Código fuente](src/)
- [Dashboard y ejecución local](dashboard/README.md)
- [Pruebas](tests/)
- [Política de datos y procedencia](data/README.md)
- [Flujo de integración continua](.github/workflows/public-package-checks.yml)

## Fuentes, datos y licencias

Usé como fuente de demanda al [Coordinador Eléctrico Nacional](https://www.coordinador.cl/). Las licencias de mi código y documentación no cubren los datos originales ni materiales de terceros; el acceso público no implica que sean de dominio público ni confirma derechos de redistribución. Las métricas resumidas incluyen atribución, aunque eso no resuelve la incertidumbre sobre las condiciones aplicables a los datos fuente.

El código original se distribuye bajo [MIT](LICENSE) y la documentación original bajo [CC BY 4.0](LICENSE-DOCS.md). Esas licencias no cubren datos ni materiales de terceros.

Es un proyecto independiente; no es una herramienta operacional ni una publicación oficial del CEN.
