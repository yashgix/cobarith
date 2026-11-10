"""Tests for the COBOL storage rule and plausible Python translations."""

import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from cobarith.data import parse_data, parse_pic
from cobarith.source import tokenize_file
from cobarith.stmt import parse_statements
from cobarith.translate import (
    TRANSLATIONS,
    exact_results,
    scale_units,
    storage_changed,
    store,
    translate,
)


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


class ScaleUnitsTest(unittest.TestCase):
    def test_truncation_and_rounding(self) -> None:
        self.assertEqual(scale_units(Fraction(1234, 1000), 2, False), 123)
        self.assertEqual(scale_units(Fraction(1234, 1000), 2, True), 123)
        self.assertEqual(scale_units(Fraction(1235, 1000), 2, False), 123)
        self.assertEqual(scale_units(Fraction(1235, 1000), 2, True), 124)

        self.assertEqual(scale_units(Fraction(-1235, 1000), 2, False), -123)
        self.assertEqual(scale_units(Fraction(-1235, 1000), 2, True), -124)

        self.assertEqual(scale_units(Fraction(5, 2), 0, False), 2)
        self.assertEqual(scale_units(Fraction(5, 2), 0, True), 3)
        self.assertEqual(scale_units(Fraction(-5, 2), 0, False), -2)
        self.assertEqual(scale_units(Fraction(-5, 2), 0, True), -3)


class StoreTest(unittest.TestCase):
    def test_display_size_error_and_low_order_digits(self) -> None:
        signed = parse_pic("S9(3)")
        unsigned = parse_pic("9(3)")

        self.assertEqual(store(1234, signed, "DISPLAY", 7, False), (234, False))
        self.assertEqual(store(1234, signed, "DISPLAY", 7, True), (7, True))
        self.assertEqual(store(-1234, signed, "DISPLAY", 7, False), (-234, False))
        self.assertEqual(store(999, signed, "DISPLAY", 7, True), (999, False))

        self.assertEqual(store(-5, unsigned, "DISPLAY", 7, False), (5, False))
        self.assertEqual(store(-1234, unsigned, "DISPLAY", 7, False), (234, False))
        self.assertEqual(store(-1234, unsigned, "DISPLAY", 7, True), (7, True))
        self.assertEqual(store(1000, unsigned, "DISPLAY", 0, False), (0, False))

    def test_comp_keeps_pic_width_until_binary_range(self) -> None:
        comp16 = parse_pic("S9(4)")
        comp_unsigned16 = parse_pic("9(4)")
        comp32 = parse_pic("S9(9)")

        self.assertEqual(store(12345, comp16, "COMP", 1, False), (12345, False))
        self.assertEqual(store(40000, comp16, "COMP", 1, False), (-25536, False))
        self.assertEqual(store(40000, comp16, "COMP", 1, True), (1, True))

        self.assertEqual(store(-1, comp_unsigned16, "COMP", 5, False), (1, False))
        self.assertEqual(store(70000, comp_unsigned16, "COMP", 5, False), (4464, False))

        self.assertEqual(store(2147483648, comp32, "COMP", 0, False), (-2147483648, False))

    def test_comp5_uses_the_same_binary_rule(self) -> None:
        pic = parse_pic("S9(4)")
        self.assertEqual(store(40000, pic, "COMP-5", 1, False), (-25536, False))


class ExactResultsTest(unittest.TestCase):
    DATA = [
        "01 WS-A PIC S9(3).",
        "01 WS-B PIC S9(4).",
        "01 WS-C PIC S9(6).",
    ]

    def test_add_and_subtract_forms(self) -> None:
        statement = parse_program(self.DATA, ["ADD WS-A TO WS-B."])[0]
        self.assertEqual(exact_results(statement, [5, 10]), [Fraction(15)])

        statement = parse_program(self.DATA, ["ADD WS-A WS-B GIVING WS-C."])[0]
        self.assertEqual(exact_results(statement, [5, 10, 0]), [Fraction(15)])

        statement = parse_program(self.DATA, ["SUBTRACT WS-A FROM WS-B."])[0]
        self.assertEqual(exact_results(statement, [5, 10]), [Fraction(5)])

        statement = parse_program(self.DATA, ["SUBTRACT WS-A FROM WS-B GIVING WS-C."])[0]
        self.assertEqual(exact_results(statement, [5, 10, 0]), [Fraction(5)])

    def test_multiply_divide_and_compute_forms(self) -> None:
        statement = parse_program(self.DATA, ["MULTIPLY WS-A BY WS-B."])[0]
        self.assertEqual(exact_results(statement, [5, 10]), [Fraction(50)])

        statement = parse_program(self.DATA, ["MULTIPLY WS-A BY WS-B GIVING WS-C."])[0]
        self.assertEqual(exact_results(statement, [5, 10, 0]), [Fraction(50)])

        statement = parse_program(self.DATA, ["DIVIDE WS-A INTO WS-B."])[0]
        self.assertEqual(exact_results(statement, [5, 10]), [Fraction(2)])

        statement = parse_program(self.DATA, ["DIVIDE WS-A INTO WS-B GIVING WS-C."])[0]
        self.assertEqual(exact_results(statement, [5, 10, 0]), [Fraction(2)])

        statement = parse_program(self.DATA, ["DIVIDE WS-A BY WS-B GIVING WS-C."])[0]
        self.assertEqual(exact_results(statement, [5, 10, 0]), [Fraction(1, 2)])

        statement = parse_program(self.DATA, ["COMPUTE WS-C = WS-A + WS-B * 2."])[0]
        self.assertEqual(exact_results(statement, [0, 5, 10]), [Fraction(25)])

    def test_field_scale_is_applied(self) -> None:
        data = [
            "01 WS-A PIC S9(3)V99.",
            "01 WS-B PIC 9(1).",
            "01 WS-C PIC S9(5)V99.",
        ]
        statement = parse_program(data, ["COMPUTE WS-C = WS-A / WS-B."])[0]
        self.assertEqual(exact_results(statement, [0, 135, 1]), [Fraction(135, 100)])


class TranslateTest(unittest.TestCase):
    def test_translations_have_the_documented_keys(self) -> None:
        data = ["01 WS-A PIC S9(3).", "01 WS-B PIC S9(4)."]
        statement = parse_program(data, ["ADD WS-A TO WS-B."])[0]
        results = translate(statement, [1, 2])
        self.assertEqual(tuple(results), TRANSLATIONS)
        self.assertTrue(all(len(values) == 1 for values in results.values()))

    def test_floating_rounding_differs_from_truncating_cobol(self) -> None:
        data = [
            "01 WS-A PIC S9(3)V999.",
            "01 WS-B PIC 9(1).",
            "01 WS-C PIC S9(2)V99.",
        ]
        statement = parse_program(data, ["COMPUTE WS-C = WS-A / WS-B."])[0]
        results = translate(statement, [0, 999, 1])

        self.assertEqual(results["cobol_exact"], [99])
        self.assertEqual(results["exact_no_size"], [99])
        self.assertEqual(results["float_round"], [100])
        self.assertEqual(results["decimal_half_even"], [100])
        self.assertEqual(results["float_truncate"], [99])

    def test_decimal_half_even_rounds_the_tie_away_from_truncation(self) -> None:
        data = [
            "01 WS-A PIC S9(3)V999.",
            "01 WS-B PIC 9(1).",
            "01 WS-C PIC S9(2)V99.",
        ]
        statement = parse_program(data, ["COMPUTE WS-C = WS-A / WS-B."])[0]
        results = translate(statement, [0, 135, 1])

        self.assertEqual(results["cobol_exact"], [13])
        self.assertEqual(results["exact_no_size"], [13])
        self.assertEqual(results["decimal_half_even"], [14])

    def test_float_truncate_can_lose_one_unit(self) -> None:
        data = [
            "01 WS-A PIC S9(2)V99.",
            "01 WS-B PIC 9(1).",
            "01 WS-C PIC S9(2)V99.",
        ]
        statement = parse_program(data, ["COMPUTE WS-C = WS-A / WS-B."])[0]
        results = translate(statement, [0, 29, 1])

        self.assertEqual(results["cobol_exact"], [29])
        self.assertEqual(results["exact_no_size"], [29])
        self.assertEqual(results["float_round"], [29])
        self.assertEqual(results["decimal_half_even"], [29])
        self.assertEqual(results["float_truncate"], [28])

    def test_exact_no_size_honours_rounded_but_python_translations_do_not(self) -> None:
        data = [
            "01 WS-A PIC S9(1).",
            "01 WS-B PIC S9(3).",
            "01 WS-C PIC S9(1).",
        ]
        statement = parse_program(data, ["COMPUTE WS-B ROUNDED = WS-A / WS-C."])[0]
        results = translate(statement, [0, 5, 2])

        self.assertEqual(results["cobol_exact"], [3])
        self.assertEqual(results["exact_no_size"], [3])
        self.assertEqual(results["float_round"], [2])
        self.assertEqual(results["decimal_half_even"], [2])
        self.assertEqual(results["float_truncate"], [2])

    def test_decimal_half_even_uses_integer_units_for_nonzero_scale(self) -> None:
        data = [
            "01 WS-A PIC S9(3)V99.",
            "01 WS-B PIC 9(1).",
            "01 WS-C PIC S9(2)V99.",
        ]
        statement = parse_program(data, ["COMPUTE WS-C = WS-A / WS-B."])[0]
        results = translate(statement, [0, 12345, 1])

        self.assertEqual(results["decimal_half_even"], [12345])

    def test_decimal_wide_multiplication_does_not_raise(self) -> None:
        data = [
            "01 WS-A PIC 9(16).",
            "01 WS-B PIC 9(16).",
            "01 WS-C PIC 9(32).",
        ]
        statement = parse_program(data, ["COMPUTE WS-C = WS-A * WS-B."])[0]
        expected = 9999999999999999**2
        results = translate(statement, [0, 9999999999999999, 9999999999999999])

        self.assertEqual(results["exact_no_size"], [expected])
        self.assertEqual(results["decimal_half_even"], [expected])


class StorageChangedTest(unittest.TestCase):
    def test_display_overflow_changes_storage(self) -> None:
        statement = parse_program(["01 WS-A PIC 9(2)."], ["COMPUTE WS-A = 123."])[0]
        self.assertEqual(translate(statement, [7])["cobol_exact"], [23])
        self.assertEqual(translate(statement, [7])["exact_no_size"], [123])
        self.assertTrue(storage_changed(statement, [7]))

    def test_comp_wrap_changes_storage(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(4) COMP."], ["COMPUTE WS-A = 40000."])[0]
        self.assertEqual(translate(statement, [1])["cobol_exact"], [-25536])
        self.assertEqual(translate(statement, [1])["exact_no_size"], [40000])
        self.assertTrue(storage_changed(statement, [1]))

    def test_size_error_keeps_prior(self) -> None:
        statement = parse_program(
            ["01 WS-A PIC 9(2)."],
            ["COMPUTE WS-A = 123 ON SIZE ERROR."],
        )[0]
        translated = translate(statement, [7])
        self.assertTrue(statement.size_error)
        self.assertEqual(translated["cobol_exact"], [7])
        self.assertEqual(translated["exact_no_size"], [123])
        self.assertTrue(storage_changed(statement, [7]))

    def test_no_storage_change_for_ordinary_value(self) -> None:
        statement = parse_program(["01 WS-A PIC S9(5)."], ["COMPUTE WS-A = 123."])[0]
        self.assertFalse(storage_changed(statement, [7]))


if __name__ == "__main__":
    unittest.main()
