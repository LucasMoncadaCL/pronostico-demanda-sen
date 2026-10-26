#!/usr/bin/env python3
"""Recompute the main Fase 2 statistics from the saved CEN JSON responses.

Uses only Python's standard library. It never makes network requests and does
not require or read an API key.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from statistics import mean


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def rows_from_pages(folder: Path):
    rows = []
    pages = []
    for path in sorted(folder.glob("page-*.json")):
        response = read_json(path)
        page_rows = response.get("data", [])
        rows.extend(page_rows)
        pages.append({"file": path.name, "page": response.get("page"), "rows": len(page_rows),
                      "totalPages": response.get("totalPages"), "limit": response.get("limit")})
    return rows, pages


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, default=Path("evidencia-fase2"))
    parser.add_argument("--output", type=Path, default=Path("auditoria-fase2"))
    args = parser.parse_args()
    ev = args.evidence.resolve()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)

    # A: detailed estimated real demand.
    a_folder = ev / "demanda-real-2024-06-01"
    a_rows, a_pages = rows_from_pages(a_folder)
    a_keys = ["clave_anio_mes", "fecha_hora", "medida_kwh", "barra", "suministrador", "retiro", "tipo", "date_control"]
    exact = collections.Counter(json.dumps({k: r.get(k) for k in a_keys}, sort_keys=True, separators=(",", ":")) for r in a_rows)
    coarse = collections.Counter(tuple(r.get(k) for k in ["fecha_hora", "barra", "suministrador", "retiro", "tipo"]) for r in a_rows)
    hourly_kwh = collections.Counter()
    types = collections.Counter()
    signs = collections.Counter()
    for r in a_rows:
        value = float(r["medida_kwh"])
        hourly_kwh[r["fecha_hora"]] += value
        types[r.get("tipo")] += 1
        signs["negative" if value < 0 else "positive" if value > 0 else "zero"] += 1

    official = read_json(a_folder / "official-system-reference.json").get("results", [])
    official_by_hour = {int(r["hora"]): float(r["demanda"]) for r in official}
    hourly_comparison = []
    for timestamp in sorted(hourly_kwh):
        hour = int(timestamp[11:13]) + 1
        system = official_by_hour.get(hour)
        aggregate = -hourly_kwh[timestamp] / 1000.0
        if system is not None:
            difference = aggregate - system
            hourly_comparison.append({"fecha_hora": timestamp, "hora_periodo": hour,
                                      "retiros_agregados_estimados_MWh": aggregate,
                                      "demanda_sistemica_MWh": system,
                                      "diferencia_MWh": difference,
                                      "diferencia_pct": difference / system * 100 if system else None})
    abs_errors = [abs(x["diferencia_MWh"]) for x in hourly_comparison]
    mapes = [abs(x["diferencia_pct"]) for x in hourly_comparison if x["diferencia_pct"] is not None]
    a_summary = {
        "pages": a_pages,
        "rows": len(a_rows),
        "distinctHours": len(hourly_kwh),
        "firstHour": min(hourly_kwh) if hourly_kwh else None,
        "lastHour": max(hourly_kwh) if hourly_kwh else None,
        "distinctBars": len({r.get("barra") for r in a_rows}),
        "distinctSuppliers": len({r.get("suministrador") for r in a_rows}),
        "distinctWithdrawals": len({r.get("retiro") for r in a_rows}),
        "types": dict(types),
        "signs": dict(signs),
        "sumSignedKwh": sum(float(r["medida_kwh"]) for r in a_rows),
        "exactRepeatedExtraRows": sum(n - 1 for n in exact.values() if n > 1),
        "exactRepeatedGroups": sum(1 for n in exact.values() if n > 1),
        "coarseCompositeExtraRows": sum(n - 1 for n in coarse.values() if n > 1),
        "officialAggregateRows": len(official),
        "officialAggregateMWh": sum(official_by_hour.values()),
        "provisionalDetailAggregateMWh": -sum(hourly_kwh.values()) / 1000.0,
        "hourlyComparisonCount": len(hourly_comparison),
        "hoursDetailBelowSystem": sum(x["diferencia_MWh"] < 0 for x in hourly_comparison),
        "meanAbsoluteErrorMWh": mean(abs_errors) if abs_errors else None,
        "MAPEPercent": mean(mapes) if mapes else None,
    }
    (out / "recomputed-demand-real-summary.json").write_text(json.dumps(a_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "recomputed-hourly-comparison.json").write_text(json.dumps(hourly_comparison, ensure_ascii=False, indent=2), encoding="utf-8")

    # B: short-term forecast observations from saved periods.
    b_summaries = {}
    b_rows_by_folder = {}
    for name in ["pronostico-2024-06-01", "pronostico-2024-06-01-a-07", "pronostico-vigente-2026-10-25-a-31"]:
        folder = ev / name
        if not folder.exists():
            continue
        rows, pages = rows_from_pages(folder)
        b_rows_by_folder[name] = rows
        b_summaries[name] = {
            "pages": pages,
            "rows": len(rows),
            "distinctTargetHours": len({r.get("fecha_hora") for r in rows}),
            "firstTarget": min((r.get("fecha_hora") for r in rows), default=None),
            "lastTarget": max((r.get("fecha_hora") for r in rows), default=None),
            "distinctDateControls": sorted({r.get("date_control") for r in rows if r.get("date_control") is not None}),
            "distinctBars": len({r.get("barra") for r in rows}),
            "nullBarIds": sum(r.get("id_barra_info") is None for r in rows),
        }

    # PCP: candidate program dates and changed values, grouped by target and demand key.
    pcp_folder = ev / "demanda-programada-pcp-2024-06-01-a-07"
    pcp_rows, pcp_pages = rows_from_pages(pcp_folder)
    pcp_groups = collections.defaultdict(list)
    for r in pcp_rows:
        pcp_groups[(r.get("fecha_hora"), r.get("llave_dem"))].append(r)
    multi = [g for g in pcp_groups.values() if len({r.get("fecha_programa") for r in g}) > 1]
    changed = [g for g in multi if len({r.get("demanda_prog_mw") for r in g}) > 1]
    example = [r for r in pcp_rows if r.get("fecha_hora") == "2024-06-02 00:00:00" and r.get("llave_dem") == "Mapal154"]
    pcp_summary = {
        "pages": pcp_pages,
        "rows": len(pcp_rows),
        "distinctTargetHours": len({r.get("fecha_hora") for r in pcp_rows}),
        "distinctProgramDates": sorted({r.get("fecha_programa") for r in pcp_rows}),
        "targetHourDemandKeyGroups": len(pcp_groups),
        "groupsWithMultipleProgramDates": len(multi),
        "multipleProgramGroupsWithChangedValues": len(changed),
        "exampleMapal154": [{"fecha_programa": r.get("fecha_programa"), "fecha_hora": r.get("fecha_hora"),
                              "llave_dem": r.get("llave_dem"), "demanda_prog_mw": r.get("demanda_prog_mw"), "id": r.get("id")} for r in example],
    }

    # For target date June 1, compare B with the PCP program dated June 1.
    b_rows = b_rows_by_folder.get("pronostico-2024-06-01-a-07", [])
    b_hour = collections.Counter()
    for r in b_rows:
        if str(r.get("fecha_hora", "")).startswith("2024-06-01"):
            b_hour[r["fecha_hora"]] += float(r.get("energia_mwh") or 0)
    pcp_hour = collections.Counter()
    pcp_rows_issue_june1 = [r for r in pcp_rows if r.get("fecha_programa") == "2024-06-01" and str(r.get("fecha_hora", "")).startswith("2024-06-01")]
    for r in pcp_rows_issue_june1:
        pcp_hour[r["fecha_hora"]] += float(r.get("demanda_prog_mw") or 0)
    b_pcp = []
    for timestamp in sorted(set(b_hour) | set(pcp_hour)):
        b_val, pcp_val = b_hour.get(timestamp), pcp_hour.get(timestamp)
        b_pcp.append({"fecha_hora": timestamp, "B_sum": b_val, "PCP_program_june1_sum": pcp_val,
                      "difference_B_minus_PCP": (b_val - pcp_val) if b_val is not None and pcp_val is not None else None})

    # DST observations are retained in the raw response manifest.
    dst_manifest = read_json(ev / "cambio-horario-2024" / "manifest.json")
    summary = {
        "generatedFrom": str(ev.name),
        "demandReal": a_summary,
        "shortTermForecasts": b_summaries,
        "PCPProgramDateComparison": pcp_summary,
        "BversusPCPJune1": b_pcp,
        "DSTActualAggregate": dst_manifest,
    }
    (out / "recomputed-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # SHA-256 file index for all response/manifests supplied with the evidence set.
    index = []
    for path in sorted(p for p in ev.rglob("*") if p.is_file()):
        index.append({"path": path.relative_to(ev).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    (out / "sha256-evidence-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"output": str(out), "sourceFiles": len(index), "sourceBytes": sum(x["bytes"] for x in index),
                      "demandRows": a_summary["rows"], "exactRepeatedExtraRows": a_summary["exactRepeatedExtraRows"],
                      "pcpMultipleProgramGroups": pcp_summary["groupsWithMultipleProgramDates"],
                      "pcpChangedValueGroups": pcp_summary["multipleProgramGroupsWithChangedValues"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
