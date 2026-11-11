"""Differential sweep: generated statements run three ways and compared.

1. GnuCOBOL on the source as written (`cobc -std=ibm`), with values MOVEd into the fields first: the reference.
2. The candidate's model (`translate(...)["cobol_exact"]`).
3. The candidate's harness (`harness.run`), which re-emits the statement.

Each probe is also classified: GnuCOBOL accepts or rejects the source, and the candidate harnesses it or gives a
reason. Usage: python tools/sweep.py OUT.jsonl  (needs $ARCTURUS_COBC or cobc on PATH; prints a summary)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cobarith.harness import run  # noqa: E402
from cobarith.inventory import inventory  # noqa: E402
from cobarith.translate import translate  # noqa: E402

COBC = os.environ.get("ARCTURUS_COBC") or shutil.which("cobc")
B = "    "  # Area B indent inside the code area


@dataclass
class Probe:
    group: str
    label: str
    data: list[str]
    lines: list[str]  # procedure lines; a leading "X|" sets column 7 (indicator) to X
    values: dict[str, str] = field(default_factory=dict)  # reference as written -> decimal value MOVEd in
    flag: bool = False  # the statement sets SZ-FLAG on size error


def fixed(n: int, code: str) -> str:
    indicator, text = (code[0], code[2:]) if len(code) > 1 and code[1] == "|" else (" ", code)
    return f"{n:06d}{indicator}{text}"


def key(text: str) -> str:
    """A reference without spacing, IN read as OF: how a value given by name is found again."""
    return "".join(f" {text.upper()} ".replace(" IN ", " OF ").split())


def source(probe: Probe, targets: list[tuple[str, int]]) -> str:
    data = [*probe.data, "01 SZ-FLAG PIC 9 VALUE 0."]
    data += [
        f"01 OUT-{i} PIC S9(30){f'V9({s})' if s else ''} SIGN LEADING SEPARATE." for i, (_, s) in enumerate(targets)
    ]
    head = ["IDENTIFICATION DIVISION.", "PROGRAM-ID. PROBE.", "DATA DIVISION.", "WORKING-STORAGE SECTION."]
    moves = [f"{B}MOVE {value} TO {ref}" for ref, value in probe.values.items()]
    shows = []
    for i, (ref, _) in enumerate(targets):
        shows += [f"{B}MOVE {ref} TO OUT-{i}", f"{B}DISPLAY 'V' OUT-{i}", f"{B}DISPLAY 'R[' {ref} ']'"]
    body = [
        *head,
        *data,
        "PROCEDURE DIVISION.",
        *moves,
        *probe.lines,
        f"{B}DISPLAY 'F' SZ-FLAG",
        *shows,
        f"{B}STOP RUN.",
    ]
    return "\n".join(fixed(n, line) for n, line in enumerate(body, 1)) + "\n"


def compile_and_run(text: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "PROBE.cbl"
        path.write_text(text)
        built = subprocess.run(
            [COBC, "-x", "-std=ibm", "-o", str(Path(tmp) / "probe"), str(path)], capture_output=True, text=True
        )
        if built.returncode:
            return False, built.stderr.strip().splitlines()[-1] if built.stderr.strip() else "compile error"
        done = subprocess.run([str(Path(tmp) / "probe")], capture_output=True, text=True, timeout=20)
        return True, done.stdout


def candidate(text: str):
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "PROBE.cbl").write_text(text)
        return inventory(tmp).statements


def reference_text(stmt, index: int) -> str:
    start, end, _ = next(span for span in stmt.spans if span[2] == index)
    return " ".join(token.text for token in stmt.tokens[start:end])


def units(value: str, scale: int) -> int:
    exact = Fraction(value) * 10**scale
    if exact.denominator != 1:
        raise ValueError(f"{value} does not fit scale {scale}")
    return int(exact)


def direct_values(output: str, targets: list[tuple[str, int]]) -> tuple[list[int], bool]:
    lines = output.splitlines()
    flag = next(line[1:] for line in lines if line.startswith("F")) == "1"
    shown = [line[1:] for line in lines if line.startswith("V")]
    raw = [line[2:-1] for line in lines if line.startswith("R[")]
    values = [int(v) for v in shown]
    # GnuCOBOL's de-editing MOVE drops a DB sign; the field's own text keeps it.
    return [-abs(v) if r.rstrip().endswith("DB") else v for v, r in zip(values, raw, strict=True)], flag


def check(probe: Probe) -> dict:
    record = {"group": probe.group, "label": probe.label, "statement": " ".join(probe.lines)}
    stmts = candidate(source(probe, []))
    record["candidate"] = [(s.status, s.reason) for s in stmts]
    accepted, _ = compile_and_run(source(probe, []))
    record["gnucobol_accepts"] = accepted
    harnessed = [s for s in stmts if s.status == "harnessed"]
    if not accepted or not harnessed or len(harnessed) != len(stmts):
        record["outcome"] = classify(accepted, stmts)
        return record
    targets, cases, given = [], [], {key(ref): value for ref, value in probe.values.items()}
    for stmt in harnessed:
        case = []
        for index, variable in enumerate(stmt.variables):
            ref = reference_text(stmt, index)
            case.append(units(given.get(key(ref), "0"), variable.pic.scale))
        cases.append(case)
        targets += [(reference_text(stmt, a.target), stmt.variables[a.target].pic.scale) for a in stmt.assignments]
    ok, output = compile_and_run(source(probe, targets))
    if not ok:
        record["outcome"] = "probe error: " + output
        return record
    direct, flag = direct_values(output, targets)
    model, harness, harness_flags = [], [], []
    for stmt, case in zip(harnessed, cases, strict=True):
        model += translate(stmt, case)["cobol_exact"]
        try:
            stored, raised = run(stmt, [case])[0]
            harness += list(stored)
            harness_flags.append(raised)
        except ValueError as exc:
            harness.append(f"error: {str(exc).splitlines()[0][:120]}")
    record.update(direct=direct, model=model, harness=harness)
    if probe.flag:
        record.update(direct_flag=flag, harness_flags=harness_flags)
    flags_agree = not probe.flag or harness_flags == [flag] * len(harness_flags)
    record["outcome"] = (
        "agree"
        if model == direct and harness == direct and flags_agree
        else "harness differs"
        if model == direct
        else "model differs"
        if harness == direct
        else "both differ"
    )
    return record


def classify(accepted: bool, stmts) -> str:
    if not stmts:
        return "no statement found" + (" (GnuCOBOL accepts)" if accepted else "")
    reasons = {s.reason for s in stmts if s.status != "harnessed"}
    if accepted:
        return "candidate refuses valid source: " + ", ".join(sorted(map(str, reasons)))
    if any(s.status == "harnessed" for s in stmts):
        return "candidate harnesses source GnuCOBOL rejects"
    return "both refuse"


def main() -> None:
    from probes import PROBES  # noqa: PLC0415  (the probe list lives next to this file)

    results = []
    for probe in PROBES:
        try:
            results.append(check(probe))
        except Exception as exc:  # one broken probe must not hide the others
            results.append({"group": probe.group, "label": probe.label, "outcome": f"sweep error: {exc!r}"[:200]})
    Path(sys.argv[1]).write_text("".join(json.dumps(r) + "\n" for r in results))
    counts: dict[str, int] = {}
    for r in results:
        counts[r["outcome"].split(":")[0]] = counts.get(r["outcome"].split(":")[0], 0) + 1
    print(json.dumps(counts, indent=1))
    for r in results:
        if r["outcome"] not in ("agree", "both refuse"):
            print(f"{r['group']:10} {r['label']:44} {r['outcome']}")


if __name__ == "__main__":
    main()
