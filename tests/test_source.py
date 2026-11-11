import tempfile
import unittest
from pathlib import Path

from cobarith import DATA_DIR
from cobarith.source import Library, source_tokens, tokenize_file


def fixed(seq: str, indicator: str, code: str) -> str:
    return f"{seq}{indicator}{code}"


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TokenizerTest(unittest.TestCase):
    def test_token_kinds_positions_and_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "T.cbl"
            write(
                path,
                [
                    fixed("000100", " ", "IDENTIFICATION DIVISION."),
                    fixed("000200", " ", "PROGRAM-ID. TEST."),
                    fixed("000300", " ", "DATA DIVISION."),
                    fixed("000400", " ", "WORKING-STORAGE SECTION."),
                    fixed("000500", " ", "01 WS-A PIC S9(09)V99."),
                    fixed("000600", " ", "01 WS-B PIC X(08) VALUE 'DON''T'."),
                    fixed("000700", " ", "01 WS-C PIC 9(02) VALUE 1.5."),
                    fixed("000800", "*", "COMMENT LINE"),
                    fixed("000900", "D", "DEBUG LINE"),
                    fixed("001000", " ", "MOVE A, B; TO C."),
                ],
            )

            tokens = tokenize_file(path)
            texts = [t.text for t in tokens]

            self.assertEqual(tokens[0].text, "IDENTIFICATION")
            self.assertEqual(tokens[0].kind, "word")
            self.assertEqual(tokens[0].line, 1)
            self.assertEqual(tokens[0].col, 0)

            pic_index = texts.index("PIC")
            self.assertEqual(tokens[pic_index + 1].kind, "pic")
            self.assertEqual(tokens[pic_index + 1].text, "S9(09)V99")
            self.assertEqual(tokens[pic_index + 2].text, ".")

            self.assertIn("'DON''T'", texts)
            self.assertIn("1.5", texts)
            self.assertNotIn("COMMENT", texts)
            self.assertNotIn("DEBUG", texts)
            self.assertNotIn(",", texts)
            self.assertNotIn(";", texts)

    def test_picture_is_and_trailing_period(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "T.cbl"
            write(
                path,
                [
                    fixed("000100", " ", "01 WS-A PICTURE IS 9(02) VALUE ZERO."),
                    fixed("000200", " ", "01 WS-B PIC -ZZZ,ZZ9.99."),
                ],
            )

            tokens = tokenize_file(path)
            texts = [t.text for t in tokens]

            self.assertIn("PICTURE", texts)
            self.assertNotIn("IS", texts)
            picture_index = texts.index("PICTURE")
            self.assertEqual(tokens[picture_index + 1].kind, "pic")
            self.assertEqual(tokens[picture_index + 1].text, "9(02)")
            self.assertEqual(tokens[picture_index + 2].text, "VALUE")

            self.assertIn("-ZZZ,ZZ9.99", texts)
            self.assertEqual(texts.count("."), 2)

    def test_word_continuation_joins_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "T.cbl"
            write(
                path,
                [
                    fixed("000100", " ", "MOVE ABC"),
                    fixed("000200", "-", "DEF TO WS-X."),
                ],
            )

            texts = [t.text for t in tokenize_file(path)]
            self.assertIn("ABCDEF", texts)
            self.assertNotIn("ABC", texts)

    def test_literal_continuation_pads_previous_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "T.cbl"
            write(
                path,
                [
                    fixed("000100", " ", "MOVE 'ABC"),
                    fixed("000200", "-", "'DEF' TO WS-X."),
                ],
            )

            tokens = tokenize_file(path)
            literals = [t for t in tokens if t.kind == "lit"]
            self.assertEqual(len(literals), 1)
            self.assertTrue(literals[0].text.startswith("'ABC"))
            self.assertTrue(literals[0].text.endswith("DEF'"))
            self.assertGreater(len(literals[0].text), len("'ABCDEF'"))


class LibraryTest(unittest.TestCase):
    def test_longest_path_prefix_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            program = root / "a" / "b" / "cbl" / "PROG.cbl"
            write(program, [fixed("000100", " ", "COPY FOO.")])
            write(
                root / "a" / "cpy" / "FOO.cpy",
                [fixed("000100", " ", "01 WS-A PIC 9(01) VALUE 1.")],
            )
            write(
                root / "a" / "b" / "cpy" / "FOO.cpy",
                [fixed("000100", " ", "01 WS-A PIC 9(01) VALUE 2.")],
            )

            tokens = source_tokens(program, Library(root))
            texts = [t.text for t in tokens]
            self.assertIn("2", texts)
            self.assertNotIn("1", texts)

    def test_missing_copybook_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            program = root / "PROG.cbl"
            write(program, [fixed("000100", " ", "COPY NOPE.")])

            library = Library(root)
            tokens = source_tokens(program, library)
            self.assertIn("NOPE", library.missing)
            self.assertNotIn("COPY", [t.text for t in tokens])

    def test_replacing_pseudo_text_inside_word(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "MEM.cpy",
                [fixed("000100", " ", "01 FLG-(TESTVAR1)-BLANK PIC X.")],
            )
            program = root / "PROG.cbl"
            write(
                program,
                [
                    fixed(
                        "000100",
                        " ",
                        "COPY MEM REPLACING ==(TESTVAR1)== BY ==ABC==.",
                    )
                ],
            )

            texts = [t.text for t in source_tokens(program, Library(root))]
            self.assertIn("FLG-ABC-BLANK", texts)
            self.assertNotIn("TESTVAR1", texts)

    def test_replacing_word_only_whole_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "MEM.cpy",
                [
                    fixed("000100", " ", "01 WS-OLD PIC X."),
                    fixed("000200", " ", "01 WS-OLDER PIC X."),
                ],
            )
            program = root / "PROG.cbl"
            write(
                program,
                [fixed("000100", " ", "COPY MEM REPLACING WS-OLD BY WS-NEW.")],
            )

            texts = [t.text for t in source_tokens(program, Library(root))]
            self.assertIn("WS-NEW", texts)
            self.assertIn("WS-OLDER", texts)
            self.assertNotIn("WS-OLD", texts)

    def test_quoted_member_name_dcl_file_and_literal_replacing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "decl" / "TRTYP.DCL", [fixed("000100", " ", "01 WS-CODE PIC X(3) VALUE 'OLD'.")])
            program = root / "PROG.cbl"
            write(program, [fixed("000100", " ", "COPY 'trtyp' REPLACING 'OLD' BY 'NEW'.")])

            library = Library(root)
            texts = [t.text for t in source_tokens(program, library)]
            self.assertIn("WS-CODE", texts)
            self.assertIn("'NEW'", texts)
            self.assertNotIn("'OLD'", texts)
            self.assertEqual(library.missing, set())

    def test_exec_sql_include(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "MEM.cpy",
                [fixed("000100", " ", "01 WS-SQL PIC X.")],
            )
            program = root / "PROG.cbl"
            write(
                program,
                [fixed("000100", " ", "EXEC SQL INCLUDE MEM END-EXEC.")],
            )

            texts = [t.text for t in source_tokens(program, Library(root))]
            self.assertIn("WS-SQL", texts)
            for removed in ("EXEC", "SQL", "INCLUDE", "END-EXEC"):
                self.assertNotIn(removed, texts)

    def test_recursive_copy_stops_at_depth_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "A.cpy", [fixed("000100", " ", "COPY B.")])
            write(root / "B.cpy", [fixed("000100", " ", "COPY A.")])
            program = root / "PROG.cbl"
            write(program, [fixed("000100", " ", "COPY A.")])

            tokens = source_tokens(program, Library(root))
            self.assertIsInstance(tokens, list)
            self.assertGreater(len(tokens), 0)


class RealDataTest(unittest.TestCase):
    @unittest.skipUnless(DATA_DIR.exists(), "CardDemo upstream data is not present")
    def test_real_program_smoke(self) -> None:
        library = Library(DATA_DIR)
        tokens = source_tokens(DATA_DIR / "cbl" / "CBACT01C.cbl", library)
        self.assertGreater(len(tokens), 100)
        self.assertTrue(any(t.kind == "pic" for t in tokens))
        self.assertTrue(any(t.text == "PROGRAM-ID" for t in tokens))


if __name__ == "__main__":
    unittest.main()
