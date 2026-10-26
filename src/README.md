# Código fuente

El código está organizado en tres áreas:

- `baselines/`: benchmark por día de semana e índice de período.
- `models/`: modelos candidatos y extensión de perfil para feriados.
- `evaluation/`: validación cronológica y utilidades de auditoría.

Los scripts de evaluación necesitan entradas históricas que no se distribuyen en esta versión. No los ejecutes esperando reproducir las métricas resumidas del README. Las pruebas unitarias usan datos sintéticos y no acceden a la API.

La evaluación final congelada de 2025 se conserva como evidencia histórica en el archivo privado; no debe relanzarse.
