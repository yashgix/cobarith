import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cobarith.data import parse_data
from cobarith.harness import program, run
from cobarith.source import tokenize_file
from cobarith.stmt import parse_statements
from cobarith.translate import translate

COBC = os.environ.get("ARCTURUS_COBC") or shutil.which("cobc")


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


def compiles(data: list[str], procedure: list[str]) -> bool:
    """Whether GnuCOBOL accepts the statements as written."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "TEST.cbl"
        write(path, program_lines(data, [*procedure, "STOP RUN."]))
        return subprocess.run([COBC, "-std=ibm", "-fsyntax-only", str(path)], capture_output=True).returncode == 0


def agrees_with_gnucobol(test: unittest.TestCase, statement, case: tuple) -> None:
    """The model's stored units (cobol_exact) equal what GnuCOBOL stores for the same case."""
    test.assertEqual(statement.status, "harnessed", statement.reason)
    expected = tuple(translate(statement, case)["cobol_exact"])
    test.assertEqual(run(statement, [case]), [(expected, False)])


def parse_program(data: list[str], procedure: list[str], program_name: str = "TEST") -> list:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"{program_name}.cbl"
        write(path, program_lines(data, procedure))
        tokens = tokenize_file(path)
        items = parse_data(tokens)
        return parse_statements(tokens, program_name, items, path.name)


class ProgramShapeTest(unittest.TestCase):
    def test_fixed_format_cases_file_and_receiving_field(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(3)."],
            ["ADD WS-A TO WS-B."],
        )[0]
        source = program(statement)
        flat = " ".join(source.split())

        self.assertIn("IDENTIFICATION DIVISION.", flat)
        self.assertIn("PROGRAM-ID. HARNESS.", flat)
        self.assertIn("SELECT CASES-FILE ASSIGN TO 'cases.txt'", flat)
        self.assertIn("ORGANIZATION IS LINE SEQUENTIAL.", flat)
        self.assertIn("05 IN-0001 PIC S9(3) SIGN LEADING SEPARATE", flat)
        self.assertIn("05 IN-0002 PIC S9(3) SIGN LEADING SEPARATE.", flat)
        self.assertIn("01 FLD-WS-A PIC S9(3).", flat)
        self.assertIn("01 FLD-WS-B PIC S9(3).", flat)
        self.assertIn("MOVE IN-0001 TO FLD-WS-A", flat)
        self.assertIn("ADD FLD-WS-A TO FLD-WS-B", flat)
        self.assertIn("DISPLAY OUT-0001", flat)
        self.assertIn("DISPLAY WS-SIZE-ERROR-FLAG", flat)
        self.assertIn("STOP RUN.", flat)

        for line in source.splitlines():
            self.assertLessEqual(len(line), 72)
            self.assertEqual(line[:7], " " * 7)

    def test_usage_and_scale_survive_into_the_declarations(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC S9(3)V99 COMP-3.", "01 WS-B PIC S9(5)V99."],
            ["COMPUTE WS-B = WS-A + 1.5."],
        )[0]
        source = program(statement)
        flat = " ".join(source.split())

        self.assertIn("01 FLD-WS-A PIC S9(3)V99 COMP-3.", flat)
        self.assertIn("01 FLD-WS-B PIC S9(5)V99.", flat)
        self.assertIn("05 IN-0002 PIC S9(3)V9(2) SIGN LEADING SEPARATE", flat)
        self.assertIn("COMPUTE FLD-WS-B = FLD-WS-A + 1.5", flat)

    def test_size_error_sets_a_flag_and_closes_the_statement(self) -> None:
        statement = parse_program(["01 WS-A PIC 9(2)."], ["COMPUTE WS-A = 123 ON SIZE ERROR."])[0]
        source = program(statement)
        flat = " ".join(source.split())

        self.assertTrue(statement.size_error)
        self.assertIn("ON SIZE ERROR MOVE 1 TO WS-SIZE-ERROR-FLAG END-COMPUTE", flat)

        plain = parse_program(["01 WS-A PIC 9(2)."], ["COMPUTE WS-A = 123."])[0]
        self.assertFalse(plain.size_error)
        self.assertNotIn("SIZE ERROR", " ".join(program(plain).split()))

    def test_binary_target_gets_a_roomy_display_field(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(4) COMP."], ["COMPUTE WS-A = 1."])[0]
        source = program(statement)
        flat = " ".join(source.split())

        self.assertIn("01 FLD-WS-A PIC S9(4) COMP.", flat)
        self.assertIn("01 OUT-0001 PIC S9(5) SIGN LEADING SEPARATE.", flat)

    def test_long_statement_wraps_inside_the_code_area(self) -> None:
        statement = parse_program(
            [
                "01 WS-A PIC S9(3).",
                "01 WS-B PIC S9(3).",
                "01 WS-C PIC S9(3).",
                "01 WS-D PIC S9(3).",
                "01 WS-E PIC S9(6).",
            ],
            ["ADD WS-A WS-B WS-C WS-D GIVING WS-E."],
        )[0]
        source = program(statement)
        flat = " ".join(source.split())

        self.assertIn(
            "ADD FLD-WS-A FLD-WS-B FLD-WS-C FLD-WS-D GIVING FLD-WS-E",
            flat,
        )
        for line in source.splitlines():
            self.assertLessEqual(len(line), 72)
            self.assertEqual(line[:7], " " * 7)

    def test_subscripts_and_clashing_names_stay_distinct(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC 9(3) OCCURS 3."],
            ["ADD WS-A(1) WS-A(1) TO WS-A(2)."],
        )[0]
        source = program(statement)
        flat = " ".join(source.split())

        self.assertIn("01 FLD-WS-A-1 PIC 9(3).", flat)
        self.assertIn("01 FLD-WS-A-2 PIC 9(3).", flat)
        self.assertEqual(flat.count("05 IN-"), 2)


class RunValidationTest(unittest.TestCase):
    DATA = ["01 WS-A PIC 9(2).", "01 WS-B PIC 9(2).", "01 WS-C PIC 9(2)."]

    def statement(self):
        return parse_program(self.DATA, ["COMPUTE WS-A = WS-B * WS-C."])[0]

    def test_case_outside_the_picture_raises(self) -> None:
        with self.assertRaises(ValueError):
            run(self.statement(), [(0, 1000, 1)])
        with self.assertRaises(ValueError):
            run(self.statement(), [(-1, 1, 1)])
        with self.assertRaises(ValueError):
            run(self.statement(), [(0, 1)])

    def test_missing_compiler_raises_value_error(self) -> None:
        with mock.patch.dict(os.environ, {"ARCTURUS_COBC": "/nonexistent/cobc-3.2"}):
            with self.assertRaises(ValueError):
                run(self.statement(), [(0, 1, 1)])


@unittest.skipUnless(COBC, "no GnuCOBOL compiler available")
class RunTest(unittest.TestCase):
    def test_display_overflow_keeps_the_low_order_digits(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC 9(2).", "01 WS-B PIC 9(2).", "01 WS-C PIC 9(2)."],
            ["COMPUTE WS-A = WS-B * WS-C."],
        )[0]
        self.assertEqual(run(statement, [(0, 50, 41)]), [((50,), False)])

    def test_size_error_keeps_the_prior_value(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC 9(2).", "01 WS-B PIC 9(2).", "01 WS-C PIC 9(2)."],
            ["COMPUTE WS-A = WS-B * WS-C ON SIZE ERROR."],
        )[0]
        self.assertEqual(run(statement, [(7, 50, 41)]), [((7,), True)])

    def test_comp_wraps_at_its_binary_width(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC S9(4) COMP.", "01 WS-B PIC S9(3).", "01 WS-C PIC S9(3)."],
            ["COMPUTE WS-A = WS-B * WS-C."],
        )[0]
        self.assertEqual(run(statement, [(0, 200, 200)]), [((-25536,), False)])

    def test_division_truncates_toward_zero(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC S9(3)V99.", "01 WS-B PIC S9(2)V99."],
            ["COMPUTE WS-B = WS-A / 3."],
        )[0]
        self.assertEqual(run(statement, [(0, 100)]), [((33,), False)])

    def test_rounded_halves_go_away_from_zero(self) -> None:
        data = ["01 WS-A PIC S9(3)V99.", "01 WS-B PIC S9(2)V99."]
        rounded = parse_program(data, ["COMPUTE WS-B ROUNDED = WS-A / 2."])[0]
        plain = parse_program(data, ["COMPUTE WS-B = WS-A / 2."])[0]

        self.assertEqual(run(rounded, [(0, 125)]), [((63,), False)])
        self.assertEqual(run(plain, [(0, 125)]), [((62,), False)])

    def test_several_cases_run_in_order(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC 9(2).", "01 WS-B PIC 9(2).", "01 WS-C PIC 9(2)."],
            ["COMPUTE WS-A = WS-B * WS-C."],
        )[0]
        results = run(statement, [(0, 1, 2), (0, 50, 41), (0, 0, 9)])
        self.assertEqual(results, [((2,), False), ((50,), False), ((0,), False)])


if __name__ == "__main__":
    unittest.main()


class SourceFormatTest(unittest.TestCase):
    """Renamed statements must stay valid fixed-format COBOL and mean what they meant."""

    FIELDS = [f"01 WS-{c} PIC S9(3)." for c in "ABCDEFGHI"] + ["01 WS-T PIC S9(5)."]

    def test_a_long_unspaced_expression_stays_in_the_code_area_and_runs(self) -> None:
        statement = parse_program(self.FIELDS, ["COMPUTE WS-T=WS-A+WS-B+WS-C+WS-D+WS-E+WS-F+WS-G+WS-H+WS-I."])[0]
        source = program(statement)
        for line in source.splitlines():
            self.assertLessEqual(len(line), 72, line)
        case = (0, *range(1, 10))
        self.assertEqual(run(statement, [case]), [((45,), False)])

    def test_a_touching_minus_after_an_operand_is_subtraction(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(3).", "01 WS-T PIC S9(3)."], ["COMPUTE WS-T = WS-A -1."])[0]
        self.assertEqual(run(statement, [(0, 10)]), [((9,), False)])

    def test_a_unary_sign_stays_on_its_literal(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(3)."], ["ADD +1 TO WS-A."])[0]
        self.assertIn("ADD +1 TO", " ".join(program(statement).split()))
        self.assertEqual(run(statement, [(41,)]), [((42,), False)])

    def test_a_word_that_cannot_fit_is_refused(self) -> None:
        from cobarith.harness import _wrap

        with self.assertRaises(ValueError):
            _wrap("X" * 70, " " * 4)


class OtherVerbsRunTest(unittest.TestCase):
    """Verbs other than COMPUTE, checked against GnuCOBOL rather than only parsed."""

    FIELDS = ["01 WS-A PIC S9(3)V9.", "01 WS-B PIC S9(3)V9.", "01 WS-C PIC S9(5)V9.", "01 WS-D PIC S9(5)V9."]

    def check(self, statement_text: str, case: tuple, expected: tuple) -> None:
        statement = parse_program(self.FIELDS, [statement_text])[0]
        self.assertEqual(statement.status, "harnessed", statement.reason)
        self.assertEqual(run(statement, [case]), [(expected, False)])

    def test_multiply_by_and_giving(self) -> None:
        self.check("MULTIPLY WS-A BY WS-B.", (25, 40), (100,))
        self.check("MULTIPLY WS-A BY WS-B GIVING WS-C.", (25, 40, 0), (100,))

    def test_divide_into_and_by_giving(self) -> None:
        self.check("DIVIDE WS-A INTO WS-B.", (30, 100), (33,))
        self.check("DIVIDE WS-A BY WS-B GIVING WS-C ROUNDED.", (100, 30, 0), (33,))

    def test_subtract_giving_and_add_to_two_targets(self) -> None:
        self.check("SUBTRACT WS-A FROM WS-B GIVING WS-C.", (15, 100, 0), (85,))
        self.check("ADD WS-A TO WS-C WS-D.", (15, 100, 200), (115, 215))


@unittest.skipUnless(COBC, "no GnuCOBOL compiler available")
class LiteralOperandTest(unittest.TestCase):
    """Numeric literals and ZERO are operands in every form, also right before GIVING."""

    FIELDS = ["01 WS-A PIC S9(3)V9.", "01 WS-C PIC S9(5)V99."]

    def test_literals_before_giving_agree_with_gnucobol(self) -> None:
        for text in (
            "SUBTRACT WS-A FROM 100 GIVING WS-C.",
            "SUBTRACT 1 FROM ZERO GIVING WS-C.",
            "SUBTRACT WS-A FROM -5 GIVING WS-C.",
            "MULTIPLY WS-A BY 2.5 GIVING WS-C.",
            "MULTIPLY 2 BY 3 GIVING WS-C.",
            "DIVIDE WS-A INTO 1000 GIVING WS-C.",
            "DIVIDE WS-A BY 4 GIVING WS-C ROUNDED.",
            "DIVIDE 2 INTO 8 GIVING WS-C.",
            "DIVIDE 7 BY 2 GIVING WS-C.",
        ):
            with self.subTest(text):
                statement = parse_program(self.FIELDS, [text])[0]
                case = tuple(-125 if v.name == "WS-A" else 0 for v in statement.variables)
                agrees_with_gnucobol(self, statement, case)

    def test_a_literal_cannot_receive_the_result(self) -> None:
        for text in ("MULTIPLY WS-A BY 3.", "DIVIDE WS-A INTO 8.", "SUBTRACT WS-A FROM 5."):
            with self.subTest(text):
                self.assertEqual(parse_program(self.FIELDS, [text])[0].reason, "syntax")
                self.assertFalse(compiles(self.FIELDS, [text]))
