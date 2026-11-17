import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import experiment

COBC = os.environ.get("COBARITH_COBC") or shutil.which("cobc")


def fixed(seq: str, indicator: str, code: str) -> str:
    return f"{seq}{indicator}{code}"


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def program_lines(data: list[str], procedure: list[str]) -> list[str]:
    lines = [
        fixed("000100", " ", "IDENTIFICATION DIVISION."),
        fixed("000200", " ", "PROGRAM-ID. TEST."),
        fixed("000300", " ", "DATA DIVISION."),
        fixed("000400", " ", "WORKING-STORAGE SECTION."),
    ]
    for number, code in enumerate(data, 5):
        lines.append(fixed(f"{number:06d}", " ", code))
    lines.append(fixed("009000", " ", "PROCEDURE DIVISION."))
    for number, code in enumerate(procedure, 91):
        lines.append(fixed(f"{number:06d}", " ", code))
    return lines


def make_root(tmp: str, data: list[str], procedure: list[str]) -> Path:
    root = Path(tmp)
    write(root / "TEST.cbl", program_lines(data, procedure))
    return root


class ExperimentTest(unittest.TestCase):
    def test_unsupported_record_and_reason_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(3)."],
                ["COMPUTE WS-A = FUNCTION NUMVAL(WS-B)."],
            )
            metrics, records = experiment.experiment(root)

            self.assertEqual(len(records), 1)
            record = records[0]
            self.assertEqual(record["status"], "unsupported")
            self.assertEqual(record["reason"], "intrinsic function")
            self.assertEqual(
                set(record),
                {"id", "program", "file", "line", "verb", "status", "reason"},
            )
            self.assertEqual(metrics["statements_total"], 1)
            self.assertEqual(metrics["statements_unsupported"], 1)
            self.assertEqual(metrics["statements_harnessed"], 0)
            self.assertEqual(metrics["statements_compute"], 1)
            self.assertEqual(metrics["unsupported_intrinsic_function"], 1)

    def test_the_arithmetic_example_skips_an_earlier_storage_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(tmp, ["01 WS-A PIC 9V9.", "01 WS-B PIC 9(2)."], ["COMPUTE WS-A = WS-B / 3."])
            # B = 60: 20.0 overflows 9V9 (a storage effect); B = 2: 0.666... truncates to 0.6, float_round gives 0.7.
            with (
                mock.patch("experiment.random_cases", return_value=[(0, 60), (0, 2)]),
                mock.patch("experiment.boundary_cases", return_value=[]),
                mock.patch("experiment.run", return_value=[((0,), False), ((6,), False)]),
            ):
                _, records = experiment.experiment(root)

        record = records[0]
        self.assertEqual(record["float_round"]["cases_differ_storage"], 1)
        self.assertEqual(record["float_round"]["cases_differ_arithmetic"], 1)
        self.assertEqual(record["float_round"]["example"]["inputs"], [0, 60])
        expected = {"inputs": [0, 2], "cobol": [6], "translation": [7]}
        self.assertEqual(record["arithmetic_examples"]["float_round"], expected)

    def test_harnessed_record_and_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(2)."],
                ["COMPUTE WS-A = WS-B / 5."],
            )
            with (
                mock.patch("experiment.random_cases", return_value=[(0, 13), (0, 17)]),
                mock.patch("experiment.boundary_cases", return_value=[]),
                mock.patch("experiment.run", return_value=[((2,), False), ((3,), False)]),
            ):
                metrics, records = experiment.experiment(root)

            record = records[0]
            self.assertEqual(record["status"], "harnessed")
            self.assertEqual(record["targets"], ["WS-A"])
            self.assertEqual(
                record["variables"],
                [["WS-A", "S9(3)", "DISPLAY"], ["WS-B", "S9(2)", "DISPLAY"]],
            )
            self.assertEqual(record["cases_random"], 2)
            self.assertEqual(record["cases_boundary"], 0)
            self.assertEqual(record["cobol_exact_cases_differ"], 0)
            self.assertEqual(
                record["flags"],
                {"scale": True, "float": True, "size": False, "sign": False},
            )
            self.assertEqual(record["float_round"]["cases_differ_random"], 1)
            self.assertEqual(record["float_round"]["cases_differ_arithmetic"], 1)
            self.assertEqual(record["float_round"]["cases_differ_storage"], 0)
            self.assertEqual(
                record["float_round"]["example"],
                {"inputs": [0, 13], "cobol": [2], "translation": [3]},
            )
            self.assertEqual(record["float_truncate"]["cases_differ_random"], 0)
            self.assertEqual(metrics["cobol_exact_agreement"], 1.0)
            self.assertEqual(metrics["float_round_statements_differ"], 1)
            self.assertEqual(metrics["float_round_statements_differ_arithmetic"], 1)
            self.assertEqual(metrics["float_round_cases_differ_random"], 1)
            self.assertEqual(metrics["float_round_cases_differ_arithmetic"], 1)
            self.assertEqual(metrics["float_round_cases_differ_storage"], 0)
            self.assertEqual(metrics["cases_random"], 2)
            self.assertEqual(metrics["statements_flag_scale"], 1)
            self.assertEqual(metrics["statements_flag_float"], 1)
            self.assertEqual(metrics["statements_decimal_risk"], 1)

    def test_boundary_cases_skip_random_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(2)."],
                ["COMPUTE WS-A = WS-B / 5."],
            )
            with (
                mock.patch("experiment.random_cases", return_value=[(0, 13)]),
                mock.patch(
                    "experiment.boundary_cases",
                    return_value=[("tie", 0, (0, 13)), ("over", 0, (0, 18))],
                ),
                mock.patch("experiment.run", return_value=[((2,), False), ((3,), False)]),
            ):
                metrics, records = experiment.experiment(root)

            record = records[0]
            self.assertEqual(record["cases_random"], 1)
            self.assertEqual(record["cases_boundary"], 1)
            self.assertEqual(record["float_round"]["cases_differ_boundary"], 1)
            self.assertEqual(metrics["cases_boundary"], 1)

    def test_storage_differences_are_not_counted_as_arithmetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                ["01 WS-A PIC 9(2).", "01 WS-B PIC 9(3)."],
                ["COMPUTE WS-A = WS-B."],
            )
            with (
                mock.patch("experiment.random_cases", return_value=[(0, 123)]),
                mock.patch("experiment.boundary_cases", return_value=[]),
                mock.patch("experiment.run", return_value=[((23,), False)]),
            ):
                metrics, records = experiment.experiment(root)

            record = records[0]
            self.assertEqual(record["cobol_exact_cases_differ"], 0)
            self.assertEqual(record["exact_no_size"]["cases_differ_storage"], 1)
            self.assertEqual(record["exact_no_size"]["cases_differ_arithmetic"], 0)
            self.assertEqual(record["float_round"]["cases_differ_storage"], 1)
            self.assertEqual(metrics["exact_no_size_statements_differ"], 1)
            self.assertEqual(metrics["exact_no_size_statements_differ_arithmetic"], 0)
            self.assertEqual(metrics["exact_no_size_cases_differ_storage"], 1)
            self.assertEqual(metrics["exact_no_size_cases_differ_arithmetic"], 0)
            self.assertEqual(metrics["statements_flag_size"], 1)

    def test_writes_are_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(2)."],
                ["COMPUTE WS-A = WS-B / 5."],
            )
            first = Path(tmp) / "first" / "metrics.json"
            second = Path(tmp) / "second" / "metrics.json"
            with (
                mock.patch("experiment.random_cases", return_value=[(0, 13)]),
                mock.patch("experiment.boundary_cases", return_value=[]),
                mock.patch("experiment.run", return_value=[((2,), False)]),
            ):
                experiment.main(["--root", str(root), "--out", str(first)])
                experiment.main(["--root", str(root), "--out", str(second)])

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                (first.parent / "statements.jsonl").read_bytes(),
                (second.parent / "statements.jsonl").read_bytes(),
            )
            metrics = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(metrics["cases_random"], 1)


@unittest.skipUnless(COBC, "no GnuCOBOL compiler available")
class RealHarnessTest(unittest.TestCase):
    def test_one_statement_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(
                tmp,
                ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(2)."],
                ["COMPUTE WS-A = WS-B / 5."],
            )
            with (
                mock.patch("experiment.random_cases", return_value=[(0, 13)]),
                mock.patch("experiment.boundary_cases", return_value=[]),
            ):
                metrics, records = experiment.experiment(root)

            record = records[0]
            self.assertEqual(record["cobol_exact_cases_differ"], 0)
            self.assertEqual(metrics["cobol_exact_agreement"], 1.0)
            self.assertEqual(metrics["cases_random"], 1)


if __name__ == "__main__":
    unittest.main()
