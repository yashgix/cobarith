"""COBOL storage rules and plausible Python translations for arithmetic statements."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

from .data import Pic, binary_bits, parse_pic
from .stmt import Binary, Expr, Field, Literal, Statement, Unary, Variable

__all__ = [
    "TRANSLATIONS",
    "exact_results",
    "scale_units",
    "storage_changed",
    "store",
    "translate",
]

TRANSLATIONS = (
    "cobol_exact",
    "exact_no_size",
    "float_round",
    "decimal_half_even",
    "float_truncate",
)

_BINARY_USAGES = {"COMP", "COMP-5", "BINARY"}


def scale_units(value: Fraction, scale: int, rounded: bool) -> int:
    """Convert an exact decimal value to integer units of ``10**-scale``."""

    scaled = Fraction(value) * 10**scale
    if not rounded:
        return int(scaled)
    if scaled >= 0:
        return math.floor(scaled + Fraction(1, 2))
    return -math.floor(-scaled + Fraction(1, 2))


def store(units: int, pic: Pic | str, usage: str, prior: int, size_error: bool) -> tuple[int, bool]:
    """Apply the GnuCOBOL 3.2 ``-std=ibm`` storage rule for one receiving field."""

    if isinstance(pic, str):
        pic = parse_pic(pic)
    if usage.upper() in _BINARY_USAGES:
        return _store_binary(units, pic, prior, size_error)
    return _store_display(units, pic, prior, size_error)


def _store_display(units: int, pic: Pic, prior: int, size_error: bool) -> tuple[int, bool]:
    raised = False
    if abs(units) > pic.capacity:
        if size_error:
            value = prior
            raised = True
        else:
            magnitude = abs(units) % (pic.capacity + 1)
            value = -magnitude if units < 0 else magnitude
    else:
        value = units

    if not pic.signed:
        value = abs(value)
    return value, raised


def _store_binary(units: int, pic: Pic, prior: int, size_error: bool) -> tuple[int, bool]:
    bits = binary_bits(pic)
    unsigned = not pic.signed
    value = abs(units) if unsigned else units

    if unsigned:
        low, high = 0, 2**bits - 1
    else:
        low, high = -(2 ** (bits - 1)), 2 ** (bits - 1) - 1

    if low <= value <= high:
        return value, False
    if size_error:
        return (abs(prior) if unsigned else prior), True
    if unsigned:
        return value % 2**bits, False

    modulus = 2**bits
    half = 2 ** (bits - 1)
    return ((value + half) % modulus) - half, False


def _scale_of(variable: Variable) -> int:
    return variable.pic.scale if variable.pic is not None else 0


def _combine(op: str, left, right):
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    return left / right


def _eval_exact(expr: Expr, variables: Sequence[Variable], case: Sequence[int]) -> Fraction:
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, Field):
        return Fraction(case[expr.index], 10 ** _scale_of(variables[expr.index]))
    if isinstance(expr, Unary):
        value = _eval_exact(expr.operand, variables, case)
        return -value if expr.op == "-" else value
    if isinstance(expr, Binary):
        left = _eval_exact(expr.left, variables, case)
        right = _eval_exact(expr.right, variables, case)
        return _combine(expr.op, left, right)
    raise TypeError(f"unsupported expression: {expr!r}")


def _eval_float(expr: Expr, variables: Sequence[Variable], case: Sequence[int]) -> float:
    if isinstance(expr, Literal):
        return float(expr.value)
    if isinstance(expr, Field):
        return float(Fraction(case[expr.index], 10 ** _scale_of(variables[expr.index])))
    if isinstance(expr, Unary):
        value = _eval_float(expr.operand, variables, case)
        return -value if expr.op == "-" else value
    if isinstance(expr, Binary):
        left = _eval_float(expr.left, variables, case)
        right = _eval_float(expr.right, variables, case)
        return _combine(expr.op, left, right)
    raise TypeError(f"unsupported expression: {expr!r}")


def _eval_decimal(expr: Expr, variables: Sequence[Variable], case: Sequence[int]) -> Decimal:
    if isinstance(expr, Literal):
        return Decimal(expr.value.numerator) / Decimal(expr.value.denominator)
    if isinstance(expr, Field):
        return Decimal(case[expr.index]) / (Decimal(10) ** _scale_of(variables[expr.index]))
    if isinstance(expr, Unary):
        value = _eval_decimal(expr.operand, variables, case)
        return -value if expr.op == "-" else value
    if isinstance(expr, Binary):
        left = _eval_decimal(expr.left, variables, case)
        right = _eval_decimal(expr.right, variables, case)
        return _combine(expr.op, left, right)
    raise TypeError(f"unsupported expression: {expr!r}")


def exact_results(stmt: Statement, case: Sequence[int]) -> list[Fraction]:
    """Exact unrounded result per target, using the case's units per variable."""

    return [_eval_exact(assignment.expr, stmt.variables, case) for assignment in stmt.assignments]


def _target_pic(stmt: Statement, assignment_index: int) -> Pic:
    target = stmt.variables[stmt.assignments[assignment_index].target]
    if target.pic is None:
        raise ValueError("target has no PICTURE")
    return target.pic


def translate(stmt: Statement, case: Sequence[int]) -> dict[str, list[int]]:
    """Stored units per target for each reference translation."""

    exact = exact_results(stmt, case)
    results: dict[str, list[int]] = {name: [] for name in TRANSLATIONS}

    for index, (assignment, exact_value) in enumerate(zip(stmt.assignments, exact, strict=True)):
        target = stmt.variables[assignment.target]
        pic = _target_pic(stmt, index)
        scale = pic.scale
        units = scale_units(exact_value, scale, assignment.rounded)

        stored, _raised = store(units, pic, target.usage, case[assignment.target], stmt.size_error)
        results["cobol_exact"].append(stored)
        results["exact_no_size"].append(units)

        floating = _eval_float(assignment.expr, stmt.variables, case)
        results["float_round"].append(int(round(round(floating, scale) * 10**scale)))

        decimal_value = _eval_decimal(assignment.expr, stmt.variables, case)
        quantum = Decimal(1).scaleb(-scale)
        results["decimal_half_even"].append(
            int(decimal_value.quantize(quantum, rounding=ROUND_HALF_EVEN))
        )

        results["float_truncate"].append(math.trunc(floating * 10**scale))

    return results


def storage_changed(stmt: Statement, case: Sequence[int]) -> bool:
    """Whether the COBOL storage rule changes the exact arithmetic result."""

    results = translate(stmt, case)
    return results["cobol_exact"] != results["exact_no_size"]
