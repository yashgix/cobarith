"""Statement scanning and arithmetic-form parsing for fixed-format COBOL."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .data import Item, Pic, find_item
from .source import Token

__all__ = [
    "Assignment",
    "Binary",
    "Expr",
    "Field",
    "Literal",
    "Statement",
    "Unary",
    "Variable",
    "parse_statement",
    "parse_statements",
    "scan_statements",
    "statements",
]


@dataclass(frozen=True)
class Variable:
    """A distinct data reference used by a statement."""

    name: str
    pic: Pic | None
    usage: str


@dataclass(frozen=True)
class Literal:
    value: Fraction
    scale: int


@dataclass(frozen=True)
class Field:
    index: int


@dataclass(frozen=True)
class Unary:
    op: str
    operand: Expr


@dataclass(frozen=True)
class Binary:
    op: str
    left: Expr
    right: Expr


Expr = Literal | Field | Unary | Binary


@dataclass(frozen=True)
class Assignment:
    target: int
    expr: Expr
    rounded: bool = False


@dataclass
class Statement:
    program: str
    file: str
    line: int
    verb: str
    id: str
    status: str
    reason: str | None
    size_error: bool
    flags: dict[str, bool] | None
    variables: list[Variable]
    targets: list[str]
    assignments: list[Assignment] = field(default_factory=list, repr=False)
    target_indices: list[int] = field(default_factory=list, repr=False)
    read_flags: list[bool] = field(default_factory=list, repr=False)
    tokens: list[Token] = field(default_factory=list, repr=False)
    spans: list[tuple[int, int, int]] = field(default_factory=list, repr=False)


_VERBS = {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"}

_TERMINATORS = {
    "ACCEPT",
    "ADD",
    "ALTER",
    "CALL",
    "CANCEL",
    "CLOSE",
    "COMPUTE",
    "CONTINUE",
    "DELETE",
    "DISPLAY",
    "DIVIDE",
    "ELSE",
    "EVALUATE",
    "EXEC",
    "EXIT",
    "GO",
    "GOBACK",
    "IF",
    "INITIALIZE",
    "INSPECT",
    "MERGE",
    "MOVE",
    "MULTIPLY",
    "NEXT",
    "OPEN",
    "PERFORM",
    "READ",
    "RELEASE",
    "RETURN",
    "REWRITE",
    "SEARCH",
    "SET",
    "SORT",
    "START",
    "STOP",
    "STRING",
    "SUBTRACT",
    "THEN",
    "UNSTRING",
    "WHEN",
    "WRITE",
}

_SPECIAL_REGISTERS = {
    "RETURN-CODE",
    "SORT-RETURN",
    "TALLY",
    "EIBCALEN",
    "EIBRESP",
    "EIBRESP2",
}

_RESERVED = _TERMINATORS | {
    "AND",
    "BY",
    "CORR",
    "CORRESPONDING",
    "ERROR",
    "FROM",
    "FUNCTION",
    "GIVING",
    "IN",
    "INTO",
    "IS",
    "LENGTH",
    "MODE",
    "NOT",
    "OF",
    "ON",
    "OR",
    "REMAINDER",
    "ROUNDED",
    "SIZE",
    "TO",
    "ZERO",
    "ZEROES",
    "ZEROS",
}


@dataclass
class _Ref:
    name: str
    base: str
    qualifiers: tuple[str, ...]
    subscript: str | None
    index: int
    item: Item | None = None


class _ParseError(Exception):
    pass


def _feature_reason(tokens: Sequence[Token]) -> str | None:
    for i, token in enumerate(tokens):
        if token.kind == "word":
            text = token.text
            if text == "FUNCTION":
                return "intrinsic function"
            if text == "LENGTH" and i + 1 < len(tokens) and tokens[i + 1].kind == "word" and tokens[i + 1].text == "OF":
                return "LENGTH OF"
            if text in _SPECIAL_REGISTERS:
                return "special register"
            if text == "REMAINDER":
                return "REMAINDER"
            if text in ("CORRESPONDING", "CORR"):
                return "CORRESPONDING"
            if (
                text == "ROUNDED"
                and i + 1 < len(tokens)
                and tokens[i + 1].kind == "word"
                and tokens[i + 1].text == "MODE"
            ):
                return "ROUNDED MODE"
        elif token.kind == "sep":
            if token.text == ":":
                return "reference modification"
            if token.text == "**":
                return "exponentiation"
        elif token.kind == "lit":
            return "nonnumeric literal"
    return None


def _procedure_start(tokens: Sequence[Token]) -> int | None:
    for i in range(len(tokens) - 1):
        if (
            tokens[i].kind == "word"
            and tokens[i].text == "PROCEDURE"
            and tokens[i + 1].kind == "word"
            and tokens[i + 1].text == "DIVISION"
        ):
            return i + 2
    return None


def _size_error_at(tokens: Sequence[Token], i: int) -> bool:
    def word(j: int, text: str) -> bool:
        return j < len(tokens) and tokens[j].kind == "word" and tokens[j].text == text

    if word(i, "SIZE") and word(i + 1, "ERROR"):
        return True
    if word(i, "ON") and word(i + 1, "SIZE") and word(i + 2, "ERROR"):
        return True
    if word(i, "NOT"):
        j = i + 1
        if word(j, "ON"):
            j += 1
        if word(j, "SIZE") and word(j + 1, "ERROR"):
            return True
    return False


def _statement_slices(tokens: Sequence[Token], start: int) -> list[tuple[list[Token], bool, Token]]:
    out: list[tuple[list[Token], bool, Token]] = []
    i = start
    n = len(tokens)
    while i < n:
        token = tokens[i]
        if token.kind == "word" and token.text == "EXEC":
            j = i + 1
            while j < n and not (tokens[j].kind == "word" and tokens[j].text == "END-EXEC"):
                j += 1
            i = j + 1 if j < n else n
            continue

        if token.kind == "word" and token.text in _VERBS:
            verb = token
            j = i + 1
            size_error = False
            while j < n:
                current = tokens[j]
                if current.kind == "sep" and current.text == ".":
                    break
                if current.kind == "word" and current.text.startswith("END-"):
                    break
                if _size_error_at(tokens, j):
                    size_error = True
                    break
                if current.kind == "word" and current.text in _TERMINATORS:
                    break
                j += 1

            out.append((list(tokens[i:j]), size_error, verb))
            i = j
            if i < n:
                current = tokens[i]
                if current.kind == "sep" and current.text == ".":
                    i += 1
                elif current.kind == "word" and current.text.startswith("END-"):
                    i += 1
            continue

        i += 1
    return out


def _sum_expr(exprs: Sequence[Expr]) -> Expr:
    if not exprs:
        return Literal(Fraction(0), 0)
    total = exprs[0]
    for expr in exprs[1:]:
        total = Binary("+", total, expr)
    return total


class _Parser:
    def __init__(self, tokens: Sequence[Token], items: Iterable[Item]) -> None:
        self.tokens = list(tokens)
        self.items = list(items)
        self.i = 0
        self.refs: list[_Ref] = []
        self.by_key: dict[tuple[str, tuple[str, ...], str | None], int] = {}
        self.read: list[bool] = []
        self.target_indices: list[int] = []
        self.target_names: list[str] = []
        self.assignments: list[Assignment] = []
        self.spans: list[tuple[int, int, int]] = []

    def parse(self) -> None:
        if not self.tokens or self.tokens[0].kind != "word":
            raise _ParseError
        verb = self.tokens[0].text
        if verb == "COMPUTE":
            self._parse_compute()
        elif verb == "ADD":
            self._parse_add()
        elif verb == "SUBTRACT":
            self._parse_subtract()
        elif verb == "MULTIPLY":
            self._parse_multiply()
        elif verb == "DIVIDE":
            self._parse_divide()
        else:
            raise _ParseError
        if self.i != len(self.tokens):
            raise _ParseError

    def resolve_variables(self) -> list[Variable]:
        variables: list[Variable] = []
        for ref in self.refs:
            item = find_item(self.items, ref.base, ref.qualifiers)
            ref.item = item
            if item is None:
                variables.append(Variable(ref.name, None, ""))
            else:
                variables.append(Variable(ref.name, item.pic, item.usage))
        return variables

    def resolution_reason(self) -> str | None:
        for index, ref in enumerate(self.refs):
            item = ref.item
            if item is None:
                return "unresolved name"
            if item.index or item.usage == "INDEX":
                return "index item"
            if item.usage in ("COMP-1", "COMP-2"):
                return "floating-point usage"
            pic = item.pic
            if pic is None or pic.kind == "alnum":
                return "non-numeric field"
            if pic.kind == "scaled":
                return "P scaling"
            if pic.kind == "edited" and self.read[index]:
                return "numeric-edited operand"
        return None

    def _current(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _is_word(self, text: str) -> bool:
        token = self._current()
        return token is not None and token.kind == "word" and token.text == text

    def _is_sep(self, text: str) -> bool:
        token = self._current()
        return token is not None and token.kind == "sep" and token.text == text

    def _next_num_adjacent(self) -> bool:
        if self.i + 1 >= len(self.tokens):
            return False
        sign = self.tokens[self.i]
        number = self.tokens[self.i + 1]
        return (
            sign.kind == "sep"
            and sign.text in ("+", "-")
            and number.kind == "num"
            and sign.file == number.file
            and sign.line == number.line
            and sign.end == number.col
        )

    def _record_ref(self, base: str, qualifiers: Sequence[str], subscript: str | None) -> _Ref:
        base_upper = base.upper()
        qualifiers_upper = tuple(qualifier.upper() for qualifier in qualifiers)
        key = (base_upper, qualifiers_upper, subscript)
        if key in self.by_key:
            return self.refs[self.by_key[key]]

        index = len(self.refs)
        name = base_upper if subscript is None else f"{base_upper}({subscript})"
        ref = _Ref(name, base_upper, qualifiers_upper, subscript, index)
        self.refs.append(ref)
        self.by_key[key] = index
        self.read.append(False)
        return ref

    def _mark_read(self, ref: _Ref) -> None:
        self.read[ref.index] = True

    def _parse_subscript(self) -> str | None:
        if not self._is_sep("("):
            return None
        self.i += 1
        parts: list[str] = []
        depth = 1
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            if token.kind == "sep" and token.text == "(":
                depth += 1
            elif token.kind == "sep" and token.text == ")":
                depth -= 1
                if depth == 0:
                    self.i += 1
                    return " ".join(parts)
            parts.append(token.text)
            self.i += 1
        raise _ParseError

    def _parse_ref(self) -> _Ref:
        token = self._current()
        if token is None or token.kind != "word" or token.text in _RESERVED:
            raise _ParseError
        base = token.text
        start = self.i
        self.i += 1
        subscript = self._parse_subscript()
        qualifiers: list[str] = []

        while self._is_word("OF") or self._is_word("IN"):
            self.i += 1
            qualifier = self._current()
            if qualifier is None or qualifier.kind != "word" or qualifier.text in _RESERVED:
                raise _ParseError
            qualifiers.append(qualifier.text)
            self.i += 1
            self._parse_subscript()

        ref = self._record_ref(base, qualifiers, subscript)
        self.spans.append((start, self.i, ref.index))
        return ref

    def _parse_number(self) -> Literal:
        sign = 1
        token = self._current()
        if token is not None and token.kind == "sep" and token.text in ("+", "-") and self._next_num_adjacent():
            sign = -1 if token.text == "-" else 1
            self.i += 1
            token = self._current()
        if token is None or token.kind != "num":
            raise _ParseError
        self.i += 1
        scale = len(token.text.split(".", 1)[1]) if "." in token.text else 0
        return Literal(Fraction(token.text) * sign, scale)

    def _parse_value(self) -> Expr:
        token = self._current()
        if token is None:
            raise _ParseError
        if token.kind == "sep" and token.text in ("+", "-") and self._next_num_adjacent():
            return self._parse_number()
        if token.kind == "num":
            return self._parse_number()
        if token.kind == "word" and token.text in ("ZERO", "ZEROS", "ZEROES"):
            self.i += 1
            return Literal(Fraction(0), 0)
        if token.kind == "word" and token.text not in _RESERVED:
            ref = self._parse_ref()
            self._mark_read(ref)
            return Field(ref.index)
        raise _ParseError

    def _parse_values(self, stop_words: set[str]) -> list[Expr]:
        values: list[Expr] = []
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            if token.kind == "word" and token.text in stop_words:
                break
            values.append(self._parse_value())
        return values

    def _parse_targets(
        self,
        *,
        stop_words: set[str] | None = None,
        stop_sep: str | None = None,
        read: bool = False,
    ) -> list[tuple[_Ref, bool]]:
        targets: list[tuple[_Ref, bool]] = []
        while self.i < len(self.tokens):
            token = self.tokens[self.i]
            if stop_words is not None and token.kind == "word" and token.text in stop_words:
                break
            if stop_sep is not None and token.kind == "sep" and token.text == stop_sep:
                break
            ref = self._parse_ref()
            rounded = False
            if self._is_word("ROUNDED"):
                rounded = True
                self.i += 1
            if read:
                self._mark_read(ref)
            targets.append((ref, rounded))
        return targets

    def _parse_expression(self) -> Expr:
        return self._parse_additive()

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while True:
            token = self._current()
            if token is None or token.kind != "sep" or token.text not in ("+", "-"):
                return left
            op = token.text
            self.i += 1
            right = self._parse_multiplicative()
            left = Binary(op, left, right)

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_primary()
        while True:
            token = self._current()
            if token is None or token.kind != "sep" or token.text not in ("*", "/"):
                return left
            op = token.text
            self.i += 1
            right = self._parse_primary()
            left = Binary(op, left, right)

    def _parse_primary(self) -> Expr:
        token = self._current()
        if token is None:
            raise _ParseError
        if token.kind == "sep" and token.text == "(":
            self.i += 1
            expr = self._parse_expression()
            if not self._is_sep(")"):
                raise _ParseError
            self.i += 1
            return expr
        if token.kind == "sep" and token.text in ("+", "-") and not self._next_num_adjacent():
            self.i += 1
            return Unary(token.text, self._parse_primary())
        return self._parse_value()

    def _add_assignment(self, ref: _Ref, expr: Expr, rounded: bool, read: bool = False) -> None:
        if read:
            self._mark_read(ref)
        if ref.index in self.target_indices:
            return
        self.target_indices.append(ref.index)
        self.target_names.append(ref.name)
        self.assignments.append(Assignment(ref.index, expr, rounded))

    def _parse_compute(self) -> None:
        self.i = 1
        targets = self._parse_targets(stop_sep="=", read=False)
        if not targets or not self._is_sep("="):
            raise _ParseError
        self.i += 1
        expr = self._parse_expression()
        for ref, rounded in targets:
            self._add_assignment(ref, expr, rounded)

    def _giving_ahead(self) -> bool:
        return any(t.kind == "word" and t.text == "GIVING" for t in self.tokens[self.i :])

    def _parse_add(self) -> None:
        self.i = 1
        values = self._parse_values({"TO", "GIVING"})
        if not values:
            raise _ParseError

        if self._is_word("TO") and self._giving_ahead():
            self.i += 1
            more = self._parse_values({"GIVING"})
            if not more or not self._is_word("GIVING"):
                raise _ParseError
            self.i += 1
            giving = self._parse_targets(read=False)
            if not giving:
                raise _ParseError
            total = _sum_expr(values + more)
            for ref, rounded in giving:
                self._add_assignment(ref, total, rounded)
        elif self._is_word("TO"):
            self.i += 1
            targets = self._parse_targets(stop_words={"GIVING"}, read=True)
            if not targets:
                raise _ParseError
            total = _sum_expr(values)
            for ref, rounded in targets:
                self._add_assignment(ref, Binary("+", Field(ref.index), total), rounded, read=True)
        elif self._is_word("GIVING"):
            self.i += 1
            giving = self._parse_targets(read=False)
            if not giving:
                raise _ParseError
            total = _sum_expr(values)
            for ref, rounded in giving:
                self._add_assignment(ref, total, rounded)
        else:
            raise _ParseError

    def _parse_subtract(self) -> None:
        self.i = 1
        values = self._parse_values({"FROM", "GIVING"})
        if not values or not self._is_word("FROM"):
            raise _ParseError
        self.i += 1
        from_refs = self._parse_targets(stop_words={"GIVING"}, read=True)
        if not from_refs:
            raise _ParseError

        if self._is_word("GIVING"):
            if len(from_refs) != 1:
                raise _ParseError
            self.i += 1
            giving = self._parse_targets(read=False)
            if not giving:
                raise _ParseError
            expr = Binary("-", Field(from_refs[0][0].index), _sum_expr(values))
            for ref, rounded in giving:
                self._add_assignment(ref, expr, rounded)
        else:
            total = _sum_expr(values)
            for ref, rounded in from_refs:
                self._add_assignment(ref, Binary("-", Field(ref.index), total), rounded, read=True)

    def _parse_multiply(self) -> None:
        self.i = 1
        left = self._parse_value()
        if not self._is_word("BY"):
            raise _ParseError
        self.i += 1
        ref = self._parse_ref()

        if self._is_word("GIVING"):
            self._mark_read(ref)
            self.i += 1
            giving = self._parse_targets(read=False)
            if not giving:
                raise _ParseError
            expr = Binary("*", left, Field(ref.index))
            for target, rounded in giving:
                self._add_assignment(target, expr, rounded)
        else:
            rounded = False
            if self._is_word("ROUNDED"):
                rounded = True
                self.i += 1
            self._mark_read(ref)
            self._add_assignment(ref, Binary("*", Field(ref.index), left), rounded, read=True)

    def _parse_divide(self) -> None:
        self.i = 1
        left = self._parse_value()

        if self._is_word("INTO"):
            self.i += 1
            ref = self._parse_ref()
            if self._is_word("GIVING"):
                self._mark_read(ref)
                self.i += 1
                giving = self._parse_targets(read=False)
                if not giving:
                    raise _ParseError
                expr = Binary("/", Field(ref.index), left)
                for target, rounded in giving:
                    self._add_assignment(target, expr, rounded)
            else:
                rounded = False
                if self._is_word("ROUNDED"):
                    rounded = True
                    self.i += 1
                self._mark_read(ref)
                self._add_assignment(ref, Binary("/", Field(ref.index), left), rounded, read=True)
            return

        if self._is_word("BY"):
            self.i += 1
            ref = self._parse_ref()
            if not self._is_word("GIVING"):
                raise _ParseError
            self._mark_read(ref)
            self.i += 1
            giving = self._parse_targets(read=False)
            if not giving:
                raise _ParseError
            expr = Binary("/", left, Field(ref.index))
            for target, rounded in giving:
                self._add_assignment(target, expr, rounded)
            return

        raise _ParseError


def _expr_scale(expr: Expr, variables: Sequence[Variable]) -> int | None:
    if isinstance(expr, Literal):
        return expr.scale
    if isinstance(expr, Field):
        pic = variables[expr.index].pic
        return pic.scale if pic is not None else 0
    if isinstance(expr, Unary):
        return _expr_scale(expr.operand, variables)
    if isinstance(expr, Binary):
        if expr.op == "/":
            return None
        left = _expr_scale(expr.left, variables)
        right = _expr_scale(expr.right, variables)
        if left is None or right is None:
            return None
        if expr.op == "*":
            return left + right
        return max(left, right)
    return 0


Interval = tuple[Fraction | None, Fraction | None]
_UNBOUNDED: Interval = (None, None)


def _is_unbounded(interval: Interval) -> bool:
    return interval[0] is None or interval[1] is None


def _expr_interval(expr: Expr, variables: Sequence[Variable]) -> Interval:
    if isinstance(expr, Literal):
        return expr.value, expr.value

    if isinstance(expr, Field):
        pic = variables[expr.index].pic
        if pic is None:
            return _UNBOUNDED
        cap = Fraction(pic.capacity, 10**pic.scale)
        low = -cap if pic.signed else Fraction(0)
        return low, cap

    if isinstance(expr, Unary):
        low, high = _expr_interval(expr.operand, variables)
        if _is_unbounded((low, high)):
            return _UNBOUNDED
        if expr.op == "-":
            return -high, -low
        return low, high

    if isinstance(expr, Binary):
        left = _expr_interval(expr.left, variables)
        right = _expr_interval(expr.right, variables)
        if expr.op in ("+", "-"):
            if _is_unbounded(left) or _is_unbounded(right):
                return _UNBOUNDED
            if expr.op == "+":
                return left[0] + right[0], left[1] + right[1]
            return left[0] - right[1], left[1] - right[0]
        if expr.op == "*":
            if _is_unbounded(left) or _is_unbounded(right):
                return _UNBOUNDED
            products = [
                left[0] * right[0],
                left[0] * right[1],
                left[1] * right[0],
                left[1] * right[1],
            ]
            return min(products), max(products)
        if expr.op == "/":
            if _is_unbounded(left) or _is_unbounded(right):
                return _UNBOUNDED
            if right[0] <= 0 <= right[1]:
                return _UNBOUNDED
            quotients = [
                left[0] / right[0],
                left[0] / right[1],
                left[1] / right[0],
                left[1] / right[1],
            ]
            return min(quotients), max(quotients)

    return _UNBOUNDED


def _has_division(expr: Expr) -> bool:
    if isinstance(expr, Binary):
        return expr.op == "/" or _has_division(expr.left) or _has_division(expr.right)
    if isinstance(expr, Unary):
        return _has_division(expr.operand)
    return False


def _has_decimal_literal(expr: Expr) -> bool:
    if isinstance(expr, Literal):
        return expr.scale > 0
    if isinstance(expr, Unary):
        return _has_decimal_literal(expr.operand)
    if isinstance(expr, Binary):
        return _has_decimal_literal(expr.left) or _has_decimal_literal(expr.right)
    return False


def _compute_flags(assignments: Sequence[Assignment], variables: Sequence[Variable]) -> dict[str, bool]:
    flags = {"scale": False, "float": False, "size": False, "sign": False}
    statement_decimal = any(variable.pic is not None and variable.pic.scale > 0 for variable in variables)
    if not statement_decimal:
        statement_decimal = any(_has_decimal_literal(assignment.expr) for assignment in assignments)

    for assignment in assignments:
        if assignment.target >= len(variables):
            continue
        pic = variables[assignment.target].pic
        if pic is None:
            continue

        scale = _expr_scale(assignment.expr, variables)
        if scale is None or scale > pic.scale:
            flags["scale"] = True

        interval = _expr_interval(assignment.expr, variables)
        unbounded = _is_unbounded(interval)

        if _has_division(assignment.expr) or pic.scale > 0 or statement_decimal:
            flags["float"] = True

        if unbounded:
            flags["float"] = True
            flags["size"] = True
        else:
            bound = max(abs(interval[0]), abs(interval[1]))
            if bound * (10**pic.scale) >= 2**53:
                flags["float"] = True
            threshold = Fraction(pic.capacity + 1, 10**pic.scale)
            if bound >= threshold:
                flags["size"] = True

        if not pic.signed and (unbounded or interval[0] < 0):
            flags["sign"] = True

    return flags


def _statement_id(program: str, file: str, line: int, verb: str, program_file: str | None) -> str:
    own_file = Path(program_file).name if program_file else ""
    if own_file and file != own_file:
        return f"{program}:{file}:{line}:{verb}"
    return f"{program}:{line}:{verb}"


def _build_statement(
    tokens: Sequence[Token],
    program: str,
    items: Iterable[Item],
    program_file: str | None,
    size_error: bool,
) -> Statement:
    token_list = list(tokens)
    if token_list and token_list[-1].kind == "sep" and token_list[-1].text == ".":
        token_list = token_list[:-1]

    verb_token = token_list[0] if token_list else None
    verb = verb_token.text if verb_token is not None and verb_token.kind == "word" else ""
    file = verb_token.file if verb_token is not None else (Path(program_file).name if program_file else "")
    line = verb_token.line if verb_token is not None else 0
    program_name = program.upper()
    statement_id = _statement_id(program_name, file, line, verb, program_file)

    if not token_list:
        return Statement(
            program_name,
            file,
            line,
            verb,
            statement_id,
            "unsupported",
            "syntax",
            size_error,
            None,
            [],
            [],
        )

    feature = _feature_reason(token_list)
    if feature is not None:
        return Statement(
            program_name,
            file,
            line,
            verb,
            statement_id,
            "unsupported",
            feature,
            size_error,
            None,
            [],
            [],
        )

    parser = _Parser(token_list, items)
    try:
        parser.parse()
    except _ParseError:
        variables = parser.resolve_variables()
        return Statement(
            program_name,
            file,
            line,
            verb,
            statement_id,
            "unsupported",
            "syntax",
            size_error,
            None,
            variables,
            list(parser.target_names),
            list(parser.assignments),
            list(parser.target_indices),
            list(parser.read),
        )

    variables = parser.resolve_variables()
    reason = parser.resolution_reason()
    if reason is not None:
        return Statement(
            program_name,
            file,
            line,
            verb,
            statement_id,
            "unsupported",
            reason,
            size_error,
            None,
            variables,
            list(parser.target_names),
            list(parser.assignments),
            list(parser.target_indices),
            list(parser.read),
        )

    flags = _compute_flags(parser.assignments, variables)
    return Statement(
        program_name,
        file,
        line,
        verb,
        statement_id,
        "harnessed",
        None,
        size_error,
        flags,
        variables,
        list(parser.target_names),
        list(parser.assignments),
        list(parser.target_indices),
        list(parser.read),
        token_list,
        sorted(set(parser.spans)),
    )


def parse_statements(
    tokens: Sequence[Token],
    program: str,
    items: Iterable[Item],
    program_file: str | None = None,
) -> list[Statement]:
    token_list = list(tokens)
    if not token_list:
        return []
    if program_file is None:
        program_file = token_list[0].file
    start = _procedure_start(token_list)
    if start is None:
        return []
    return [
        _build_statement(statement_tokens, program, items, program_file, size_error)
        for statement_tokens, size_error, _verb in _statement_slices(token_list, start)
    ]


def parse_statement(
    tokens: Sequence[Token],
    program: str,
    items: Iterable[Item],
    program_file: str | None = None,
    size_error: bool = False,
) -> Statement:
    token_list = list(tokens)
    if program_file is None and token_list:
        program_file = token_list[0].file
    return _build_statement(token_list, program, items, program_file, size_error)


statements = parse_statements
scan_statements = parse_statements
