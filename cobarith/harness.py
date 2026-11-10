'''GnuCOBOL harness: one generated program per statement, run over its cases.

The generated program re-emits the statement's own tokens with data references
renamed, so COBOL itself evaluates the original verb and target list.
'''

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .data import Pic, binary_bits
from .stmt import Statement, Variable

__all__ = ['program', 'run']

_BINARY_USAGES = {'COMP', 'COMP-5', 'BINARY'}
_AREA_B = '       '
_STATEMENT = '           '
_CODE_WIDTH = 65
_NAME_LIMIT = 30
_FLAG = 'WS-SIZE-ERROR-FLAG'

_EMIT_KEYWORDS = {
    'ADD',
    'SUBTRACT',
    'MULTIPLY',
    'DIVIDE',
    'COMPUTE',
    'TO',
    'GIVING',
    'FROM',
    'BY',
    'INTO',
    'ROUNDED',
    'ZERO',
    'ZEROS',
    'ZEROES',
    'OF',
    'IN',
    'ON',
    'SIZE',
    'ERROR',
    'NOT',
    'END-ADD',
    'END-SUBTRACT',
    'END-MULTIPLY',
    'END-DIVIDE',
    'END-COMPUTE',
}


def _wrap(text: str, indent: str) -> list[str]:
    chunks: list[str] = []
    current = indent
    for word in text.split():
        if not current.strip():
            current = indent + word
        elif len(current) + 1 + len(word) <= _CODE_WIDTH:
            current = f'{current} {word}'
        else:
            chunks.append(current)
            current = indent + word
    chunks.append(current)
    return chunks


def _physical(code: str) -> str:
    return f'       {code}'


def _picture_of(variable: Variable) -> Pic:
    if variable.pic is None:
        raise ValueError(f'{variable.name} has no PICTURE')
    return variable.pic


def _field_names(variables: Sequence[Variable]) -> list[str]:
    names: list[str] = []
    used: set[str] = set()
    for index, variable in enumerate(variables, 1):
        cleaned = ''.join(
            char if char.isalnum() or char == '-' else '-' for char in variable.name.upper()
        )
        cleaned = cleaned.strip('-')
        stem = f'FLD-{cleaned}' if cleaned else f'FLD-{index}'
        stem = stem[:_NAME_LIMIT].rstrip('-')
        name = stem
        counter = 2
        while name in used:
            suffix = f'-{counter}'
            name = stem[: _NAME_LIMIT - len(suffix)].rstrip('-') + suffix
            counter += 1
        used.add(name)
        names.append(name)
    return names


def _scaled_picture(digits: int, scale: int) -> str:
    if scale:
        return f'S9({digits})V9({scale})'
    return f'S9({digits})'


def _input_picture(variable: Variable) -> str:
    pic = _picture_of(variable)
    return _scaled_picture(max(pic.digits, 1), pic.scale)


def _output_picture(variable: Variable) -> str:
    pic = _picture_of(variable)
    if variable.usage.upper() in _BINARY_USAGES:
        bits = binary_bits(pic)
        bound = 2 ** (bits - 1) if pic.signed else 2**bits - 1
    else:
        bound = pic.capacity
    digits = max(pic.digits, len(str(bound)) - pic.scale, 1)
    return _scaled_picture(digits, pic.scale)


def _declaration(variable: Variable) -> str:
    text = f'PIC {_picture_of(variable).text}'
    if variable.usage and variable.usage != 'DISPLAY':
        text += f' {variable.usage}'
    return text


def _skip_balanced(tokens: Sequence[object], pos: int) -> int | None:
    if pos >= len(tokens):
        return None
    token = tokens[pos]
    if not (token.kind == 'sep' and token.text == '('):
        return pos
    depth = 0
    while pos < len(tokens):
        current = tokens[pos]
        if current.kind == 'sep' and current.text == '(':
            depth += 1
        elif current.kind == 'sep' and current.text == ')':
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def _consume_qualifiers(tokens: Sequence[object], pos: int) -> int:
    while pos < len(tokens) and tokens[pos].kind == 'word' and tokens[pos].text in ('OF', 'IN'):
        pos += 1
        if pos >= len(tokens) or tokens[pos].kind != 'word':
            break
        pos += 1
        if pos < len(tokens) and tokens[pos].kind == 'sep' and tokens[pos].text == '(':
            pos = _skip_balanced(tokens, pos)
            if pos is None:
                break
    return pos


def _base_map(variables: Sequence[Variable]) -> dict[str, list[tuple[str | None, int]]]:
    mapping: dict[str, list[tuple[str | None, int]]] = {}
    for index, variable in enumerate(variables):
        name = variable.name.upper()
        if '(' in name:
            base, _, rest = name.partition('(')
            subscript = rest[:-1].strip() if rest.endswith(')') else rest.strip()
        else:
            base = name
            subscript = None
        mapping.setdefault(base, []).append((subscript, index))
    return mapping


def _match_ref(tokens: Sequence[object], i: int, base_map: dict, fields: Sequence[str]):
    if i >= len(tokens) or tokens[i].kind != 'word' or tokens[i].text in _EMIT_KEYWORDS:
        return None
    base = tokens[i].text.upper()
    candidates = base_map.get(base)
    if not candidates:
        return None

    pos = i + 1
    subscript: str | None = None
    if pos < len(tokens) and tokens[pos].kind == 'sep' and tokens[pos].text == '(':
        close = _skip_balanced(tokens, pos)
        if close is None:
            return None
        subscript = ' '.join(token.text for token in tokens[pos + 1 : close - 1])
        pos = close

    matches = [index for sub, index in candidates if sub == subscript]
    if not matches:
        return None

    pos = _consume_qualifiers(tokens, pos)
    return matches[0], pos


def _touching(prev: object, curr: object) -> bool:
    return prev.file == curr.file and prev.line == curr.line and prev.end == curr.col


def _statement_code(stmt: Statement, fields: Sequence[str]) -> str:
    tokens = stmt.tokens
    base_map_values = _base_map(stmt.variables)
    pieces: list[tuple[str, bool]] = []
    prev_token = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        join_prev = prev_token is not None and _touching(prev_token, token)
        match = _match_ref(tokens, i, base_map_values, fields)
        if match is not None:
            index, end = match
            pieces.append((fields[index], join_prev))
            prev_token = tokens[end - 1]
            i = end
        else:
            pieces.append((token.text, join_prev))
            prev_token = token
            i += 1

    code = ''
    for piece_index, (text, join_prev) in enumerate(pieces):
        if piece_index and not join_prev:
            code += ' '
        code += text
    return code


def program(stmt: Statement) -> str:
    variables = list(stmt.variables)
    if not variables or not stmt.assignments:
        raise ValueError(f'{stmt.id} has nothing to harness')
    if not stmt.tokens:
        raise ValueError(f'{stmt.id} has no tokens to harness')

    fields = _field_names(variables)
    sources = [f'IN-{index:04d}' for index in range(1, len(variables) + 1)]
    displays = [f'OUT-{index:04d}' for index in range(1, len(stmt.assignments) + 1)]
    lines: list[str] = []

    def add(text: str, indent: str = '') -> None:
        lines.extend(_wrap(text, indent))

    add('IDENTIFICATION DIVISION.')
    add('PROGRAM-ID. HARNESS.')
    add('ENVIRONMENT DIVISION.')
    add('INPUT-OUTPUT SECTION.')
    add('FILE-CONTROL.')
    add('SELECT CASES-FILE ASSIGN TO \'cases.txt\'', _AREA_B)
    add('ORGANIZATION IS LINE SEQUENTIAL.', _AREA_B)
    add('DATA DIVISION.')
    add('FILE SECTION.')
    add('FD CASES-FILE.')
    add('01 CASE-RECORD.')
    for source, variable in zip(sources, variables, strict=True):
        add(f'05 {source} PIC {_input_picture(variable)} SIGN LEADING SEPARATE.')
    add('WORKING-STORAGE SECTION.')
    add('01 WS-END-FLAG PIC X VALUE \'N\'.')
    add(f'01 {_FLAG} PIC 9 VALUE 0.')
    for name, variable in zip(fields, variables, strict=True):
        add(f'01 {name} {_declaration(variable)}.')
    for position, assignment in enumerate(stmt.assignments):
        display_picture = _output_picture(variables[assignment.target])
        add(f'01 {displays[position]} PIC {display_picture} SIGN LEADING SEPARATE.')
    add('PROCEDURE DIVISION.')
    add('MAIN-PARA.')
    add('OPEN INPUT CASES-FILE', _STATEMENT)
    add('PERFORM UNTIL WS-END-FLAG = \'Y\'', _STATEMENT)
    add('READ CASES-FILE', _STATEMENT)
    add('AT END MOVE \'Y\' TO WS-END-FLAG', _STATEMENT)
    add('END-READ', _STATEMENT)
    add('IF WS-END-FLAG NOT = \'Y\'', _STATEMENT)
    for name, source in zip(fields, sources, strict=True):
        add(f'MOVE {source} TO {name}', _STATEMENT)
    add(f'MOVE 0 TO {_FLAG}', _STATEMENT)
    statement_text = _statement_code(stmt, fields)
    if stmt.size_error:
        statement_text += f' ON SIZE ERROR MOVE 1 TO {_FLAG}'
    statement_text += f' END-{stmt.verb}'
    add(statement_text, _STATEMENT)
    for display in displays:
        add(f'DISPLAY {display}', _STATEMENT)
    add(f'DISPLAY {_FLAG}', _STATEMENT)
    add('END-IF', _STATEMENT)
    add('END-PERFORM', _STATEMENT)
    add('CLOSE CASES-FILE', _STATEMENT)
    add('STOP RUN.', _STATEMENT)

    return ''.join(_physical(line) + '\n' for line in lines)


def _check_case(stmt: Statement, case: Sequence[int]) -> None:
    if len(case) != len(stmt.variables):
        raise ValueError(f'case has {len(case)} values for {len(stmt.variables)} variables')
    for variable, value in zip(stmt.variables, case, strict=True):
        pic = _picture_of(variable)
        if not isinstance(value, int):
            raise ValueError(f'{variable.name}: {value!r} is not an integer number of units')
        if abs(value) > pic.capacity:
            raise ValueError(f'{variable.name}: {value} is outside {pic.text}')
        if not pic.signed and value < 0:
            raise ValueError(f'{variable.name}: {value} is negative for an unsigned field')


def _case_line(stmt: Statement, case: Sequence[int]) -> str:
    parts: list[str] = []
    for variable, value in zip(stmt.variables, case, strict=True):
        pic = _picture_of(variable)
        width = max(pic.digits, 1) + pic.scale
        sign = '-' if value < 0 else '+'
        parts.append(f'{sign}{abs(value):0{width}d}')
    return ''.join(parts)


def run(stmt: Statement, cases: Sequence[Sequence[int]]) -> list[tuple[tuple[int, ...], bool]]:
    checked = [tuple(case) for case in cases]
    for case in checked:
        _check_case(stmt, case)

    source = program(stmt)
    payload = ''.join(_case_line(stmt, case) + '\n' for case in checked)
    compiler = os.environ.get('ARCTURUS_COBC') or 'cobc'

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / 'harness.cbl').write_text(source, encoding='utf-8')
        (folder / 'cases.txt').write_text(payload, encoding='utf-8')
        try:
            built = subprocess.run(
                [compiler, '-x', '-std=ibm', '-o', 'harness', 'harness.cbl'],
                cwd=folder,
                capture_output=True,
                text=True,
            )
        except OSError as error:
            raise ValueError(f'cannot run {compiler}: {error}') from error
        if built.returncode != 0:
            raise ValueError(f'cobc failed: {(built.stderr or built.stdout).strip()}')
        executed = subprocess.run(
            [str(folder / 'harness')], cwd=folder, capture_output=True, text=True
        )
        if executed.returncode != 0:
            raise ValueError(f'harness failed: {(executed.stderr or executed.stdout).strip()}')

    tokens = executed.stdout.split()
    per_case = len(stmt.assignments) + 1
    if len(tokens) != per_case * len(checked):
        raise ValueError(f'expected {per_case * len(checked)} values, got {len(tokens)}')

    results: list[tuple[tuple[int, ...], bool]] = []
    for index in range(len(checked)):
        chunk = tokens[index * per_case : (index + 1) * per_case]
        results.append((tuple(int(text) for text in chunk[:-1]), chunk[-1] != '0'))
    return results
