"""Render cobarith results into a README block and a short console summary."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cobarith.data import parse_pic
from cobarith.translate import TRANSLATIONS

__all__ = ["load_results", "main", "render", "replace_results_block", "summary"]

START = "<!-- results:start -->"
END = "<!-- results:end -->"
COMPARED = tuple(name for name in TRANSLATIONS if name != "cobol_exact")


def load_results(results: str | Path = "results") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read metrics.json and statements.jsonl from *results*; missing files are empty."""
    root = Path(results)
    metrics_path = root / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else {}
    records: list[dict[str, Any]] = []
    records_path = root / "statements.jsonl"
    if records_path.exists():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return metrics, records


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _decimal(units: int, scale: int) -> str:
    units = int(units)
    sign = "-" if units < 0 else ""
    digits = str(abs(units))
    if scale <= 0:
        return sign + digits
    digits = digits.rjust(scale + 1, "0")
    return f"{sign}{digits[:-scale]}.{digits[-scale:]}"


def _scales(record: Mapping[str, Any]) -> dict[str, int]:
    scales: dict[str, int] = {}
    for entry in record.get("variables", []):
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        name, picture = entry[0], entry[1]
        if isinstance(name, str) and isinstance(picture, str):
            scales[name] = parse_pic(picture).scale
    return scales


def _decimal_list(names: Sequence[str], values: Sequence[Any], scales: Mapping[str, int]) -> str:
    parts: list[str] = []
    for name, value in zip(names, values, strict=False):
        try:
            units = int(value)
        except (TypeError, ValueError):
            parts.append(f"{name}={value}")
            continue
        parts.append(f"{name}={_decimal(units, scales.get(name, 0))}")
    return ", ".join(parts)


def _example(record: Mapping[str, Any], names: Sequence[str]) -> str:
    scales = _scales(record)
    variables = [entry[0] for entry in record.get("variables", []) if isinstance(entry, (list, tuple)) and entry]
    targets = [str(name) for name in record.get("targets", [])]
    for name in names:
        info = record.get(name)
        if not isinstance(info, Mapping):
            continue
        example = info.get("example")
        if not isinstance(example, Mapping):
            continue
        inputs = example.get("inputs") or []
        cobol = example.get("cobol") or []
        translation = example.get("translation") or []
        input_text = _decimal_list(variables, inputs, scales)
        cobol_text = _decimal_list(targets, cobol, scales)
        translation_text = _decimal_list(targets, translation, scales)
        return f"{input_text} -> COBOL {cobol_text}; {name} {translation_text}"
    return ""


def _arithmetic_translations(record: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for name in COMPARED:
        info = record.get(name)
        if not isinstance(info, Mapping):
            continue
        try:
            differ = int(info.get("cases_differ_arithmetic", 0) or 0)
        except (TypeError, ValueError):
            differ = 0
        if differ > 0:
            names.append(name)
    return names


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _metrics_table(metrics: Mapping[str, Any]) -> str:
    lines = ["| Metric | Value |", "| --- | --- |"]
    if metrics:
        for key in sorted(metrics):
            lines.append(f"| `{_cell(key)}` | {_cell(_format_value(metrics[key]))} |")
    else:
        lines.append("| _none_ | |")
    return "\n".join(lines)


def _arithmetic_table(records: Sequence[Mapping[str, Any]]) -> str:
    lines = ["| Statement | Translations | Example (decimal) |", "| --- | --- | --- |"]
    found = False
    for record in records:
        names = _arithmetic_translations(record)
        if not names:
            continue
        found = True
        example = _example(record, names)
        statement_id = _cell(record.get("id", ""))
        lines.append(f"| `{statement_id}` | {_cell(', '.join(names))} | {_cell(example)} |")
    if not found:
        lines.append("| _none_ | | |")
    return "\n".join(lines)


def _storage_table(metrics: Mapping[str, Any]) -> str:
    header = "| Translation | Statements differ | Cases: storage | Cases: arithmetic |"
    rule = "| --- | ---: | ---: | ---: |"
    lines = [header, rule]
    for name in COMPARED:
        statements = metrics.get(f"{name}_statements_differ", 0)
        storage = metrics.get(f"{name}_cases_differ_storage", 0)
        arithmetic = metrics.get(f"{name}_cases_differ_arithmetic", 0)
        lines.append(f"| {name} | {_cell(statements)} | {_cell(storage)} | {_cell(arithmetic)} |")
    return "\n".join(lines)


def _agreement(metrics: Mapping[str, Any]) -> str:
    agreement = metrics.get("cobol_exact_agreement")
    differ = metrics.get("cobol_exact_cases_differ", 0)
    if isinstance(agreement, (int, float)):
        return f"COBOL exact agreement: {agreement:.6f} ({differ} differing cases)."
    return f"COBOL exact agreement: n/a ({differ} differing cases)."


def render(metrics: Mapping[str, Any], records: Sequence[Mapping[str, Any]], results: str | Path | None = None) -> str:
    if not metrics and not records:
        where = f" in `{results}`" if results is not None else ""
        return f"_No results found{where}. Run `python experiment.py --out results/metrics.json`._"
    return "\n\n".join(
        [
            "## Results",
            "### Metrics",
            _metrics_table(metrics),
            "### Arithmetic differences",
            _arithmetic_table(records),
            "### Storage",
            _storage_table(metrics),
            _agreement(metrics),
        ]
    )


def replace_results_block(template: str, block: str) -> str:
    """Replace what lies between the results markers, keeping the surrounding README."""
    start = template.find(START)
    end = template.find(END, start + len(START)) if start != -1 else -1
    body = block.strip("\n")
    if start == -1 or end == -1:
        prefix = template.rstrip()
        if prefix:
            prefix += "\n\n"
        return f"{prefix}{START}\n{body}\n{END}\n"
    before = template[: start + len(START)]
    after = template[end:]
    return f"{before}\n{body}\n{after}"


def summary(metrics: Mapping[str, Any], records: Sequence[Mapping[str, Any]], results: str | Path = "results") -> str:
    if not metrics:
        target = Path(results) / "metrics.json"
        return f"No results in {results}; run `python experiment.py --out {target}`."
    total = metrics.get("statements_total", 0)
    harnessed = metrics.get("statements_harnessed", 0)
    lines = [
        f"cobarith results from {results}",
        f"Programs: {metrics.get('programs_total', 0)}; statements: {harnessed}/{total} harnessed",
        f"Cases: {metrics.get('cases_random', 0)} random + {metrics.get('cases_boundary', 0)} boundary",
    ]
    agreement = metrics.get("cobol_exact_agreement")
    if isinstance(agreement, (int, float)):
        lines.append(f"COBOL exact agreement: {agreement:.6f}")
    else:
        lines.append("COBOL exact agreement: n/a")
    for name in COMPARED:
        statements = metrics.get(f"{name}_statements_differ_arithmetic", 0)
        cases = metrics.get(f"{name}_cases_differ_arithmetic", 0)
        if statements or cases:
            lines.append(f"{name}: {statements} statements, {cases} cases differ arithmetically")
    if not records:
        lines.append("No statement records found.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--readme", type=Path, help="README template containing the results markers")
    parser.add_argument("--out", type=Path, help="write the rendered README here")
    parser.add_argument(
        "--results",
        type=Path,
        default=Path("results"),
        help="directory with metrics.json and statements.jsonl",
    )
    args = parser.parse_args(argv)

    metrics, records = load_results(args.results)
    if args.readme is None and args.out is None:
        print(summary(metrics, records, args.results))
        return 0

    if args.readme is None or args.out is None:
        parser.error("--readme and --out must be used together")

    template = args.readme.read_text(encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        replace_results_block(template, render(metrics, records, args.results)),
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
