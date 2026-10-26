"""Genera la figura de resultado final desde el JSON congelado de evaluación."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")


ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = (
    ROOT
    / "data/audits/2025-demanda-sistemica/evaluacion-extension-feriados-congelada/"
    / "evaluacion-extension-feriados-2025.json"
)
OUTPUT_PATH = ROOT / "docs/assets/resultados-extension-feriados-2025.png"


def main() -> None:
    import matplotlib.pyplot as plt

    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    all_targets = metrics["metrics"]["all_2025_targets_including_blackout"]
    benchmark = float(all_targets["benchmark"]["mae"])
    candidate = float(all_targets["candidate"]["mae"])
    target_count = metrics["coverage"]["target_rows"]
    changed_count = metrics["coverage"]["holiday_rows"]
    unchanged_count = metrics["coverage"]["unchanged_rows"]

    improvement = benchmark - candidate
    relative = improvement / benchmark * 100
    changed_share = changed_count / target_count * 100

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titleweight": "bold",
            "axes.labelcolor": "#334155",
            "text.color": "#172033",
        }
    )
    fig, ax = plt.subplots(figsize=(9.6, 5.4), layout="constrained")
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    labels = ["Benchmark semanal", "Benchmark + feriados"]
    values = [benchmark, candidate]
    colors = ["#52657a", "#168a72"]
    bars = ax.barh(labels, values, color=colors, height=0.52, zorder=3)
    ax.invert_yaxis()
    ax.set_xlim(0, max(values) * 1.19)
    ax.set_xlabel("MAE horario (escala numérica de la fuente)", labelpad=12)
    ax.set_title("La regla de feriados redujo el MAE en 2025", loc="left", pad=18, fontsize=17)
    ax.grid(axis="x", color="#e8edf2", linewidth=0.9, zorder=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.tick_params(axis="y", length=0, pad=12, labelsize=12)
    ax.tick_params(axis="x", colors="#64748b")

    for bar, value in zip(bars, values, strict=True):
        ax.text(
            value + max(values) * 0.018,
            bar.get_y() + bar.get_height() / 2,
            f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            va="center",
            ha="left",
            fontsize=13,
            fontweight="bold",
            color="#172033",
        )

    ax.text(
        0.98,
        0.50,
        f"−{improvement:.2f}  |  −{relative:.2f}%".replace(".", ","),
        transform=ax.transAxes,
        ha="right",
        va="center",
        fontsize=13,
        fontweight="bold",
        color="#11745f",
        bbox={"boxstyle": "round,pad=0.55", "facecolor": "#eaf6f2", "edgecolor": "none"},
    )
    changed_share_text = f"{changed_share:.2f}".replace(".", ",")
    period_count_text = f"{target_count:,}".replace(",", ".")
    unchanged_count_text = f"{unchanged_count:,}".replace(",", ".")
    fig.text(
        0.01,
        -0.01,
        f"Evaluación cronológica 2025 · {changed_count} de {period_count_text} períodos "
        f"modificados ({changed_share_text}%) · {unchanged_count_text} pronósticos sin cambios\n"
        "El benchmark 2025 ya era conocido; tres feriados empeoraron. Resultado retrospectivo, "
        "sin demostrar utilidad operacional.",
        ha="left",
        va="top",
        fontsize=9.5,
        color="#526174",
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Figura generada desde el JSON de la corrida archivada: {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
