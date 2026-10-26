"""Verify frozen holiday-extension artifacts and 2024 support without scoring 2025."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.baselines.weekday_period_mean import predict_one
from src.evaluation.benchmark_policy import frozen_2024_snapshot

MANIFEST = ROOT / "docs/protocol/manifest-congelamiento-extension-feriados-2025.json"
CALENDAR = ROOT / "docs/protocol/calendario-feriados-nacionales-2025.json"
TRAIN = ROOT / "data/audits/2024-demanda-sistemica/serie_horaria_2024.csv"
FIRST_ISSUE = date(2024, 12, 31)
RECEIPT = ROOT / "data/audits/2025-demanda-sistemica/preparacion-extension-feriados-2025/verificacion-paquete.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("status") != "frozen_before_candidate_2025_scoring":
        raise ValueError("El manifiesto no está congelado antes de puntuar el candidato.")
    mismatches = []
    for relative, expected in manifest["sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            mismatches.append(relative)
    if mismatches:
        raise ValueError("Hash no coincide o falta: " + ", ".join(mismatches))

    rows = []
    with TRAIN.open("r", encoding="utf-8-sig", newline="") as stream:
        import csv
        from decimal import Decimal
        for raw in csv.DictReader(stream):
            day = date.fromisoformat(raw["fecha"])
            if day.year != 2024:
                raise ValueError("Se encontró una observación no 2024 en el archivo de desarrollo.")
            rows.append({"date": day, "hour": int(raw["hora"]), "value": Decimal(raw["demanda"])})
    history = frozen_2024_snapshot(rows, FIRST_ISSUE, 60)
    if len(history) != 7320 or min(r["date"] for r in history) != date(2024, 1, 1) or max(r["date"] for r in history) != date(2024, 10, 31):
        raise AssertionError("Snapshot 2024 debe contener 7.320 registros del 1-ene al 31-oct.")
    if any(r["date"] >= date(2024, 11, 1) for r in history):
        raise AssertionError("El snapshot rebasa el corte exclusivo 2024-11-01.")

    calendar = json.loads(CALENDAR.read_text(encoding="utf-8"))
    dates = {date.fromisoformat(item["date"]) for item in calendar["national_holidays"]
             if item["class"] == "national_holiday" and date.fromisoformat(item["date"]).weekday() < 5}
    declared = {date.fromisoformat(value) for value in calendar["included_candidate_dates"]}
    if dates != declared or len(declared) != 12:
        raise AssertionError("Las fechas incluidas no siguen exactamente la regla mecánica del calendario.")
    if any(day in declared for day in (date(2025, 6, 29), date(2025, 11, 16), date(2025, 12, 14), date(2025, 6, 7), date(2025, 8, 20))):
        raise AssertionError("Un evento electoral o feriado regional fue incluido indebidamente.")

    support_min, support_max = 10**9, 0
    fallback_counts = {}
    for target_date in declared:
        for period in range(1, 25):
            result = predict_one(weekday=6, period_index=period, history=history)
            if result["prediction"] is None or result["n_support"] < 5:
                raise AssertionError(f"Perfil dominical sin soporte: {target_date}, período {period}.")
            if result["fallback_level"] != "weekday_x_period":
                raise AssertionError(f"No hay soporte directo domingo × período: {target_date}, período {period}.")
            support_min = min(support_min, result["n_support"])
            support_max = max(support_max, result["n_support"])
            fallback_counts[result["fallback_level"]] = fallback_counts.get(result["fallback_level"], 0) + 1

    # This preflight hashes the pre-existing 2025 files but never parses them,
    # generates the candidate, or computes candidate metrics.
    receipt = {
        "status": "PACKAGE_VERIFIED_NO_2025_CANDIDATE_METRICS_COMPUTED",
        "verified_date": "2026-10-25",
        "manifest_sha256": sha256(MANIFEST),
        "frozen_artifacts_hashes_match": True,
        "history_rows": len(history),
        "history_start": min(r["date"] for r in history).isoformat(),
        "history_end": max(r["date"] for r in history).isoformat(),
        "candidate_holiday_dates": len(declared),
        "candidate_dates": sorted(day.isoformat() for day in declared),
        "sunday_period_profiles_checked": len(declared) * 24,
        "support_min": support_min,
        "support_max": support_max,
        "fallback_levels": fallback_counts,
        "candidate_2025_metrics_calculated": False,
        "2025_target_or_prediction_rows_parsed": False,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
