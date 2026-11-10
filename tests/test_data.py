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
        self.assertEqual(binary_bits("S9(08)V9"), 32)
        self.assertEqual(binary_bits(parse_pic("S9(9)V9")), 64)


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


if __name__ == "__main__":
    unittest.main()
