"""Pinned random and z3 boundary inputs for harnessed arithmetic statements."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from fractions import Fraction

import z3

from .data import Pic
from .stmt import Binary, Expr, Field, Literal, Statement, Unary, Variable
from .translate import exact_results

__all__ = ["boundary_cases", "random_cases"]


def _random(seed: str) -> random.Random:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _range_for(variable: Variable) -> tuple[int, int]:
    pic = variable.pic
    if pic is None:
        return 0, 0
    if pic.signed:
        return -pic.capacity, pic.capacity
    return 0, pic.capacity


def _top_for(pic: Pic | None, index: int) -> int:
    if pic is None:
        return 0
    if index % 2 == 1:
        return pic.capacity
    return min(pic.capacity, 10 ** (pic.scale + min(pic.digits, 5)) - 1)


def _divides_by_zero(stmt: Statement, case: Sequence[int]) -> bool:
    try:
        exact_results(stmt, case)
    except ZeroDivisionError:
        return True
    return False


def random_cases(stmt: Statement, n: int = 1000) -> list[list[int]]:
    """Pinned random inputs, redrawing any case that divides by zero."""
    if n <= 0:
        return []
    rng = _random(f"{stmt.id}|random")
    cases: list[list[int]] = []
    while len(cases) < n:
        index = len(cases)
        case: list[int] = []
        for variable in stmt.variables:
            top = _top_for(variable.pic, index)
            low = -top if variable.pic is not None and variable.pic.signed else 0
            case.append(rng.randint(low, top))
        if not _divides_by_zero(stmt, case):
            cases.append(case)
    return cases


def _real(value: Fraction):
    return z3.RealVal(value.numerator) / z3.RealVal(value.denominator)


def _scale_of(variable: Variable) -> int:
    return variable.pic.scale if variable.pic is not None else 0


def _real_expr(expr: Expr, variables: Sequence[Variable], z3_vars: Sequence):
    if isinstance(expr, Literal):
        return _real(expr.value)
    if isinstance(expr, Field):
        scale = _scale_of(variables[expr.index])
        return z3.ToReal(z3_vars[expr.index]) / z3.RealVal(10**scale)
    if isinstance(expr, Unary):
        operand = _real_expr(expr.operand, variables, z3_vars)
        return -operand if expr.op == "-" else operand
    if isinstance(expr, Binary):
        left = _real_expr(expr.left, variables, z3_vars)
        right = _real_expr(expr.right, variables, z3_vars)
        if expr.op == "+":
            return left + right
        if expr.op == "-":
            return left - right
        if expr.op == "*":
            return left * right
        if expr.op == "/":
            return left / right
    raise TypeError(f"unsupported expression: {expr!r}")


def _nonzero_constraints(expr: Expr, variables: Sequence[Variable], z3_vars: Sequence):
    constraints = []
    if isinstance(expr, Unary):
        constraints.extend(_nonzero_constraints(expr.operand, variables, z3_vars))
    elif isinstance(expr, Binary):
        if expr.op == "/":
            constraints.append(_real_expr(expr.right, variables, z3_vars) != 0)
        constraints.extend(_nonzero_constraints(expr.left, variables, z3_vars))
        constraints.extend(_nonzero_constraints(expr.right, variables, z3_vars))
    return constraints


def _kind_constraint(kind: str, result, pic: Pic):
    scale = pic.scale
    scaled = result * z3.RealVal(10**scale)
    if kind == "tie":
        return z3.IsInt(scaled - z3.RealVal(1) / z3.RealVal(2))
    if kind == "exact":
        return z3.IsInt(scaled)
    if kind == "over":
        return z3.Abs(result) >= _real(Fraction(pic.capacity + 1, 10**scale))
    if kind == "negative":
        return scaled <= z3.RealVal(-1)
    raise ValueError(f"unknown kind: {kind}")


def _kind_holds(kind: str, value: Fraction, pic: Pic) -> bool:
    scale = pic.scale
    scaled = value * 10**scale
    if kind == "tie":
        return scaled.denominator == 2
    if kind == "exact":
        return scaled.denominator == 1
    if kind == "over":
        return abs(value) >= Fraction(pic.capacity + 1, 10**scale)
    if kind == "negative":
        return scaled <= -1
    return False


def _solve(
    stmt: Statement,
    target_index: int,
    kind: str,
    attempt: int,
    rng: random.Random,
) -> tuple[int, ...] | None:
    variables = stmt.variables
    if not variables:
        return None

    z3_vars = [z3.Int(f"v{i}") for i in range(len(variables))]
    solver = z3.Solver()
    solver.set("rlimit", 2_000_000)

    for variable, z3_var in zip(variables, z3_vars, strict=True):
        low, high = _range_for(variable)
        solver.add(z3_var >= low, z3_var <= high)

    if attempt > 0:
        for variable, z3_var in zip(variables, z3_vars, strict=True):
            low, high = _range_for(variable)
            width = max(1, (high - low) // 20)
            centre = rng.randint(low, high)
            half = width // 2
            solver.add(z3_var >= max(low, centre - half))
            solver.add(z3_var <= min(high, centre + half))

    assignment = stmt.assignments[target_index]
    target = variables[assignment.target]
    pic = target.pic
    if pic is None:
        return None

    result = _real_expr(assignment.expr, variables, z3_vars)
    solver.add(_kind_constraint(kind, result, pic))
    for other in stmt.assignments:
        for constraint in _nonzero_constraints(other.expr, variables, z3_vars):
            solver.add(constraint)

    if solver.check() != z3.sat:
        return None

    model = solver.model()
    case = tuple(
        model.eval(z3_var, model_completion=True).as_long() for z3_var in z3_vars
    )
    try:
        value = exact_results(stmt, case)[target_index]
    except ZeroDivisionError:
        return None
    if not _kind_holds(kind, value, pic):
        return None
    return case


def boundary_cases(stmt: Statement) -> list[tuple[str, int, list[int]]]:
    """One or more z3-witnessed boundary inputs per flagged kind and target."""
    if stmt.flags is None or not stmt.assignments:
        return []

    kinds: list[str] = []
    if stmt.flags.get("scale"):
        kinds.extend(["tie", "exact"])
    if stmt.flags.get("size"):
        kinds.append("over")
    if stmt.flags.get("sign"):
        kinds.append("negative")
    if not kinds:
        return []

    rng = _random(f"{stmt.id}|boundary")
    results: list[tuple[str, int, list[int]]] = []
    for kind in kinds:
        for target_index in range(len(stmt.assignments)):
            target = stmt.variables[stmt.assignments[target_index].target]
            if target.pic is None:
                continue
            seen: set[tuple[int, ...]] = set()
            for attempt in range(12):
                case = _solve(stmt, target_index, kind, attempt, rng)
                if case is not None and case not in seen:
                    seen.add(case)
                    results.append((kind, target_index, list(case)))
    return results
