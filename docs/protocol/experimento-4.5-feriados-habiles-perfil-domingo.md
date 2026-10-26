# Experimento 4.5 — Regla congelada

**Estado:** diseño congelado antes de calcular resultados del experimento 4.5. No modifica el protocolo v1.2.

## Pregunta

En los feriados nacionales de lunes a viernes, ¿reemplazar el perfil histórico del día de semana correspondiente por el perfil histórico de domingo, manteniendo el mismo índice de período, reduce el MAE global del benchmark?

El perfil de domingo es una sustitución experimental sencilla. No se afirma que un feriado tenga el mismo comportamiento que un domingo.

## Regla congelada

- Ventana y objetivos: todos los 5.016 períodos del 6 de abril al 31 de octubre de 2024.
- Emisión: 18:00 hora de Santiago del día calendario anterior.
- Información histórica: `fecha_observacion < fecha_emision - 60 días calendario`, comparación estricta por fecha.
- Benchmark de control: perfil de media por día de semana × índice de período, mínimo `n >= 5` y jerarquía de respaldo existente.
- Candidato: solo en los nueve feriados hábiles incluidos en el manifiesto, pronosticar cada período con la media histórica de domingo × ese mismo índice, usando la historia elegible del origen correspondiente.
- Respaldo: se invoca la función existente del benchmark con `weekday=6` (domingo) y el índice original. Se conserva `n >= 5` y la misma jerarquía de respaldo. Si no hay ningún respaldo, la prueba de cobertura falla; no se inventa una predicción.
- No feriados: conservar exactamente la predicción benchmark previamente generada.
- No modificar: otros días, feriados de fin de semana, días electorales, índices horarios, soporte, corte, variables, ventana o protocolo.
- Métrica de selección: MAE horario global en objetivos comunes. MAE y sesgo de los nueve feriados, resultados por fecha, respaldos y comprobación de no cambio fuera de feriados son diagnósticos secundarios.
- No elegir ni reajustar la regla según el MAE exclusivo de feriados.
- Uso de 2025: prohibido para diseñar, ajustar o evaluar este experimento.

## Calendario fijado

Las fechas proceden de la [lista anual 2024 de Gob.cl](https://www.gob.cl/noticias/feriado-2024-chile-dias-festivos-irrenunciables/). Se aplica una regla mecánica: de los feriados nacionales enumerados, incluir los que caen de lunes a viernes dentro de la ventana fija. Las nueve fechas y sus nombres están enumerados en [el manifiesto JSON](experimento-4.5-feriados-habiles-perfil-domingo.json). Se excluyen deliberadamente eventos electorales y feriados regionales; el sábado 26 de octubre tampoco es feriado hábil. [Servel](https://www.servel.cl/Ch/app/26-y-27-de-octubre-elecciones-regionales-y-municipales/noticias/) confirma votaciones el 26 y 27 de octubre y feriado legal solo el domingo.

## Alcance de la conclusión

La hipótesis se formuló después de observar errores de 2024. Por ello, aunque la regla queda congelada y la comparación será reproducible, el resultado será una evaluación de desarrollo sujeta a adaptación a esa ventana, no una confirmación independiente. Un resultado favorable no establecerá causalidad ni utilidad operacional; uno desfavorable no descartará toda forma de modelar feriados.

La ejecución debe registrar el hash de este manifiesto, el CSV de datos y el código utilizado, junto con el soporte de cada predicción.
