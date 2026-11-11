import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from cobarith.cases import boundary_cases, random_cases
from cobarith.data import parse_data
from cobarith.source import tokenize_file
from cobarith.stmt import parse_statements
from cobarith.translate import exact_results


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


def parse_program(data: list[str], procedure: list[str], program: str = "TEST") -> list:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{program}.cbl"
        write(path, program_lines(data, procedure))
        tokens = tokenize_file(path)
        items = parse_data(tokens)
        return parse_statements(tokens, program, items, path.name)


class RandomCasesTest(unittest.TestCase):
    def test_repeatable_and_sized(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(4)."],
            ["ADD WS-A TO WS-B."],
        )[0]
        first = random_cases(statement, n=25)
        second = random_cases(statement, n=25)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 25)
        self.assertTrue(all(len(case) == 2 for case in first))

    def test_parity_ranges(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(9)."], ["ADD WS-A TO WS-A."])[0]
        cases = random_cases(statement, n=100)
        pic = statement.variables[0].pic
        self.assertIsNotNone(pic)
        assert pic is not None
        even_top = min(pic.capacity, 10 ** (pic.scale + min(pic.digits, 5)) - 1)
        for index, case in enumerate(cases):
            top = pic.capacity if index % 2 == 1 else even_top
            self.assertLessEqual(abs(case[0]), top)
        self.assertTrue(any(abs(cases[index][0]) > even_top for index in range(1, len(cases), 2)))

    def test_zero_divisors_are_redrawn(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(3).", "01 WS-C PIC S9(3)."],
            ["COMPUTE WS-C = WS-A / WS-B."],
        )[0]
        divisor = next(index for index, variable in enumerate(statement.variables) if variable.name == "WS-B")
        cases = random_cases(statement, n=50)
        for case in cases:
            self.assertNotEqual(case[divisor], 0)
            exact_results(statement, case)


class BoundaryCasesTest(unittest.TestCase):
    def test_scale_tie_and_exact_hold(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(3)."], ["COMPUTE WS-A = WS-A / 2."])[0]
        self.assertIsNotNone(statement.flags)
        assert statement.flags is not None
        self.assertTrue(statement.flags["scale"])
        results = boundary_cases(statement)
        kinds = {kind for kind, _, _ in results}
        self.assertIn("tie", kinds)
        self.assertIn("exact", kinds)
        self.assertEqual(results, boundary_cases(statement))
        for kind, target_index, case in results:
            assignment = statement.assignments[target_index]
            pic = statement.variables[assignment.target].pic
            self.assertIsNotNone(pic)
            assert pic is not None
            value = exact_results(statement, case)[target_index]
            scaled = value * 10**pic.scale
            if kind == "tie":
                self.assertEqual(scaled.denominator, 2)
            elif kind == "exact":
                self.assertEqual(scaled.denominator, 1)
            else:
                self.fail(f"unexpected kind {kind}")

    def test_size_and_sign_kinds_hold(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC 9(2).", "01 WS-B PIC S9(3)."],
            ["COMPUTE WS-A = WS-B."],
        )[0]
        self.assertIsNotNone(statement.flags)
        assert statement.flags is not None
        self.assertTrue(statement.flags["size"])
        self.assertTrue(statement.flags["sign"])
        results = boundary_cases(statement)
        kinds = {kind for kind, _, _ in results}
        self.assertIn("over", kinds)
        self.assertIn("negative", kinds)
        for kind, target_index, case in results:
            assignment = statement.assignments[target_index]
            pic = statement.variables[assignment.target].pic
            self.assertIsNotNone(pic)
            assert pic is not None
            value = exact_results(statement, case)[target_index]
            scaled = value * 10**pic.scale
            if kind == "over":
                self.assertGreaterEqual(abs(value), Fraction(pic.capacity + 1, 10**pic.scale))
            elif kind == "negative":
                self.assertLessEqual(scaled, -1)
            else:
                self.fail(f"unexpected kind {kind}")

    def test_no_flags_returns_empty(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(5)."], ["COMPUTE WS-A = 1."])[0]
        self.assertIsNotNone(statement.flags)
        assert statement.flags is not None
        self.assertFalse(any(statement.flags.values()))
        self.assertEqual(boundary_cases(statement), [])


if __name__ == "__main__":
    unittest.main()
