"""Tests for demo.py: README rendering, marker replacement and console summary."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import demo


def _info(arithmetic: int = 0, example: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "cases_differ_random": 0,
        "cases_differ_boundary": 0,
        "cases_differ_storage": 0,
        "cases_differ_arithmetic": arithmetic,
        "example": example,
    }


def _record(statement_id: str, translation: str, example: dict[str, Any] | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": statement_id,
        "program": "TEST",
        "file": "TEST.cbl",
        "line": 1,
        "verb": "COMPUTE",
        "status": "harnessed",
        "reason": None,
        "flags": {"scale": True, "float": True, "size": False, "sign": False},
        "variables": [["WS-A", "S9(3)V99", "DISPLAY"], ["WS-B", "S9(3)V99", "DISPLAY"]],
        "targets": ["WS-B"],
        "cases_random": 1,
        "cases_boundary": 0,
        "cobol_exact_cases_differ": 0,
    }
    for name in demo.COMPARED:
        record[name] = _info(1 if name == translation else 0, example if name == translation else None)
    return record


def _metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "programs_total": 1,
        "copybooks_missing": 0,
        "statements_total": 2,
        "statements_harnessed": 2,
        "statements_unsupported": 0,
        "statements_decimal_risk": 2,
        "cases_random": 2,
        "cases_boundary": 0,
        "cobol_exact_cases_differ": 0,
        "cobol_exact_agreement": 1.0,
    }
    for name in demo.COMPARED:
        metrics[f"{name}_statements_differ"] = 0
        metrics[f"{name}_cases_differ_storage"] = 0
        metrics[f"{name}_cases_differ_arithmetic"] = 0
    metrics["float_round_statements_differ"] = 1
    metrics["float_round_cases_differ_arithmetic"] = 1
    metrics["decimal_half_even_statements_differ"] = 1
    metrics["decimal_half_even_cases_differ_arithmetic"] = 1
    return metrics


def _write_results(root: Path, metrics: dict[str, Any], records: list[dict[str, Any]]) -> Path:
    results = root / "results"
    results.mkdir(parents=True, exist_ok=True)
    (results / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    payload = "\n".join(json.dumps(record) for record in records) + "\n"
    (results / "statements.jsonl").write_text(payload, encoding="utf-8")
    return results


class RenderTest(unittest.TestCase):
    def test_render_lists_every_arithmetic_statement(self) -> None:
        first = {"inputs": [123, 0], "cobol": [123], "translation": [124]}
        second = {"inputs": [100, 0], "cobol": [100], "translation": [101]}
        records = [
            _record("TEST:1:COMPUTE", "float_round", first),
            _record("TEST:2:COMPUTE", "decimal_half_even", second),
        ]
        text = demo.render(_metrics(), records)

        self.assertIn("TEST:1:COMPUTE", text)
        self.assertIn("TEST:2:COMPUTE", text)
        self.assertIn("float_round", text)
        self.assertIn("decimal_half_even", text)
        self.assertIn("WS-A=1.23", text)
        self.assertIn("WS-B=1.23", text)
        self.assertIn("1.24", text)
        self.assertIn("COBOL exact agreement: 1.000000", text)

    def test_replace_results_block_preserves_surrounding_text(self) -> None:
        template = "Before\n\n<!-- results:start -->\nold\n<!-- results:end -->\n\nAfter\n"
        text = demo.replace_results_block(template, "| A | B |")

        self.assertIn("Before", text)
        self.assertIn("After", text)
        self.assertIn("| A | B |", text)
        self.assertNotIn("old", text)
        self.assertLess(text.index("Before"), text.index(demo.START))
        self.assertLess(text.index(demo.START), text.index("| A | B |"))
        self.assertLess(text.index("| A | B |"), text.index(demo.END))

    def test_main_fills_readme_and_writes_the_whole_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            example = {"inputs": [123, 0], "cobol": [123], "translation": [124]}
            results = _write_results(root, _metrics(), [_record("TEST:1:COMPUTE", "float_round", example)])
            readme = root / "README.md"
            readme.write_text("Intro\n<!-- results:start -->\nold\n<!-- results:end -->\nOutro\n", encoding="utf-8")
            out = root / "OUT.md"

            code = demo.main(["--readme", str(readme), "--out", str(out), "--results", str(results)])
            text = out.read_text(encoding="utf-8")

            self.assertEqual(code, 0)
            self.assertIn("Intro", text)
            self.assertIn("Outro", text)
            self.assertIn("TEST:1:COMPUTE", text)
            self.assertIn("WS-A=1.23", text)
            self.assertNotIn("old", text)


class EmptyResultsTest(unittest.TestCase):
    def test_empty_results_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "missing"
            metrics, records = demo.load_results(results)

            self.assertEqual(metrics, {})
            self.assertEqual(records, [])
            self.assertIn("No results found", demo.render(metrics, records, results))

            output = io.StringIO()
            with redirect_stdout(output):
                code = demo.main(["--results", str(results)])

            self.assertEqual(code, 0)
            self.assertIn("No results", output.getvalue())


class SummaryTest(unittest.TestCase):
    def test_main_prints_summary_from_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = _write_results(Path(tmp), _metrics(), [])
            output = io.StringIO()
            with redirect_stdout(output):
                code = demo.main(["--results", str(results)])

            self.assertEqual(code, 0)
            self.assertIn("statements: 2/2 harnessed", output.getvalue())
            self.assertIn("COBOL exact agreement: 1.000000", output.getvalue())


if __name__ == "__main__":
    unittest.main()
