# Design notes

## The question

CardDemo is real, production-shaped COBOL. Its arithmetic statements are short and ordinary: add a transaction
amount to a running total, subtract an approved amount, divide a sum by a count, compute the difference of two
limits. A translator that turns those statements into Python has one step that is easy to underestimate: store the
result the way COBOL would have stored it.

Everything here exists to measure that step, statement by statement, with every number coming out of GnuCOBOL
rather than out of a model of GnuCOBOL.

## Pipeline

```
.cbl + copybooks
   -> source.py    tokens (fixed format, COPY expanded)
   -> data.py      data items with PICTURE parsed
   -> stmt.py      Statement: variables, targets, assignments, flags (or a reason)
   -> cases.py     pinned random cases + z3 boundary cases
   -> harness.py   one generated GnuCOBOL program per statement, run over the cases
   -> translate.py the same statement five ways
   -> experiment.py metrics.json + statements.jsonl
   -> demo.py      the README results block
```

Each layer is independently testable, and only `harness.py` needs a compiler; the tests that call it skip when
`cobc` is absent.

## Reading fixed-format source

The code area is columns 8-72. Columns 1-6 and 73-80 are dropped; column 7 `*` or `/` marks a comment and `D`/`d` a
debug line, both skipped. A `-` in column 7 continues the previous line, and COBOL has two different continuations:

- with no open literal, the continuation's stripped text is appended to the previous text, so one word can be built
  from two lines;
- with an open literal and a leading quote, the previous line is padded to column 72 with spaces and the rest of the
  continuation (minus that quote) becomes part of the literal.

The lexer keeps a `(line, column)` pair for every character of the logical text, so a token can report where it came
from even after continuations. That is what keeps the `PROGRAM:FILE:LINE:VERB` ids stable, and why the scanner works
on one flattened string with a parallel position list instead of line by line.

`PIC`/`PICTURE` (optionally `IS`) is special-cased: the picture string is one token and a trailing period is a
separate `.` token, because otherwise `9(02).` would swallow the statement terminator.

Copybooks are found by upper-cased stem across the tree; when a name exists in several folders, the one whose path
shares the longest prefix with the including file wins (CardDemo has parallel `app/cpy` and per-application `cpy`
trees). Missing names go into `library.missing` instead of raising, so one unresolved IBM system copybook does not
sink a whole program.

`REPLACING` is applied to the copybook text before tokenizing, which is what the compiler does. Pseudo-text
(`==...==`) replaces its inner text anywhere, including inside a hyphenated word; a plain word or literal replaces
whole words only, so `WS-OLD` does not touch `WS-OLDER`.

## PICTURE and data items

`parse_pic` classifies hard: a picture with any `X`, `A` or `N` is alphanumeric; with any `P` it is `scaled`; with
only `S`, `9` and `V` it is numeric; anything else is numeric-edited. `capacity` is `10**(digits+scale) - 1` units,
which is what the storage rule compares against. For edited pictures the digit positions are `9`, `Z`, `*` plus each
floating `+`, `-` or `$` beyond the first of its kind, which reproduces the compiler's count for pictures such as
`-ZZZ,ZZ9.99` (6 digits, 2 decimals).

`binary_bits` follows the 2-4-8 byte widths `-std=ibm` uses: 16 bits up to 4 digits, 32 up to 9, 64 above.

Data items come from level numbers 01-49 and 77. Levels 66 (`RENAMES`) and 88 (condition names) are skipped, and so
are `FD`/`SD` entries, because the harness supplies its own files. An entry ends at its period or, when the period is
missing, where the next level number starts in Area A (columns 8-11): that is exactly where GnuCOBOL accepts the
omission, with a warning. A number in Area B belongs to the clause before it (`OCCURS 1 TO 5`, `VALUES 1 THRU 77`),
and an `FD` or `SD` entry is skipped to its period, so `RECORD ... FROM 10 TO 80` never becomes an item. Usage inherits: a group declared `COMP` makes its
children binary unless they say otherwise. `INDEXED BY` names become items with `INDEX` usage, so a statement using
one is rejected with `index item` instead of `unresolved name`.

Name resolution is deliberately strict: `NAME [OF|IN qualifier]...` must match exactly one item, with the qualifiers
appearing as ancestors in the given order. Ambiguity is an error, not a guess.

## Statements and reasons

The scanner walks the tokens after `PROCEDURE DIVISION`, skips `EXEC ... END-EXEC` blocks, and starts a statement at
each arithmetic verb. A statement ends before a period, an `END-*` scope terminator, a `[NOT] [ON] SIZE ERROR`
phrase (which is recorded on the statement), or the next verb or statement word.

Parsing is a small recursive-descent parser over the eleven forms in the specification, producing `Assignment`
objects of exact expressions: `Literal`, `Field`, `Unary`, `Binary`. A numeric literal or `ZERO` is an operand in
every position, including the one right before `GIVING` (`SUBTRACT 1 FROM ZERO GIVING T`); without `GIVING` that
position receives the result, so it must be a field. A sign touching a number is that literal's sign, as COBOL reads
it: in a list it starts a new value (`ADD A -1 TO B` adds A and -1), and where an operator is expected it is a syntax
error (`COMPUTE T = A -1`, which GnuCOBOL also rejects). Variables are de-duplicated by name, qualifiers
and subscript text, so `WS-A(1)` and `WS-A(2)` are different variables while `WS-A` twice is one.

Reasons are checked in two passes, which fixes priority without tangled conditions: first the token-level features
(intrinsic functions, `LENGTH OF`, special registers, `REMAINDER`, `CORRESPONDING`, exponentiation, reference
modification, nonnumeric literals, `ROUNDED MODE`) in token order, then the resolution problems (`unresolved name`,
`index item`, `floating-point usage`, `non-numeric field`, `P scaling`, `numeric-edited operand`) in variable order.
Whatever the parser then rejects is `syntax`. One reason per statement, always.

The `numeric-edited operand` rule is the subtle one: an edited picture is fine as a receiving field of a `GIVING`
form, because the harness declares it with the statement's own picture, but not as a value the statement reads,
because reading an edited field means de-editing it first.

## Flags

Flags are cheap interval arithmetic over the parsed expression, not solver calls. A field's interval is
`[-cap, cap]` (or `[0, cap]` unsigned) in decimal value, a literal is a point, `+` and `-` add intervals, `*` takes
the four corner products, and a division whose divisor interval straddles zero is unbounded. From the interval and
the exact scale of the expression:

- `scale`: the expression's scale is unbounded (a division) or wider than the target's;
- `float`: there is a division, or the target or any operand has decimals, or the bound times `10**scale` is at
  least `2**53` (beyond exact integer floats), or the bound is unbounded;
- `size`: the bound is unbounded or at least the target's capacity in value;
- `sign`: the target is unsigned and the interval can be negative.

Flags decide nothing about the measurement. They steer where a boundary case is worth solving for, and they give the
`statements_decimal_risk` metric.

## Cases

Random cases are pinned to `sha256` of the statement id plus `|random`, so a rerun over the same sources gives the
same numbers on any machine. Odd cases may use the full picture range; even cases are capped at
`min(capacity, 10**(scale + min(digits, 5)) - 1)`, which keeps most draws at a realistic magnitude while still
letting wide ones appear. A case that would divide by zero is redrawn with the same parity, so the pattern of wide
and narrow cases is not disturbed. A divisor that is zero in every draw (`DIVIDE ZERO INTO A GIVING T`) stops after
1,000 redraws in a row, with the cases found so far; GnuCOBOL raises a size error there, and no case can show it.

Boundary cases are the interesting half, and they are solved rather than sampled. For each flagged kind and each
receiving field, z3 is asked for an integer assignment to the variables, within their picture ranges (and, after the
first attempt, inside a box around a seeded random centre), that makes the assignment's exact result a rounding tie,
an exactly representable value, an overflow, or a negative value for an unsigned field, with every divisor
constrained non-zero. An `rlimit` of two million bounds what a pathological statement can cost.

Every solver answer is re-checked with `exact_results` before it is kept, so a case is reported only if the exact
arithmetic, not z3's real approximation, really satisfies its kind. A kind that is unsatisfiable inside a box is
retried with another centre, up to twelve attempts; if none succeed, that kind simply has no case for that target.

Boundary cases are deterministic for one z3 version and `rlimit` (two runs here are byte-identical), but unlike
the random cases they are not pinned across implementations: another z3 version, or another solver, may pick
different witnesses, so boundary counts can shift while every random-case count stays the same.

## The harness

`program(stmt)` re-emits the statement as generated GnuCOBOL.

- Every variable becomes a level-01 field declaring the statement's own picture text and usage.
- The statement runs as written: its own tokens, one space apart, with each data reference (qualifiers and
  subscripts included) renamed to its field, so GnuCOBOL applies the verb's own rules. A sign that touched its
  number stays glued (`ADD A -1 TO B`), because COBOL reads that as one literal; other touching tokens (`A+B`) mean
  the same with spaces, so they may wrap, and a word that can't fit in columns 8-72 is refused rather than written
  past column 72. No `EXEC` blocks, file sections or
  CICS are needed.
- Input cases come from `cases.txt`, each variable as sign-leading-separate signed digits, moved into the field
  before the statement runs.
- Each receiving field is displayed afterwards through a signed display field wide enough for a binary field's whole
  range, followed by the size-error flag. GnuCOBOL's de-editing `MOVE` drops a `DB` sign (it keeps `CR`, `+` and
  `-`), so for a `DB` picture the harness checks the field's last two characters and restores the sign.

Long lines are split at word boundaries inside the code area (65 columns of code starting at column 8) so the
generated program stays valid fixed format. Names are sanitised to legal COBOL data names and de-duplicated.

The harness is where a model could be wrong, so the tests compare it against known compiler behaviour: display
overflow keeping the low-order digits, `ON SIZE ERROR` keeping the prior value, `COMP` wrapping at its binary width
(`200 * 200` into `S9(4) COMP` gives `-25536`), division truncating toward zero, and `ROUNDED` sending halves away
from zero (`125 / 2` rounded gives `63`, unrounded `62`).

## The storage rule

`store(units, pic, usage, prior, size_error)` holds the whole COBOL side of the comparison.

Non-`COMP`: a magnitude above capacity keeps `prior` and raises when the statement has a size-error phrase;
otherwise it keeps the low-order digits with the sign. Then an unsigned field stores the absolute value, which is
why a negative value moved into an unsigned display field comes out positive.

`COMP`: `-std=ibm` does not truncate to the picture, so the value is not cut to `digits`; it is cut by the binary
width. Outside the signed (or unsigned) range of `binary_bits`, the field keeps `prior` and raises when size-error
handling is on, and otherwise wraps: unsigned modulo `2**bits`, signed into the two's-complement window.

Both branches are checked against the compiler in `tests/test_harness.py`, which is what makes the rest of the
measurement trustworthy.

## The four translations

`translate` returns stored units per receiving field for five names. `cobol_exact` is the rule above.
`exact_no_size` is the exact result with no storage rule at all, which isolates the storage step (`storage_changed`
compares those two). The other three model translations people actually write:

- `float_round`: evaluate in Python floats, `round(x, s)`, then `int(round(... * 10**s))`;
- `decimal_half_even`: `Decimal` in the default context, `quantize(10**-s, ROUND_HALF_EVEN)`;
- `float_truncate`: `math.trunc(x * 10**s)` on the float result.

All three ignore `ROUNDED` and ignore the size and sign rules, because a translation that keeps a `Decimal` or a
`float` rarely re-implements them. That is exactly the gap being measured. A case counts as an arithmetic
difference only when the storage rule did not change the value anyway, and as a storage difference otherwise;
keeping those buckets apart is what stops the report from blaming floating point for a plain overflow.

## Experiment output

`metrics.json` is numbers only with sorted keys, and `statements.jsonl` carries one record per statement with the
first differing case per translation (inputs, COBOL's stored units, the translation's units). Both are written with
Unix newlines and deterministic ordering, so two runs are byte-identical; the runner checks that. A `cobol_exact`
difference is reported, never hidden and never removed by bending the rule to match.

`demo.py` renders the README block from those two files only. It never recomputes anything and never contains a
number, which is why the README can be regenerated safely after every experiment.

## Trade-offs

- **One statement at a time.** No data flow, so a receiving field's prior value and the operands' values come from
  the case. Cheaper and reproducible, and enough to find the storage differences; a whole-program trace would need a
  working-storage model and a lot more runtime.
- **Run the statement as written.** The harness keeps the statement's own tokens and renames only its data
  references, so no re-rendering can change what is measured, and no CICS, MQ or file handling is needed. The cost is
  that statements whose operands can't be harnessed (intrinsic functions, MQ fields from missing system copybooks)
  are listed, not run.
- **Wide inputs.** Random cases span the picture ranges instead of resembling real transaction data. That maximises
  the chance of finding a difference per statement; it means counts are exposure, not rates.
- **z3 with a rlimit** rather than a full bit-vector encoding: the exact arithmetic is done in rationals and the
  integer variables keep the search small. A few statements will simply not produce every kind of boundary case.
- **GnuCOBOL only.** It is the compiler available here. IBM Enterprise COBOL's `TRUNC` option changes the `COMP`
  story, and the README says so instead of guessing.

## What the parser covers, and what it doesn't

Covered: the eleven arithmetic forms of the specification with identifiers (qualified, subscripted), numeric
literals and `ZERO` in every operand position; `ROUNDED`; `ON SIZE ERROR`; receiving fields in `DISPLAY`, `COMP`,
`COMP-3`, `COMP-5` and numeric-edited usage, each checked against GnuCOBOL; data entries with or without the
optional period; `COPY` and `EXEC SQL INCLUDE` members. Every rule above was probed against GnuCOBOL 3.2 with
`-std=ibm`, and the tests keep those probes.

Not covered, by the specification's scope: the reasons it lists (intrinsic functions, `LENGTH OF`, special
registers, `REMAINDER`, `CORRESPONDING`, exponentiation, reference modification, nonnumeric literals, `ROUNDED MODE`,
floating-point and `P`-scaled operands, edited operands); figurative constants other than `ZERO`; free-format source;
report-writer (`RD`) entries; and any other COBOL statement or data-division feature. Source that GnuCOBOL itself
rejects is not modelled. A milestone that wanted more of COBOL would widen the specification first, not the parser
alone.

## Open questions

- Does IBM Enterprise COBOL with `TRUNC(BIN)` agree with GnuCOBOL `-std=ibm` on `COMP` overflow, and does the default
  `TRUNC(STD)` disagree? Not tested here.
- How much do interim results inside a `COMPUTE` matter for these statements? The generated code is itself a
  `COMPUTE`, so the measurement inherits the compiler's own interim rules instead of modelling them.
- What would the numbers look like on real transaction data rather than the full picture range? A separate
  experiment, and a different question.
