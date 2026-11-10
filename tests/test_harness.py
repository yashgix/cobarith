import os
import shutil
import tempfile
import unittest
from pathlib import Path

from cobarith.data import parse_data
from cobarith.harness import program, run
from cobarith.source import tokenize_file
from cobarith.stmt import parse_statements

COBC = os.environ.get('ARCTURUS_COBC') or shutil.which('cobc')


def fixed(seq: str, indicator: str, code: str) -> str:
    return f'{seq}{indicator}{code}'


def write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def program_lines(data: list[str], procedure: list[str]) -> list[str]:
    lines = [
        fixed('000100', ' ', 'IDENTIFICATION DIVISION.'),
        fixed('000200', ' ', 'PROGRAM-ID. TEST.'),
        fixed('000300', ' ', 'DATA DIVISION.'),
        fixed('000400', ' ', 'WORKING-STORAGE SECTION.'),
    ]
    for number, code in enumerate(data, 5):
        lines.append(fixed(f'{number:06d}', ' ', code))
    lines.append(fixed('009000', ' ', 'PROCEDURE DIVISION.'))
    for number, code in enumerate(procedure, 91):
        lines.append(fixed(f'{number:06d}', ' ', code))
    return lines


def parse_program(data: list[str], procedure: list[str], program_name: str = 'TEST') -> list:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f'{program_name}.cbl'
        write(path, program_lines(data, procedure))
        tokens = tokenize_file(path)
        items = parse_data(tokens)
        return parse_statements(tokens, program_name, items, path.name)


class ProgramShapeTest(unittest.TestCase):
    def test_fixed_format_cases_file_and_receiving_field(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC S9(3).', '01 WS-B PIC S9(3).'],
            ['ADD WS-A TO WS-B.'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn('IDENTIFICATION DIVISION.', flat)
        self.assertIn('PROGRAM-ID. HARNESS.', flat)
        self.assertIn('SELECT CASES-FILE ASSIGN TO \'cases.txt\'', flat)
        self.assertIn('ORGANIZATION IS LINE SEQUENTIAL.', flat)
        self.assertIn('05 IN-0001 PIC S9(3) SIGN LEADING SEPARATE.', flat)
        self.assertIn('05 IN-0002 PIC S9(3) SIGN LEADING SEPARATE.', flat)
        self.assertIn('01 FLD-WS-A PIC S9(3).', flat)
        self.assertIn('01 FLD-WS-B PIC S9(3).', flat)
        self.assertIn('MOVE IN-0001 TO FLD-WS-A', flat)
        self.assertIn('ADD FLD-WS-A TO FLD-WS-B END-ADD', flat)
        self.assertIn('DISPLAY OUT-0001', flat)
        self.assertIn('DISPLAY WS-SIZE-ERROR-FLAG', flat)
        self.assertIn('STOP RUN.', flat)

        for line in source.splitlines():
            self.assertLessEqual(len(line), 72)
            self.assertEqual(line[:7], ' ' * 7)

    def test_usage_and_scale_survive_into_the_declarations(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC S9(3)V99 COMP-3.', '01 WS-B PIC S9(5)V99.'],
            ['COMPUTE WS-B = WS-A + 1.5.'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn('01 FLD-WS-A PIC S9(3)V99 COMP-3.', flat)
        self.assertIn('01 FLD-WS-B PIC S9(5)V99.', flat)
        self.assertIn('05 IN-0001 PIC S9(3)V99 SIGN LEADING SEPARATE.', flat)
        self.assertIn('COMPUTE FLD-WS-B = FLD-WS-A + 1.5 END-COMPUTE', flat)

    def test_size_error_sets_a_flag_and_closes_the_statement(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).'],
            ['COMPUTE WS-A = 123 ON SIZE ERROR.'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertTrue(statement.size_error)
        self.assertIn('ON SIZE ERROR MOVE 1 TO WS-SIZE-ERROR-FLAG END-COMPUTE', flat)

        plain = parse_program(['01 WS-A PIC 9(2).'], ['COMPUTE WS-A = 123.'])[0]
        self.assertFalse(plain.size_error)
        self.assertNotIn('ON SIZE ERROR', ' '.join(program(plain).split()))

    def test_binary_target_gets_a_roomy_display_field(self) -> None:
        statement = parse_program(['01 WS-A PIC S9(4) COMP.'], ['COMPUTE WS-A = 1.'])[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn('01 FLD-WS-A PIC S9(4) COMP.', flat)
        self.assertIn('01 OUT-0001 PIC S9(5) SIGN LEADING SEPARATE.', flat)

    def test_long_statement_wraps_inside_the_code_area(self) -> None:
        statement = parse_program(
            [
                '01 WS-A PIC S9(3).',
                '01 WS-B PIC S9(3).',
                '01 WS-C PIC S9(3).',
                '01 WS-D PIC S9(3).',
                '01 WS-E PIC S9(6).',
            ],
            ['ADD WS-A WS-B WS-C WS-D GIVING WS-E.'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn(
            'ADD FLD-WS-A FLD-WS-B FLD-WS-C FLD-WS-D GIVING FLD-WS-E END-ADD',
            flat,
        )
        for line in source.splitlines():
            self.assertLessEqual(len(line), 72)
            self.assertEqual(line[:7], ' ' * 7)

    def test_subscripts_and_clashing_names_stay_distinct(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(3) OCCURS 3.'],
            ['ADD WS-A(1) WS-A(1) TO WS-A(2).'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn('01 FLD-WS-A-1 PIC 9(3).', flat)
        self.assertIn('01 FLD-WS-A-2 PIC 9(3).', flat)
        self.assertIn('ADD FLD-WS-A-1 FLD-WS-A-1 TO FLD-WS-A-2 END-ADD', flat)
        self.assertEqual(flat.count('05 IN-'), 2)

    def test_multiple_compute_targets_share_one_expression(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).'],
            ['COMPUTE WS-A WS-B = WS-A + 1.'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn('COMPUTE FLD-WS-A FLD-WS-B = FLD-WS-A + 1 END-COMPUTE', flat)
        self.assertEqual(flat.count('END-COMPUTE'), 1)

    def test_qualified_reference_is_renamed_without_of(self) -> None:
        statement = parse_program(
            [
                '01 TOP-G.',
                '   05 MID-G.',
                '      10 WS-A PIC S9(3).',
                '01 WS-B PIC S9(3).',
            ],
            ['COMPUTE WS-B = WS-A OF MID-G OF TOP-G + 1.'],
        )[0]
        source = program(statement)
        flat = ' '.join(source.split())

        self.assertIn('COMPUTE FLD-WS-B = FLD-WS-A + 1 END-COMPUTE', flat)
        self.assertNotIn(' OF ', flat)


class RunValidationTest(unittest.TestCase):
    DATA = ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).', '01 WS-C PIC 9(2).']

    def statement(self):
        return parse_program(self.DATA, ['COMPUTE WS-A = WS-B * WS-C.'])[0]

    def test_case_outside_the_picture_raises(self) -> None:
        with self.assertRaises(ValueError):
            run(self.statement(), [(0, 1000, 1)])
        with self.assertRaises(ValueError):
            run(self.statement(), [(-1, 1, 1)])
        with self.assertRaises(ValueError):
            run(self.statement(), [(0, 1)])

    def test_missing_compiler_raises_value_error(self) -> None:
        from unittest import mock

        with mock.patch.dict(os.environ, {'ARCTURUS_COBC': '/nonexistent/cobc-3.2'}):
            with self.assertRaises(ValueError):
                run(self.statement(), [(0, 1, 1)])


@unittest.skipUnless(COBC, 'no GnuCOBOL compiler available')
class RunTest(unittest.TestCase):
    def test_display_overflow_keeps_the_low_order_digits(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).', '01 WS-C PIC 9(2).'],
            ['COMPUTE WS-A = WS-B * WS-C.'],
        )[0]
        self.assertEqual(run(statement, [(0, 50, 41)]), [((50,), False)])

    def test_size_error_keeps_the_prior_value(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).', '01 WS-C PIC 9(2).'],
            ['COMPUTE WS-A = WS-B * WS-C ON SIZE ERROR.'],
        )[0]
        self.assertEqual(run(statement, [(7, 50, 41)]), [((7,), True)])

    def test_comp_wraps_at_its_binary_width(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC S9(4) COMP.', '01 WS-B PIC S9(3).', '01 WS-C PIC S9(3).'],
            ['COMPUTE WS-A = WS-B * WS-C.'],
        )[0]
        self.assertEqual(run(statement, [(0, 200, 200)]), [((-25536,), False)])

    def test_division_truncates_toward_zero(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC S9(3)V99.', '01 WS-B PIC S9(2)V99.'],
            ['COMPUTE WS-B = WS-A / 3.'],
        )[0]
        self.assertEqual(run(statement, [(0, 100)]), [((33,), False)])

    def test_rounded_halves_go_away_from_zero(self) -> None:
        data = ['01 WS-A PIC S9(3)V99.', '01 WS-B PIC S9(2)V99.']
        rounded = parse_program(data, ['COMPUTE WS-B ROUNDED = WS-A / 2.'])[0]
        plain = parse_program(data, ['COMPUTE WS-B = WS-A / 2.'])[0]

        self.assertEqual(run(rounded, [(0, 125)]), [((63,), False)])
        self.assertEqual(run(plain, [(0, 125)]), [((62,), False)])

    def test_several_cases_run_in_order(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).', '01 WS-C PIC 9(2).'],
            ['COMPUTE WS-A = WS-B * WS-C.'],
        )[0]
        results = run(statement, [(0, 1, 2), (0, 50, 41), (0, 0, 9)])
        self.assertEqual(results, [((2,), False), ((50,), False), ((0,), False)])

    def test_add_subtract_multiply_divide_forms_against_compiler(self) -> None:
        add = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).'],
            ['ADD WS-A TO WS-B.'],
        )[0]
        self.assertEqual(run(add, [(5, 10)]), [((15,), False)])

        subtract = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).'],
            ['SUBTRACT WS-A FROM WS-B.'],
        )[0]
        self.assertEqual(run(subtract, [(5, 20)]), [((15,), False)])

        multiply = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).'],
            ['MULTIPLY WS-A BY WS-B.'],
        )[0]
        self.assertEqual(run(multiply, [(5, 10)]), [((50,), False)])

        divide = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).'],
            ['DIVIDE WS-A INTO WS-B.'],
        )[0]
        self.assertEqual(run(divide, [(5, 10)]), [((2,), False)])

    def test_giving_into_edited_target_against_compiler(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC -ZZ9.'],
            ['ADD WS-A GIVING WS-B.'],
        )[0]
        self.assertEqual(run(statement, [(7, 0)]), [((7,), False)])

    def test_overlapping_multi_target_compute_uses_original_operand(self) -> None:
        statement = parse_program(
            ['01 WS-A PIC 9(2).', '01 WS-B PIC 9(2).'],
            ['COMPUTE WS-A WS-B = WS-A + 1.'],
        )[0]
        self.assertEqual(run(statement, [(5, 0)]), [((6,), False), ((6,), False)])


if __name__ == '__main__':
    unittest.main()
