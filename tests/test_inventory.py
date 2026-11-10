import tempfile
import unittest
from pathlib import Path

from cobarith import DATA_DIR
from cobarith.inventory import Inventory, inventory


def fixed(seq: str, indicator: str, code: str) -> str:
    return f"{seq}{indicator}{code}"


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def program_lines(program: str, data: list[str], procedure: list[str]) -> list[str]:
    lines = [
        fixed("000100", " ", "IDENTIFICATION DIVISION."),
        fixed("000200", " ", f"PROGRAM-ID. {program}."),
        fixed("000300", " ", "DATA DIVISION."),
        fixed("000400", " ", "WORKING-STORAGE SECTION."),
    ]
    for number, code in enumerate(data, 5):
        lines.append(fixed(f"{number:06d}", " ", code))
    lines.append(fixed("009000", " ", "PROCEDURE DIVISION."))
    for number, code in enumerate(procedure, 91):
        lines.append(fixed(f"{number:06d}", " ", code))
    return lines


class InventoryTest(unittest.TestCase):
    def test_program_and_statement_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "z" / "prog2.CBL",
                program_lines(
                    "PROG2",
                    ["01 WS-A PIC 9(3).", "01 WS-B PIC 9(3)."],
                    ["ADD WS-A TO WS-B.", "SUBTRACT WS-A FROM WS-B."],
                ),
            )
            write(
                root / "a" / "prog1.cbl",
                program_lines(
                    "PROG1",
                    ["01 WS-A PIC 9(3).", "01 WS-B PIC 9(3)."],
                    ["COMPUTE WS-A = WS-B + 1."],
                ),
            )
            (root / "NOTES.txt").write_text("ignored\n", encoding="utf-8")

            result = inventory(root)

            self.assertIsInstance(result, Inventory)
            self.assertEqual(result.programs, ["PROG1", "PROG2"])
            self.assertEqual(
                [(statement.program, statement.verb) for statement in result.statements],
                [("PROG1", "COMPUTE"), ("PROG2", "ADD"), ("PROG2", "SUBTRACT")],
            )
            self.assertEqual(result.missing_copybooks, set())
            self.assertTrue(all(statement.status == "harnessed" for statement in result.statements))

    def test_copybooks_resolve_from_the_program_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "a" / "cpy" / "FOO.cpy", [fixed("000100", " ", "01 WS-A PIC 9(3).")])
            write(root / "b" / "cpy" / "FOO.cpy", [fixed("000100", " ", "01 WS-B PIC 9(4).")])
            write(
                root / "a" / "cbl" / "P1.cbl",
                program_lines("P1", ["COPY FOO."], ["ADD WS-A TO WS-A."]),
            )
            write(
                root / "b" / "cbl" / "P2.cbl",
                program_lines("P2", ["COPY FOO."], ["ADD WS-B TO WS-B."]),
            )

            result = inventory(root)

            by_program = {statement.program: statement for statement in result.statements}
            self.assertEqual([variable.name for variable in by_program["P1"].variables], ["WS-A"])
            self.assertEqual([variable.name for variable in by_program["P2"].variables], ["WS-B"])
            self.assertEqual(result.missing_copybooks, set())

    def test_missing_copybooks_are_unioned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "cbl" / "P1.cbl",
                program_lines(
                    "P1",
                    ["01 WS-A PIC 9(3).", "COPY MISSING-A.", "COPY PRESENT."],
                    ["ADD WS-A TO WS-A."],
                ),
            )
            write(
                root / "cbl" / "P2.cbl",
                program_lines(
                    "P2",
                    ["01 WS-B PIC 9(3).", "COPY MISSING-B.", "COPY MISSING-A."],
                    ["ADD WS-B TO WS-B."],
                ),
            )
            write(root / "cpy" / "PRESENT.cpy", [fixed("000100", " ", "01 WS-C PIC 9(4).")])

            result = inventory(root)

            self.assertEqual(result.missing_copybooks, {"MISSING-A", "MISSING-B"})

    def test_empty_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = inventory(Path(tmp))

            self.assertEqual(result, Inventory([], [], set()))

    def test_statement_status_reasons_and_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(
                root / "P1.cbl",
                program_lines("P1", ["01 WS-A PIC S9(3)."], ["ADD WS-A TO WS-A."]),
            )
            write(
                root / "P2.cbl",
                program_lines(
                    "P2",
                    ["01 WS-A PIC X(01).", "01 WS-B PIC S9(3)."],
                    ["COMPUTE WS-B = FUNCTION NUMVAL(WS-A)."],
                ),
            )

            result = inventory(root)

            self.assertEqual([s.status for s in result.statements], ["harnessed", "unsupported"])
            self.assertEqual(result.statements[1].reason, "intrinsic function")
            self.assertRegex(result.statements[0].id, r"^P1:\d+:ADD$")
            self.assertRegex(result.statements[1].id, r"^P2:\d+:COMPUTE$")


class RealDataTest(unittest.TestCase):
    @unittest.skipUnless(DATA_DIR.exists(), "CardDemo upstream data is not present")
    def test_real_inventory_smoke(self) -> None:
        result = inventory(DATA_DIR)

        self.assertGreater(len(result.programs), 20)
        self.assertIn("CBACT01C", result.programs)
        self.assertGreater(len(result.statements), 0)
        self.assertTrue(all(statement.program in result.programs for statement in result.statements))
        self.assertTrue(any(statement.status == "harnessed" for statement in result.statements))

    @unittest.skipUnless(DATA_DIR.exists(), "CardDemo upstream data is not present")
    def test_real_inventory_classification_stable_ids_and_reasons(self) -> None:
        result = inventory(DATA_DIR)
        allowed_reasons = {
            "intrinsic function",
            "LENGTH OF",
            "special register",
            "unresolved name",
            "non-numeric field",
            "index item",
            "floating-point usage",
            "P scaling",
            "numeric-edited operand",
            "REMAINDER",
            "reference modification",
            "nonnumeric literal",
            "CORRESPONDING",
            "exponentiation",
            "ROUNDED MODE",
            "syntax",
        }

        for statement in result.statements:
            self.assertIn(statement.status, {"harnessed", "unsupported"})
            self.assertRegex(
                statement.id,
                r"^[A-Z0-9_-]+:(?:[A-Za-z0-9_.-]+:)?\d+:(?:ADD|SUBTRACT|MULTIPLY|DIVIDE|COMPUTE)$",
            )
            if statement.status == "harnessed":
                self.assertIsNone(statement.reason)
                self.assertIsNotNone(statement.flags)
            else:
                self.assertIsNotNone(statement.reason)
                self.assertIn(statement.reason, allowed_reasons)
                self.assertIsNone(statement.flags)

        self.assertGreater(sum(s.status == "harnessed" for s in result.statements), 0)
        self.assertGreater(sum(s.status == "unsupported" for s in result.statements), 0)


if __name__ == "__main__":
    unittest.main()
