"""Probes for tools/sweep.py: representative and boundary combinations of the specified forms, not every one."""

from sweep import B, Probe

DATA = [
    "01 WS-A PIC S9(3)V9.",
    "01 WS-B PIC S9(3)V9.",
    "01 WS-C PIC S9(5)V99.",
    "01 WS-D PIC S9(5)V99.",
    "01 WS-S PIC S9(2).",
    "01 WS-I PIC 9 VALUE 2.",
    "01 G1.",
    "    05 X PIC S9(3)V9.",
    "    05 T PIC S9(3)V9 OCCURS 3.",
    "01 G2.",
    "    05 X PIC S9(3)V9.",
    "    05 T PIC S9(3)V9 OCCURS 3.",
]
VALUES = {
    "WS-A": "-12.5",
    "WS-B": "4.5",
    "WS-C": "7",
    "WS-D": "3",
    "WS-S": "10",
    "X OF G1": "2.5",
    "X OF G2": "-3.5",
    "T OF G1(1)": "1.5",
    "T OF G1(2)": "6",
    "T OF G2(2)": "-8.5",
    "T OF G1(WS-I)": "6",
    "T OF G1(3)": "-4",
    "T OF G1(WS-I + 1)": "-4",
}  # WS-I is 2, so T OF G1(WS-I) is T OF G1(2)

# Operand kinds for a position the statement reads, and for one it stores into.
VALUE_KINDS = {
    "field": "WS-B", "qualified": "X OF G1", "subscripted": "T OF G1(2)", "IN, spaced subscript": "T IN G2 (2)",
    "variable subscript": "T OF G1(WS-I)", "integer": "3", "decimal": "2.5", "signed -": "-2", "signed +": "+2",
    "ZERO": "ZERO", "ZEROS": "ZEROS", "ZEROES": "ZEROES",
}  # fmt: skip
TARGET_KINDS = {"field": "WS-C", "qualified": "X OF G2", "subscripted": "T OF G1(1)", "literal": "5"}
ZEROISH = ("ZERO", "ZEROS", "ZEROES")

# {a}, {b}: read; {t}: stored. The divisor slot never gets ZERO (no case can exist; see random_cases).
FORMS = {
    "COMPUTE": ("COMPUTE {t} = {a} + {b}", None),
    "ADD TO": ("ADD {a} TO {t}", None),
    "ADD a b TO t t": ("ADD {a} {b} TO {t} WS-D", None),
    "ADD TO GIVING": ("ADD {a} TO {b} GIVING {t}", None),
    "ADD GIVING": ("ADD {a} {b} GIVING {t}", None),
    "SUBTRACT FROM": ("SUBTRACT {a} FROM {t}", None),
    "SUBTRACT a b FROM": ("SUBTRACT {a} {b} FROM {t}", None),
    "SUBTRACT GIVING": ("SUBTRACT {a} FROM {b} GIVING {t}", None),
    "MULTIPLY BY": ("MULTIPLY {a} BY {t}", None),
    "MULTIPLY GIVING": ("MULTIPLY {a} BY {b} GIVING {t}", None),
    "DIVIDE INTO": ("DIVIDE {a} INTO {t}", "a"),
    "DIVIDE INTO GIVING": ("DIVIDE {a} INTO {b} GIVING {t}", "a"),
    "DIVIDE BY GIVING": ("DIVIDE {a} BY {b} GIVING {t}", "b"),
}


def statement(group: str, label: str, *lines: str, data=None, values=None, flag: bool = False) -> Probe:
    body = [line if "|" in line[:2] or line.startswith(" ") else f"{B}{line}" for line in lines]
    return Probe(group, label, [*DATA, *(data or [])], [*body[:-1], body[-1] + "."], {**VALUES, **(values or {})}, flag)


def form_probes() -> list[Probe]:
    probes = []
    for form, (template, divisor) in FORMS.items():
        slots = [s for s in ("a", "b", "t") if "{" + s + "}" in template]
        base = {"a": "WS-A", "b": "WS-B", "t": "WS-C"}
        for slot in slots:
            kinds = TARGET_KINDS if slot == "t" else VALUE_KINDS
            for kind, text in kinds.items():
                if slot == divisor and text in ZEROISH:
                    continue
                filled = {**base, slot: text}
                probes.append(statement("forms", f"{form}: {slot} {kind}", template.format(**filled)))
    return probes


EXPRESSIONS = [
    "WS-A + WS-B * 2", "(WS-A + WS-B) * 2", "WS-A - WS-B - 1", "WS-A / WS-B * 3", "WS-A * (WS-B + (2 - WS-A))",
    "((WS-A))", "-WS-A", "- WS-A", "+WS-A", "-(WS-A + WS-B)", "WS-A * -1", "WS-A - -1", "WS-A+WS-B", "WS-A +WS-B",
    "WS-A+ WS-B", "WS-A -1", "WS-A+1", "(WS-A)-1", "2 * -WS-A", "-2 * WS-A", "WS-A / 3", "WS-A / 7 * 7",
    "1 / 3 * 3", "WS-A * 1.5 / 0.3", "ZERO - WS-A", "WS-A + ZEROS", "(WS-A - WS-B) / (WS-B + 1)",
    "X OF G1 * T OF G2(2)", "T OF G1(1) + T OF G1(2)", "T OF G1 (1) + T OF G1(1)", "X IN G1 - X OF G1",
    "WS-A ** 2", "FUNCTION ABS(WS-A)", "WS-A + 'A'", "T OF G1(WS-I + 1)", "WS-A * WS-A * WS-A",
]  # fmt: skip


def expression_probes() -> list[Probe]:
    probes = [statement("expr", text, f"COMPUTE WS-C = {text}") for text in EXPRESSIONS]
    probes += [
        statement("expr", "two targets, one ROUNDED", "COMPUTE WS-C WS-D ROUNDED = WS-A / 3"),
        statement("expr", "EQUAL instead of =", "COMPUTE WS-C EQUAL WS-A + 1"),
        statement("expr", "target is subscripted", "COMPUTE T OF G2(2) = WS-A * 2"),
    ]
    return probes


def rounding_and_size_probes() -> list[Probe]:
    return [
        statement("size", "ADD ROUNDED", "ADD WS-A TO WS-C ROUNDED", values={"WS-A": "-0.5"}),
        statement("size", "COMPUTE ROUNDED tie", "COMPUTE WS-S ROUNDED = WS-A / 5", values={"WS-A": "12.5"}),
        statement("size", "MULTIPLY GIVING two targets", "MULTIPLY WS-A BY WS-B GIVING WS-C ROUNDED WS-D"),
        statement("size", "overflow truncates", "COMPUTE WS-S = 123"),
        statement("size", "ON SIZE ERROR END-ADD", "ADD 95 TO WS-S ON SIZE ERROR MOVE 1 TO SZ-FLAG END-ADD",
                  flag=True),
        statement("size", "SIZE ERROR without ON", "ADD 95 TO WS-S SIZE ERROR MOVE 1 TO SZ-FLAG", flag=True),
        statement("size", "ON and NOT ON SIZE ERROR", "ADD 5 TO WS-S ON SIZE ERROR MOVE 1 TO SZ-FLAG",
                  "        NOT ON SIZE ERROR CONTINUE END-ADD", flag=True),
        statement("size", "NOT ON SIZE ERROR first", "COMPUTE WS-S = WS-A * 10 NOT ON SIZE ERROR CONTINUE",
                  "        ON SIZE ERROR MOVE 1 TO SZ-FLAG", flag=True),
        statement("size", "DIVIDE size error", "DIVIDE 0.01 INTO WS-A GIVING WS-S",
                  "        ON SIZE ERROR MOVE 1 TO SZ-FLAG", flag=True),
    ]  # fmt: skip


def layout_probes() -> list[Probe]:
    return [
        statement("layout", "split after =", "COMPUTE WS-C =", "        WS-A + WS-B"),
        statement("layout", "split at an operator", "COMPUTE WS-C = WS-A", "        * WS-B + 1"),
        statement("layout", "one token per line", "ADD", "    WS-A", "    TO", "    WS-C"),
        statement("layout", "qualifier on the next line", "ADD X", "        OF G1 TO WS-C"),
        statement("layout", "subscript across lines", "ADD T OF G1 (", "        2 ) TO WS-C"),
        statement("layout", "continued data name", "ADD WS-", "-|    A TO WS-C"),
        statement("layout", "continued number", "ADD 12", "-|    5 TO WS-C"),
        statement("layout", "comment line inside", "COMPUTE WS-C = WS-A", "*|  comment", "        + WS-B"),
        statement("layout", "debug line inside", "COMPUTE WS-C = WS-A", "D|        * 100", "        + WS-B"),
        statement("layout", "lower case", "compute ws-c = ws-a + x of g1"),
        statement("layout", "statement in Area A", " |COMPUTE WS-C = WS-A + WS-B"),
        statement("layout", "two statements on a line", "ADD WS-A TO WS-C ADD WS-B TO WS-D"),
        statement("layout", "END-COMPUTE", "COMPUTE WS-C = WS-A END-COMPUTE"),
        statement("layout", "period on its own line", "COMPUTE WS-C = WS-A + WS-B", "    "),
        statement("layout", "to column 72", "COMPUTE WS-C = WS-A + WS-B + WS-A + WS-B + WS-A + 1.5 +   2"),
        statement("layout", "text past column 72", f"{'COMPUTE WS-C = WS-A + 1':<61}SEQXXXXX"),
        statement("layout", "unspaced", "COMPUTE WS-C=WS-A*WS-B-(WS-A/2)"),
    ]


def data_probes() -> list[Probe]:
    def target(label, decl, text, values):
        return statement("data", label, text, data=decl, values=values)

    return [
        target("group COMP inherited", ["01 GC COMP.", "    05 RC PIC S9(4)."], "COMPUTE RC = 400 * 100", {"RC": "1"}),
        target("PACKED-DECIMAL", ["01 RP PIC S9(3)V99 PACKED-DECIMAL."], "COMPUTE RP = WS-A * WS-B", {"RP": "1"}),
        target("BINARY unsigned", ["01 RB PIC 9(4) BINARY."], "SUBTRACT 7 FROM ZERO GIVING RB", {"RB": "1"}),
        target("COMP-4", ["01 R4 PIC S9(4) COMP-4."], "MULTIPLY 300 BY 300 GIVING R4", {"R4": "1"}),
        target("COMPUTATIONAL-3", ["01 R3 PIC S9(2)V9 COMPUTATIONAL-3."], "COMPUTE R3 = WS-A * 10", {"R3": "1"}),
        target("COMP-5 unsigned", ["01 R5 PIC 9(4) COMP-5."], "COMPUTE R5 = 99999 - 1", {"R5": "1"}),
        target("unsigned display", ["01 RU PIC 9(3)V9."], "ADD WS-A TO ZERO GIVING RU", {"RU": "1"}),
        target(
            "SIGN LEADING SEPARATE",
            ["01 SL PIC S9(3) SIGN LEADING SEPARATE."],
            "SUBTRACT 50 FROM ZERO GIVING SL",
            {"SL": "1"},
        ),
        target("SIGN TRAILING", ["01 ST PIC S9(3) SIGN TRAILING."], "SUBTRACT 50 FROM ZERO GIVING ST", {"ST": "1"}),
        target("PICTURE IS, lower case", ["01 PL picture is s999v99."], "COMPUTE PL = WS-A / 3", {"PL": "1"}),
        target("repeated symbols", ["01 PR PIC S999V99."], "COMPUTE PR = WS-A / 3", {"PR": "1"}),
        target("level 77", ["77 L7 PIC S9(3)."], "ADD WS-A TO WS-B GIVING L7", {"L7": "1"}),
        target(
            "FILLER sibling", ["01 GF.", "    05 FILLER PIC X.", "    05 F1 PIC 9(3)."], "ADD 5 TO F1", {"F1": "20"}
        ),
        target("REDEFINES", ["01 RA PIC S9(4).", "01 RR REDEFINES RA PIC S9(4)."], "ADD 1 TO RR", {"RR": "41"}),
        target(
            "88 under the target",
            ["01 RG PIC 9(3).", "    88 RG-BIG VALUE 100 THRU 999."],
            "ADD 150 TO RG",
            {"RG": "20"},
        ),
        target(
            "missing period, next 01 in Area A",
            ["01 MA PIC S9(3)V9 VALUE 1.5", "01 MB PIC S9(3)V9."],
            "ADD MA TO MB",
            {"MA": "1.5", "MB": "2"},
        ),
        target(
            "missing period, next 05 in Area A",
            ["01 GM.", "    05 MC PIC S9(3) VALUE 4", "05 MD PIC S9(3)."],
            "ADD MC TO MD",
            {"MC": "4", "MD": "3"},
        ),
        target(
            "two-level qualification",
            ["01 H1.", "    05 M1.", "        10 Y PIC 9(3).", "    05 M2.", "        10 Y PIC 9(3)."],
            "ADD 1 TO Y OF M1 OF H1",
            {"Y OF M1 OF H1": "8"},
        ),
        target(
            "ambiguous qualification",
            ["01 H2.", "    05 N1.", "        10 Z9 PIC 9(3).", "    05 N2.", "        10 Z9 PIC 9(3)."],
            "ADD 1 TO Z9 OF H2",
            {},
        ),
        target("P scaling operand", ["01 PP PIC 9(3)PP VALUE 1200."], "ADD PP TO WS-C", {}),
        target("edited operand", ["01 ED PIC ZZ9.99 VALUE 1.5."], "ADD ED TO WS-C", {}),
        target("edited DB target", ["01 EB PIC ZZ9.99DB."], "MULTIPLY WS-A BY WS-B GIVING EB", {"EB": "1"}),
        target("COMP-2 operand", ["01 FL COMP-2."], "ADD FL TO WS-C", {}),
        target("index item", ["01 GX.", "    05 TX PIC 9 OCCURS 3 INDEXED BY IX."], "ADD IX TO WS-C", {}),
        target("alphanumeric operand", ["01 AX PIC X(3) VALUE '123'."], "ADD AX TO WS-C", {}),
        target(
            "OCCURS in a group, qualified",
            ["01 GQ.", "    05 GR OCCURS 2.", "        10 GV PIC S9(3)."],
            "ADD 5 TO GV OF GR(2)",
            {"GV OF GR(2)": "-9"},
        ),
    ]


PROBES = form_probes() + expression_probes() + rounding_and_size_probes() + layout_probes() + data_probes()
