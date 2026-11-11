# cobarith

Where plausible Python translations of real COBOL arithmetic give a different stored answer from COBOL, measured
statement by statement on the AWS CardDemo application with GnuCOBOL 3.2.

## What it answers

A COBOL-to-Python translation has to reproduce COBOL's arithmetic exactly, and the parts that are easy to get wrong
sit in the storage step rather than in the arithmetic itself:

- COBOL keeps fixed-point decimals exactly and truncates toward zero on the way into a receiving field; Python
  `float` and `round()` do neither reliably.
- `ROUNDED` in COBOL sends halves away from zero; `Decimal.quantize(..., ROUND_HALF_EVEN)` sends them to even.
- A result that does not fit the receiving field is cut to its low-order digits (or, with `ON SIZE ERROR`, left
  alone), not raised as an exception.
- `COMP` fields are binary, with a width fixed by the picture, and the compiler's truncation setting decides
  whether an overflowing value wraps or is cut to the picture digits.

So the question this project answers is: for the arithmetic statements that really occur in a real application, how
often do four plausible Python translations store a different value than the COBOL program does, and on which
inputs?

Nothing here is a claim about any vendor's product or translator. The four translations are written for this
measurement and stand for hand or tool translations in general.

## How it works

1. `cobarith/source.py` reads CardDemo's fixed-format source (columns 8-72, comment and continuation lines) and
   expands `COPY` and `EXEC SQL INCLUDE` from the copybooks in the tree.
2. `cobarith/data.py` parses `PICTURE` clauses into digits, scale, signedness and capacity, and resolves data names
   with their qualifiers.
3. `cobarith/stmt.py` scans `ADD`, `SUBTRACT`, `MULTIPLY`, `DIVIDE` and `COMPUTE` statements after `PROCEDURE
   DIVISION` and parses each into assignments over exact expressions, or classifies it as unsupported with one
   reason.
4. `cobarith/cases.py` generates pinned random inputs and z3-witnessed boundary inputs: a rounding tie, an exactly
   representable value, an overflow, a negative value for an unsigned field.
5. `cobarith/harness.py` generates one fixed-format GnuCOBOL program per statement, feeds it the cases, runs the
   statement and prints every receiving field back, so the stored value is measured rather than modelled.
6. `cobarith/translate.py` computes the same statement five ways: COBOL's own storage rule (`cobol_exact`), the
   exact result with no storage rule (`exact_no_size`), floats with `round()` (`float_round`), `Decimal` with
   `ROUND_HALF_EVEN` (`decimal_half_even`) and floats truncated (`float_truncate`).
7. `experiment.py` runs all of it and writes `results/metrics.json` and `results/statements.jsonl`.

The random cases exercise the whole picture range, so the counts measure how exposed each statement is, not a rate
in production data.

## Running it

```sh
make test                                     # unittest
make lint                                     # ruff check and format
python experiment.py --out results/metrics.json
python demo.py                                # short console summary
python demo.py --readme README.md --out README.md
```

`experiment.py` needs GnuCOBOL 3.2: it uses `$ARCTURUS_COBC` when that is set and `cobc` on `PATH` otherwise. The
CardDemo sources under `upstream/` are committed; nothing is fetched at run time. `make data-check` re-checks them
against `upstream/MANIFEST.json`.

## Results

Rendered by `demo.py` from `results/metrics.json` and `results/statements.jsonl`, which come from running
GnuCOBOL. No result number is typed by hand.

<!-- results:start -->
_No results yet. Run `python experiment.py --out results/metrics.json`, then
`python demo.py --readme README.md --out README.md`._
<!-- results:end -->

## Scope and limits

- The reference is GnuCOBOL 3.2 with `-std=ibm`, nothing else. In particular `-std=ibm` leaves binary truncation
  off, so a `COMP` field whose value does not fit its binary width wraps at 16, 32 or 64 bits instead of being cut
  to its picture digits. Whether IBM Enterprise COBOL agrees depends on its `TRUNC` option; that is not tested here
  and stays an open question.
- Statements are measured one at a time, in isolation, with no data flow between them: a receiving field's prior
  value and the operands' values come from the case, not from an earlier statement.
- Random and boundary inputs span the picture ranges, so a difference count states exposure, not a rate.
- Intrinsic functions, `LENGTH OF`, special registers, `REMAINDER`, `CORRESPONDING`, exponentiation, reference
  modification, numeric-edited operands, `P` scaling, floating-point usages and index items are listed with a
  reason but not harnessed; they are counted in `statements_unsupported`.
- Some IBM system copybooks (`DFHAID`, `DFHBMSCA`, `CMQ*`, `SQLCA`) are not part of CardDemo, so fields that come
  only from them stay unresolved. Those statements are listed, not harnessed.

## Upstream data

`upstream/carddemo/` is a pinned copy of
[aws-mainframe-modernization-carddemo](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) at
commit `59cc6c2fd7ebd7ef7925cad552a01a4b8b6e4d5e`, Apache-2.0; `LICENSE` and `NOTICE` are copied alongside it.
`tools/fetch_data.py --verify` checks every file against `upstream/MANIFEST.json`.

## Design notes

`docs/DESIGN.md` covers the parsing rules, the storage rule, the translations and the case design;
`docs/INTERVIEW.md` covers how to explain the project and what the numbers do and do not show.
