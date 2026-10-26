# Protocolo de evaluación v1.2 — bloqueado para evaluación del benchmark

**Estado:** reglas bloqueadas para el benchmark; no se permite modificar umbrales o reglas a partir de resultados de 2025.
**Propósito:** cerrar las reglas antes de entrenar y proteger, hasta donde permite el trabajo ya realizado, la evaluación candidata de 2025.

## 1. Pregunta y unidad de evaluación

Evaluar cuánto se aproximan métodos propios a la **demanda sistémica real agregada** para todos los períodos del día calendario siguiente, con una emisión convencional a las 18:00 de Chile continental del día anterior. La hora de emisión es una convención experimental, no una hora oficial del CEN.

La observación objetivo se identifica por `(fecha, hora)` exactamente como la entrega la API. `hora` se conserva como índice de período; no se convierte a hora civil ni a UTC sin una correspondencia demostrada. Se pronostican todos los índices presentes para cada fecha: 23, 24 o 25 según la fuente. No se inventan períodos ni se rellenan huecos.

## 2. Regímenes de información

### Resultado principal: corte conservador de 60 días

Para cada origen de pronóstico con fecha de emisión `I`, permitir como demanda histórica solo registros que cumplan:

```text
fecha_observacion < fecha_emision.date() - timedelta(days=60)
```

`I` es el timestamp de emisión a las 18:00. Primero se obtiene su fecha calendario local, `fecha_emision.date()`; luego se calcula la fecha de corte restando 60 días calendario. La comparación se hace entre fechas, no timestamps: `fecha_observacion < fecha_emision.date() - timedelta(days=60)`. La desigualdad estricta evita admitir la fecha límite, cuyo último período podría tener menos de 60 días completos de antigüedad. Aplicar el corte tanto a entradas de demanda como a las etiquetas históricas usadas para entrenar en ese origen. El calendario que ya se conoce antes de emitir puede utilizarse. La demanda de las fechas objetivo futuras solo se usa como referencia ex post para medir error.

**Justificación:** el CEN indica que la demanda sistémica real se basa en el balance mensual de inyecciones y retiros y que los datos de un mes se oficializan y publican a partir del día 20 del mes siguiente. Un rezago estricto de 60 días deja pasar el cierre mensual y ese plazo, incluso para las observaciones del comienzo del mes. Es una regla reproducible y deliberadamente conservadora. [CEN, Demanda Real](https://www.coordinador.cl/operacion/graficos/operacion-real/demanda-real/)

**Interpretación:** el resultado principal mide pronóstico con la última demanda histórica sujeta a ese corte, no pronóstico que utiliza la demanda de ayer o de la semana pasada. Es un escenario de información pública finalizada; no representa necesariamente la información operacional que el CEN u otros actores poseen en tiempo real.

**Límite:** el plazo de publicación no reconstruye las versiones disponibles en cada fecha, ni prueba que la serie descargada hoy sea idéntica a la versión de entonces. Por eso la evaluación sigue siendo retrospectiva con valores definitivos/revisados y un corte de antigüedad; no se denominará simulación operacional histórica.

### Sensibilidad: política retrospectiva con historial reciente y benchmark actualizado

Repetir con corte de fecha calendario `fecha_observacion < fecha_emision.date()`, sin el rezago adicional de 60 días. El benchmark recalcula sus medias en cada emisión usando toda la historia revisada anterior permitida por ese corte, incluidos datos anteriores de 2025. Los parámetros de cualquier modelo candidato permanecen congelados, aunque sus entradas cambian conforme a la política.

Esta sensibilidad compara una **política completa** distinta: reduce la antigüedad del historial y actualiza el benchmark durante 2025. Una diferencia entre resultados no se interpretará como efecto aislado del rezago de 60 días. Aislar ese efecto requeriría un experimento posterior que controle la actualización del benchmark. Esta política retrospectiva no demuestra disponibilidad real de esas versiones.

## 3. Separación temporal y ajuste

- **Desarrollo:** 2024, con validación cronológica de origen móvil y el corte de información correspondiente a cada emisión. El EDA previo de 2024 se reconoce como parte del desarrollo; no se presenta como prueba independiente.
- **Evaluación candidata:** 2025. El año no es completamente desconocido: conocemos su cobertura y el evento del 25–26 de febrero. Sus errores, distribuciones y métricas no se usarán para escoger métodos, variables, hiperparámetros ni reglas.
- **Selección temporal:** usar para seleccionar método e hiperparámetros únicamente validaciones cronológicas con objetivos entre **2024-04-06 y 2024-10-31**. El límite final se deriva del primer origen de prueba 2024-12-31: con su corte estricto, objetivos posteriores a 2024-10-31 aún no son elegibles para determinar la selección.
- **Política de parámetros (estrategia A, modelo congelado):** ajustar y reestimar parámetros solo con ejemplos de entrenamiento de 2024 que fueran elegibles al primer origen de prueba (emisión 2024-12-31 para el objetivo 2025-01-01). Con el corte estricto, la última fecha objetivo de entrenamiento permitida al primer origen es 2024-10-31. Congelar parámetros e hiperparámetros durante todo 2025. Las entradas de una emisión sí pueden actualizarse con observaciones históricas de 2025 que ya superen el corte; esto actualiza los valores de entrada, no los parámetros aprendidos. No se usan etiquetas de 2025 para entrenar.

## 4. Benchmark principal

Usar un **perfil medio por día de semana e índice de período**, calculado solo con el conjunto de entrenamiento autorizado de 2024. Para el resultado principal de 2025, congelar como conjunto base las observaciones de 2024 disponibles al primer origen: emisión 2024-12-31, corte exclusivo 2024-11-01, es decir, fechas 2024-01-01 a 2024-10-31. El benchmark no incorpora observaciones ni objetivos de 2025.

Requerir **al menos cinco observaciones** (`n >= 5`) para usar la media de un grupo. Cinco es un umbral práctico predefinido para evitar que una media con uno o dos casos se presente como patrón consolidado; no es una garantía estadística universal. Aplicar esta jerarquía:

1. media para día de semana × índice de período, si `n >= 5`;
2. si no, media para ese índice de período en todos los días, si `n >= 5`;
3. si no, media para ese día de semana sobre todos los índices, si `n >= 5`;
4. si no, media global de períodos elegibles, si `n >= 5`;
5. si ningún nivel cumple, no emitir benchmark para ese objetivo y excluirlo de la comparación común de todos los métodos, informando cantidad y fechas.

El respaldo para el índice 25 usa el promedio del día de semana sobre los índices disponibles; no crea una observación ni infiere una hora civil. En la sensibilidad sin rezago, recalcular las mismas estadísticas de acuerdo con ese régimen, usando solo fechas anteriores a cada emisión. Congelar la jerarquía y el mínimo `n` antes de calcular métricas de 2025.

### Cobertura comprobada con historia 2024

La prueba reproducible del script `data/audits/2025-demanda-sistemica/analizar_cobertura_benchmark.py` confirma que el conjunto congelado de 2024 contiene **7.320 registros de 305 fechas**, hasta el 31 de octubre. Esta prueba verifica cobertura potencial y soporte; no calcula pronósticos numéricos ni métricas de 2025. Cada grupo de día de semana × índice 1–24 tiene entre **42 y 44 observaciones**. Para los **8.760 períodos de 2025**, la jerarquía encuentra soporte suficiente para producir un valor: **8.759** usan el grupo específico y el índice 25 del **5 de abril de 2025** usa el respaldo de sábado sobre todos los períodos (`n=1.033`). No queda ningún objetivo sin soporte de predicción bajo la jerarquía del benchmark. El grupo sábado × período 25 tiene solo un antecedente autorizado (2024-04-06), por debajo del mínimo de cinco; no se usa como media específica.

Para la validación de desarrollo de 2024, cuyo último objetivo permitido para selección es 2024-10-31, el primer objetivo con soporte suficiente para todos los grupos ordinarios (siete días × índices 1–24, `n >= 5`) y respaldo para períodos excepcionales es **2024-04-06**, emitido el 2024-04-05. En ese origen hay 840 registros elegibles (2024-01-01 a 2024-02-04). Esto define el warm-up por evidencia de soporte, no por una fecha escogida a conveniencia.

## 5. Entrenamiento y evaluación

El período de arranque (warm-up) termina cuando el benchmark alcanza el soporte mínimo. El primer objetivo válido es 2024-04-06; el último objetivo cuyo resultado se puede usar para seleccionar el método es 2024-10-31. Los objetivos anteriores al warm-up y posteriores al límite de selección no entran en métricas de selección. El snapshot de entrenamiento del primer origen de prueba termina el 2024-10-31.

En cada origen de validación de 2024, crear el entrenamiento y las entradas solo con observaciones elegibles bajo el corte de ese origen. Seleccionar método e hiperparámetros usando errores de los objetivos 2024-04-06 a 2024-10-31. En la primera emisión de evaluación (2024-12-31, para objetivo 2025-01-01), reestimar los parámetros del método elegido con ejemplos de entrenamiento de 2024 que sean elegibles en ese origen, sin incorporar objetivos posteriores a 2024-10-31. Congelar parámetros e hiperparámetros durante todo 2025. Las entradas permitidas por la regla pueden cambiar diariamente, pero no actualizan los parámetros aprendidos.

No barajar registros, ajustar transformaciones con datos posteriores ni utilizar observaciones objetivo antes de que sean elegibles. La ventana de selección no incluye noviembre ni diciembre de 2024, aunque esos valores permanezcan guardados.

Registrar para cada predicción: fecha/hora de emisión, fecha e índice objetivo, método/versión, régimen, información disponible y valor pronosticado. Conservar por separado `y` ex post y `ŷ`.

## 6. Métricas y reporte

- **Principal:** MAE horario sobre todos los períodos comparables, incluidos los días excepcionales y el episodio del apagón.
- **Secundarias:** RMSE y sesgo medio (`pronóstico − observado`); MAPE solo como complemento descriptivo si se mantienen denominadores válidos.
- Reportar en el conjunto común de objetivos, con número de períodos y fechas. Mostrar además error agregado por día, mes, índice de período y tipo de día cuando su definición esté validada. Informar por separado el error del índice 25 del 2025-04-05 y etiquetarlo como respaldo de baja especificidad.
- No fijar un umbral arbitrario de mejora. Comparar cada método con el benchmark bajo los mismos objetivos y el mismo régimen.

## 7. Episodio excepcional del 25–26 de febrero de 2025

La auditoría detectó valores extraordinariamente bajos el 25 de febrero. El CEN documenta un apagón iniciado aproximadamente a las 15:16 y recuperación que continuó durante la noche y madrugada del 26. [Comunicado del CEN](https://www.coordinador.cl/novedades/informacion-respecto-de-la-situacion-del-sistema-electrico-nacional/), [relato técnico del CEN](https://seguridadenergetica.coordinador.cl/nuestra-mirada-del-blackout/).

La regla se fija antes de calcular pronósticos:

1. **Resultado principal:** incluir todos los períodos de ambas fechas. No eliminar, imputar, suavizar ni corregirlos.
2. **Diagnóstico:** mostrar errores del 25 y 26 de febrero por separado, conservando los índices originales.
3. **Sensibilidad de evento:** volver a calcular métricas excluyendo todas las observaciones objetivo de las fechas 25 y 26 de febrero de 2025. El evento se delimita por fecha completa, no por horas civiles, hasta documentar el mapa de índices. La métrica sin esos días es diagnóstica; no se utiliza para elegir el modelo ni para reemplazar el resultado principal.

Este tratamiento evita ocultar un evento real y permite cuantificar su influencia sin dejar que determine la selección del método.

## 8. Estado de decisión

| Decisión | Protocolo v1.2 |
|---|---|
| Régimen principal | Corte de 60 días, con alcance de información pública finalizada |
| Régimen de sensibilidad | Historial revisado hasta el día anterior y benchmark actualizado; política completa retrospectiva |
| Benchmark | Media por día de semana × índice; mínimo n=5 y jerarquía de respaldo congelada con 2024 |
| Desarrollo y selección | Validación cronológica 2024-04-06 a 2024-10-31 |
| 2025 | Parámetros fijos; entrenamiento 2024 elegible hasta 2024-10-31; inputs según corte |
| Evento | Incluir 25–26 feb en principal; análisis separado y sensibilidad excluyéndolos |
| Métrica primaria | MAE horario en objetivos comunes |
| Horario de verano | Unir por `(fecha, hora)` de la fuente; mantener todos los períodos y no inferir horas civiles |

El protocolo v1.2 fija las reglas antes de producir predicciones de 2025. Las interpretaciones de resultados deberán conservar las limitaciones de publicación, revisión, definición/unidad y mapeo horario señaladas arriba.




## 9. Puerta de implementación

1. Implementar el benchmark como una función determinista con jerarquía y umbral `n >= 5` fijados aquí.
2. Validar el cálculo exclusivamente con datos de 2024, para objetivos 2024-04-06 a 2024-10-31; comprobar por cada emisión el día de emisión, la fecha de corte, la fecha máxima de historia, el grupo de respaldo y la ausencia de observaciones objetivo en las entradas.
3. No calcular ni inspeccionar resultados de 2025 hasta que las verificaciones anteriores pasen y el código quede congelado.
4. Luego ejecutar la evaluación especificada de 2025. El año es un holdout no ciego: sus observaciones y el apagón ya se conocen, pero sus métricas no se usan para modificar reglas o elegir el método.
