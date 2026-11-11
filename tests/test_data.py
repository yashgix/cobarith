import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from cobarith.data import binary_bits, find_item, parse_data, parse_pic
from cobarith.source import tokenize_file


def fixed(seq: str, indicator: str, code: str) -> str:
    return f"{seq}{indicator}{code}"


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


COBC = os.environ.get("ARCTURUS_COBC") or shutil.which("cobc")


def program(storage: list[str], files: list[str] = ()) -> list[str]:
    head = ["IDENTIFICATION DIVISION.", "PROGRAM-ID. TEST."]
    if files:
        head += [
            "ENVIRONMENT DIVISION.",
            "INPUT-OUTPUT SECTION.",
            "FILE-CONTROL.",
            "    SELECT IN-FILE ASSIGN TO 'IN.DAT' ORGANIZATION IS SEQUENTIAL.",
            "DATA DIVISION.",
            "FILE SECTION.",
            *files,
        ]
    else:
        head.append("DATA DIVISION.")
    body = head + ["WORKING-STORAGE SECTION.", *storage, "PROCEDURE DIVISION.", "    STOP RUN."]
    return [fixed(f"{n:06d}", " ", line) for n, line in enumerate(body, 1)]


def items_of(lines: list[str]) -> list[tuple[str, int, str | None]]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "T.cbl"
        write(path, lines)
        return [(i.name, i.level, i.pic.text if i.pic else None) for i in parse_data(tokenize_file(path))]


def gnucobol_accepts(lines: list[str]) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "T.cbl"
        write(path, lines)
        return subprocess.run([COBC, "-std=ibm", "-fsyntax-only", str(path)], capture_output=True).returncode == 0


class PicTest(unittest.TestCase):
    def test_numeric_picture(self) -> None:
        pic = parse_pic("S9(09)V99")
        self.assertEqual(pic.kind, "numeric")
        self.assertEqual((pic.digits, pic.scale, pic.signed), (9, 2, True))
        self.assertEqual(pic.capacity, 10**11 - 1)

        self.assertEqual((parse_pic("9(02)").digits, parse_pic("9(02)").scale), (2, 0))
        self.assertTrue(parse_pic("S9(4)").signed)
        self.assertFalse(parse_pic("9(4)").signed)

    def test_edited_pictures(self) -> None:
        pic = parse_pic("-ZZZ,ZZ9.99")
        self.assertEqual(pic.kind, "edited")
        self.assertEqual((pic.digits, pic.scale, pic.signed), (6, 2, True))

        pic = parse_pic("$$$,$$9.99")
        self.assertEqual(pic.kind, "edited")
        self.assertEqual((pic.digits, pic.scale, pic.signed), (5, 2, False))

        pic = parse_pic("+9(3).99")
        self.assertEqual((pic.digits, pic.scale, pic.signed), (3, 2, True))
        self.assertTrue(parse_pic("ZZZ9CR").signed)
        self.assertTrue(parse_pic("ZZZ9DB").signed)

    def test_alnum_and_p_scaling(self) -> None:
        self.assertEqual(parse_pic("X(08)").kind, "alnum")
        self.assertEqual(parse_pic("X(08)").digits, 8)
        self.assertEqual(parse_pic("A(3)").kind, "alnum")
        self.assertEqual(parse_pic("N(3)").kind, "alnum")

        pic = parse_pic("9(3)P(2)")
        self.assertEqual(pic.kind, "scaled")
        self.assertEqual(pic.digits, 3)

    def test_binary_bits_thresholds(self) -> None:
        self.assertEqual(binary_bits(parse_pic("S9(4)")), 16)
        self.assertEqual(binary_bits(parse_pic("S9(5)")), 32)
        self.assertEqual(binary_bits(parse_pic("S9(9)")), 32)
        self.assertEqual(binary_bits(parse_pic("S9(10)")), 64)
        self.assertEqual(binary_bits(parse_pic("S9(08)V9")), 32)


class DataItemTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "T.cbl"
        write(
            path,
            [
                fixed("000100", " ", "IDENTIFICATION DIVISION."),
                fixed("000200", " ", "PROGRAM-ID. TEST."),
                fixed("000300", " ", "DATA DIVISION."),
                fixed("000400", " ", "WORKING-STORAGE SECTION."),
                fixed("000500", " ", "01 TOP-G."),
                fixed("000600", " ", "  05 MID-G."),
                fixed("000700", " ", "    10 FIELD-A PIC S9(3) COMP."),
                fixed("000800", " ", "  05 FIELD-A PIC 9(2)."),
                fixed("000900", " ", "01 OTHER-G."),
                fixed("001000", " ", "  05 FIELD-A PIC 9(4)."),
                fixed("001100", " ", "  05 WS-TABLE PIC X(2) OCCURS 3 INDEXED BY WS-IDX."),
                fixed("001200", " ", "  05 FLAG PIC X."),
                fixed("001300", " ", "    88 FLAG-ON VALUE 'Y'."),
                fixed("001400", " ", "01 COMP-G COMP."),
                fixed("001500", " ", "  05 COMP-FIELD PIC 9(4)."),
                fixed("001600", " ", "77 WS-ALONE PIC 9(5)."),
                fixed("001700", " ", "PROCEDURE DIVISION."),
            ],
        )
        self.division = parse_data(tokenize_file(path))

    def test_items_and_usage_inheritance(self) -> None:
        comp_field = find_item(self.division, "COMP-FIELD", ("COMP-G",))
        self.assertIsNotNone(comp_field)
        assert comp_field is not None
        self.assertEqual(comp_field.usage, "COMP")

        alone = find_item(self.division, "WS-ALONE")
        self.assertIsNotNone(alone)
        assert alone is not None
        self.assertEqual(alone.level, 77)

    def test_qualified_name_resolution(self) -> None:
        self.assertIsNone(find_item(self.division, "FIELD-A"))

        under_mid = find_item(self.division, "FIELD-A", ("MID-G", "TOP-G"))
        self.assertIsNotNone(under_mid)
        assert under_mid is not None
        self.assertEqual(under_mid.pic.text, "S9(3)")

        under_top = find_item(self.division, "FIELD-A", ("TOP-G",))
        self.assertIsNone(under_top)

        under_other = find_item(self.division, "FIELD-A", ("OTHER-G",))
        self.assertIsNotNone(under_other)
        assert under_other is not None
        self.assertEqual(under_other.pic.text, "9(4)")

        self.assertIsNone(find_item(self.division, "FIELD-A", ("TOP-G", "MID-G")))

    def test_indexed_by_and_condition_names(self) -> None:
        index_item = find_item(self.division, "WS-IDX")
        self.assertIsNotNone(index_item)
        assert index_item is not None
        self.assertTrue(index_item.index)
        self.assertEqual(index_item.usage, "INDEX")

        self.assertIsNone(find_item(self.division, "FLAG-ON"))

    def test_data_division_exposes_items(self) -> None:
        self.assertEqual(len(self.division.items), len(self.division))
        self.assertTrue(any(item.name == "TOP-G" for item in self.division.items))


class EntryBoundaryTest(unittest.TestCase):
    """Where one data entry ends. GnuCOBOL lets the period go when the next level number starts in Area A
    (columns 8-11); a number in Area B belongs to the clause before it. The helper writes lines from column 8."""

    UNTERMINATED = {
        "a VALUE literal": ["01 G.", "    05 A PIC 9 VALUE 4", "01 B PIC 9 VALUE 7."],
        "VALUE ZERO": ["01 A PIC 9 VALUE ZERO", "01 B PIC 9 VALUE 7."],
        "a quoted VALUE": ["01 A PIC X(3) VALUE 'ABC'", "01 B PIC 9 VALUE 7."],
        "a negative VALUE": ["01 A PIC S9 VALUE -5", "01 B PIC 9 VALUE 7."],
        "an 88 with a VALUES list": [
            "01 G.",
            "    05 A PIC 9 VALUE 2.",
            "      88 A-OK VALUES 1 2 3",
            "01 B PIC 9 VALUE 7.",
        ],
        "OCCURS ... DEPENDING ON": [
            "01 N PIC 9 VALUE 3.",
            "01 G.",
            "    05 A PIC 9 OCCURS 1 TO 5 TIMES DEPENDING ON N",
            "01 B PIC 9 VALUE 7.",
        ],
        "INDEXED BY": ["01 G.", "    05 A PIC 9 OCCURS 3 INDEXED BY IX", "01 B PIC 9 VALUE 7."],
        "a 77 before a 77": ["77 A PIC 9 VALUE 4", "77 B PIC 9 VALUE 7."],
        "an 01 before a 77": ["01 A PIC 9 VALUE 1", "77 B PIC 9 VALUE 7."],
        "level 1 written without its zero": ["01 A PIC 9 VALUE 1", "1 B PIC 9 VALUE 7."],
        "a group header": ["01 G", "01 B PIC 9 VALUE 7."],
        "an 05 in Area A": ["01 G.", "    05 A PIC 9 VALUE 4", "05 B PIC 9 VALUE 7."],
        "an 05 in Area A after PIC": ["01 G.", "    05 A PIC S9 SIGN LEADING SEPARATE", "05 B PIC 9."],
    }

    def test_an_entry_without_its_period_ends_at_a_level_in_area_a(self) -> None:
        for label, storage in self.UNTERMINATED.items():
            with self.subTest(label):
                found = items_of(program(storage))
                self.assertIn(("B", int(storage[-1].split()[0]), "9"), found)
                if COBC and label != "a group header":  # GnuCOBOL wants a PICTURE for an empty 01 G
                    self.assertTrue(gnucobol_accepts(program(storage)), label)

    def test_the_entry_before_keeps_its_own_clauses(self) -> None:
        found = items_of(program(self.UNTERMINATED["a VALUE literal"]))
        self.assertEqual(found, [("G", 1, None), ("A", 5, "9"), ("B", 1, "9")])

    def test_numbers_inside_clauses_never_start_an_entry(self) -> None:
        storage = [
            "01 N PIC 9 VALUE 1.",
            "01 G.",
            "    05 A PIC 9 OCCURS 1 TO 5 TIMES DEPENDING ON N.",
            "    05 C PIC 99 VALUE IS 1.",
            "      88 C-SET VALUES 1 THRU 77.",
            "    05 D PIC 9 OCCURS 1 TIMES.",
        ]
        self.assertEqual(
            items_of(program(storage)), [("N", 1, "9"), ("G", 1, None), ("A", 5, "9"), ("C", 5, "99"), ("D", 5, "9")]
        )

    def test_file_descriptions_are_not_items(self) -> None:
        files = [
            "FD IN-FILE",
            "    RECORDING MODE IS V",
            "    BLOCK CONTAINS 1 RECORDS",
            "    RECORD IS VARYING IN SIZE FROM 10 TO 80 DEPENDING ON WS-LEN.",
            "01 IN-REC PIC X(80).",
        ]
        lines = program(["01 WS-LEN PIC 9(4) COMP."], files)
        self.assertEqual(items_of(lines), [("IN-REC", 1, "X(80)"), ("WS-LEN", 1, "9(4)")])
        if COBC:
            self.assertTrue(gnucobol_accepts(lines))


if __name__ == "__main__":
    unittest.main()
