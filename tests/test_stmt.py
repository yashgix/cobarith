import tempfile
import unittest
from pathlib import Path

from cobarith.data import parse_data
from cobarith.source import Library, source_tokens, tokenize_file
from cobarith.stmt import parse_statements


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


NUMERIC_FIELDS = [
    "01 WS-A PIC S9(3).",
    "01 WS-B PIC 9(4).",
    "01 WS-C PIC S9(6).",
]


class StatementFormsTest(unittest.TestCase):
    def test_forms_targets_and_variable_order(self) -> None:
        statements = parse_program(
            NUMERIC_FIELDS,
            [
                "ADD WS-A TO WS-B.",
                "ADD WS-A WS-B GIVING WS-C.",
                "SUBTRACT WS-A FROM WS-B.",
                "SUBTRACT WS-A FROM WS-B GIVING WS-C.",
                "MULTIPLY WS-A BY WS-B.",
                "MULTIPLY WS-A BY WS-B GIVING WS-C.",
                "DIVIDE WS-A INTO WS-B.",
                "DIVIDE WS-A INTO WS-B GIVING WS-C.",
                "DIVIDE WS-A BY WS-B GIVING WS-C.",
                "COMPUTE WS-C = WS-A + WS-B * 2.",
            ],
        )

        self.assertEqual(
            [statement.verb for statement in statements],
            [
                "ADD",
                "ADD",
                "SUBTRACT",
                "SUBTRACT",
                "MULTIPLY",
                "MULTIPLY",
                "DIVIDE",
                "DIVIDE",
                "DIVIDE",
                "COMPUTE",
            ],
        )
        self.assertTrue(all(statement.status == "harnessed" for statement in statements))
        self.assertEqual(statements[0].targets, ["WS-B"])
        self.assertEqual([variable.name for variable in statements[0].variables], ["WS-A", "WS-B"])
        self.assertEqual(statements[1].targets, ["WS-C"])
        self.assertEqual([variable.name for variable in statements[1].variables], ["WS-A", "WS-B", "WS-C"])
        self.assertEqual(statements[2].targets, ["WS-B"])
        self.assertEqual(statements[3].targets, ["WS-C"])
        self.assertEqual([variable.name for variable in statements[3].variables], ["WS-A", "WS-B", "WS-C"])
        self.assertEqual(statements[4].targets, ["WS-B"])
        self.assertEqual(statements[5].targets, ["WS-C"])
        self.assertEqual(statements[6].targets, ["WS-B"])
        self.assertEqual(statements[7].targets, ["WS-C"])
        self.assertEqual(statements[8].targets, ["WS-C"])
        self.assertEqual(statements[9].targets, ["WS-C"])
        self.assertEqual([variable.name for variable in statements[9].variables], ["WS-C", "WS-A", "WS-B"])

    def test_size_error_ends_statement_and_flag_is_set(self) -> None:
        statements = parse_program(
            NUMERIC_FIELDS,
            [
                "ADD WS-A TO WS-B",
                "   ON SIZE ERROR",
                "   DISPLAY 'ERR'",
                "END-ADD.",
                "ADD WS-A TO WS-B.",
            ],
        )

        self.assertEqual(len(statements), 2)
        self.assertTrue(statements[0].size_error)
        self.assertFalse(statements[1].size_error)
        self.assertEqual(statements[0].reason, None)
        self.assertEqual(statements[1].reason, None)

    def test_distinct_subscripts_are_distinct_variables(self) -> None:
        statements = parse_program(
            ["01 WS-A PIC 9(3) OCCURS 3."],
            ["ADD WS-A(1) WS-A(1) TO WS-A(2)."],
        )

        self.assertEqual(len(statements), 1)
        self.assertEqual([variable.name for variable in statements[0].variables], ["WS-A(1)", "WS-A(2)"])
        self.assertEqual(statements[0].targets, ["WS-A(2)"])

    def test_exec_block_is_ignored(self) -> None:
        statements = parse_program(
            NUMERIC_FIELDS,
            [
                "EXEC SQL SELECT ADD FROM X END-EXEC.",
                "ADD WS-A TO WS-B.",
            ],
        )

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0].verb, "ADD")
        self.assertEqual(statements[0].targets, ["WS-B"])

    def test_copybook_verb_gets_file_in_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "PROG.cbl",
                program_lines(
                    ["01 WS-A PIC S9(3).", "01 WS-B PIC 9(4)."],
                    ["COPY SNIP."],
                ),
            )
            write(root / "SNIP.cpy", [fixed("000100", " ", "ADD WS-A TO WS-B.")])

            tokens = source_tokens(root / "PROG.cbl", Library(root))
            statements = parse_statements(tokens, "PROG", parse_data(tokens), "PROG.cbl")

            self.assertEqual(len(statements), 1)
            self.assertEqual(statements[0].file, "SNIP.cpy")
            self.assertTrue(statements[0].id.startswith("PROG:SNIP.cpy:"))


class FlagsTest(unittest.TestCase):
    def test_add_flags_size_and_sign(self) -> None:
        statements = parse_program(NUMERIC_FIELDS, ["ADD WS-A TO WS-B."])
        self.assertEqual(
            statements[0].flags,
            {"scale": False, "float": False, "size": True, "sign": True},
        )

    def test_compute_flags_division(self) -> None:
        statements = parse_program(
            [
                "01 WS-A PIC S9(3).",
                "01 WS-B PIC 9(4).",
                "01 WS-C PIC S9(5)V99.",
            ],
            ["COMPUTE WS-C = WS-A / WS-B."],
        )
        self.assertEqual(
            statements[0].flags,
            {"scale": True, "float": True, "size": True, "sign": False},
        )

    def test_compute_flags_decimal_target_without_overflow(self) -> None:
        statements = parse_program(
            [
                "01 WS-A PIC S9(3).",
                "01 WS-C PIC S9(5)V99.",
            ],
            ["COMPUTE WS-C = WS-A + 1."],
        )
        self.assertEqual(
            statements[0].flags,
            {"scale": False, "float": True, "size": False, "sign": False},
        )


class UnsupportedReasonsTest(unittest.TestCase):
    DATA = [
        "01 WS-A PIC S9(5).",
        "01 WS-B PIC S9(5).",
        "01 WS-C PIC S9(5).",
        "01 WS-G.",
        "   05 WS-GX PIC X.",
        "01 WS-TABLE PIC X(2) OCCURS 3 INDEXED BY WS-IDX.",
        "01 WS-F COMP-1.",
        "01 WS-P PIC 9(3)P(2).",
        "01 WS-E PIC -ZZZ,ZZ9.99.",
    ]

    CASES = [
        ("COMPUTE WS-A = FUNCTION NUMVAL(WS-B).", "intrinsic function"),
        ("COMPUTE WS-A = LENGTH OF WS-B.", "LENGTH OF"),
        ("COMPUTE WS-A = RETURN-CODE.", "special register"),
        ("COMPUTE WS-A = WS-UNKNOWN.", "unresolved name"),
        ("ADD WS-G TO WS-A.", "non-numeric field"),
        ("ADD WS-IDX TO WS-A.", "index item"),
        ("ADD WS-F TO WS-A.", "floating-point usage"),
        ("ADD WS-P TO WS-A.", "P scaling"),
        ("COMPUTE WS-A = WS-E + 1.", "numeric-edited operand"),
        ("DIVIDE WS-A INTO WS-B REMAINDER WS-C.", "REMAINDER"),
        ("COMPUTE WS-A = WS-B(1:2).", "reference modification"),
        ("COMPUTE WS-A = '1'.", "nonnumeric literal"),
        ("ADD WS-A TO WS-B CORRESPONDING.", "CORRESPONDING"),
        ("COMPUTE WS-A = WS-B ** 2.", "exponentiation"),
        ("ADD WS-A TO WS-B ROUNDED MODE IS NEAREST-EVEN.", "ROUNDED MODE"),
        ("ADD WS-A TO.", "syntax"),
    ]

    def test_reason_strings(self) -> None:
        for code, reason in self.CASES:
            with self.subTest(code=code):
                statements = parse_program(self.DATA, [code])
                self.assertEqual(len(statements), 1)
                self.assertEqual(statements[0].status, "unsupported")
                self.assertEqual(statements[0].reason, reason)

    def test_feature_reason_precedes_resolution(self) -> None:
        statements = parse_program(self.DATA, ["COMPUTE WS-UNKNOWN = FUNCTION NUMVAL(WS-B)."])
        self.assertEqual(statements[0].reason, "intrinsic function")


if __name__ == "__main__":
    unittest.main()
