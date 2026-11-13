# cobarith

Where plausible Python translations of real COBOL arithmetic give a different stored answer from COBOL, measured
statement by statement on the AWS CardDemo application with GnuCOBOL 3.2.

## One real example

CardDemo's bill-payment program `COBIL00C` makes the next transaction ID like this (line 217):

```cobol
       05 WS-TRAN-ID-NUM             PIC 9(16) VALUE ZEROS.
       ...
           MOVE TRAN-ID     TO WS-TRAN-ID-NUM
           ADD 1 TO WS-TRAN-ID-NUM
```

GnuCOBOL stores `9625004552692988 + 1` as `9625004552692989`. A translation that computes through Python `float`
stores `9625004552692988` again, so the "next" ID equals the last one: a double cannot hold every integer above
2^53. Both float translations store a wrong ID on 33 of the statement's 1,000 random inputs, sometimes repeating the
last ID and sometimes skipping ahead. At the top of the
picture the storage rule shows up instead. `9999999999999999 + 1` leaves `0` in a `PIC 9(16)` field in COBOL, while
every translation without COBOL's storage rule keeps `10000000000000000`.

The inputs span each field's whole picture range, so this is exposure, not a claim that CardDemo's real IDs get that
large. Both values come from `results/statements.jsonl` (`COBIL00C:217:ADD`), measured by running the statement in
GnuCOBOL.

## What the run found

- 201 arithmetic statements, found in 28 of the 44 CardDemo programs scanned. 142 are harnessed, and 59 are listed as unsupported with a
  reason.
- COBOL's storage rule, modelled exactly (`cobol_exact`), stores the same value as GnuCOBOL on every one of the
  142,280 cases (142,000 pinned random and 280 solver-found boundary cases).
- Under each of the four translations, 88 statements store a different value in at least one case. All 88 include
  storage differences: a result too large for its field, a negative value in an unsigned field or a binary wrap,
  none of which the translations model.
- On the arithmetic alone, ignoring storage, `float_truncate` differs on 23 statements, `float_round` on 3 and
  `decimal_half_even` on 1 (the monthly-interest `COMPUTE` in `CBACT04C`, where COBOL truncates to the cent and the translation rounds).

The full tables, rendered from `results/`, are under [Results](#results).

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

Python 3.12 or later and GnuCOBOL 3.2 (`brew install gnucobol` on macOS):

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install z3-solver==5.3.3.0 ruff
make test                                     # unittest; compiler-backed tests skip without cobc
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
GnuCOBOL. Nothing between the markers is typed by hand; the summary at the top quotes these files. Rerunning the
experiment reproduces both files byte for byte.

<!-- results:start -->
## Results

### Metrics

| Metric | Value |
| --- | --- |
| `cases_boundary` | 280 |
| `cases_random` | 142000 |
| `cobol_exact_agreement` | 1.000000 |
| `cobol_exact_cases_differ` | 0 |
| `copybooks_missing` | 9 |
| `decimal_half_even_cases_differ_arithmetic` | 356 |
| `decimal_half_even_cases_differ_boundary` | 236 |
| `decimal_half_even_cases_differ_random` | 8196 |
| `decimal_half_even_cases_differ_storage` | 8076 |
| `decimal_half_even_statements_differ` | 88 |
| `decimal_half_even_statements_differ_arithmetic` | 1 |
| `exact_no_size_cases_differ_arithmetic` | 0 |
| `exact_no_size_cases_differ_boundary` | 234 |
| `exact_no_size_cases_differ_random` | 7842 |
| `exact_no_size_cases_differ_storage` | 8076 |
| `exact_no_size_statements_differ` | 88 |
| `exact_no_size_statements_differ_arithmetic` | 0 |
| `float_round_cases_differ_arithmetic` | 430 |
| `float_round_cases_differ_boundary` | 240 |
| `float_round_cases_differ_random` | 8266 |
| `float_round_cases_differ_storage` | 8076 |
| `float_round_statements_differ` | 88 |
| `float_round_statements_differ_arithmetic` | 3 |
| `float_truncate_cases_differ_arithmetic` | 3250 |
| `float_truncate_cases_differ_boundary` | 235 |
| `float_truncate_cases_differ_random` | 11091 |
| `float_truncate_cases_differ_storage` | 8076 |
| `float_truncate_statements_differ` | 88 |
| `float_truncate_statements_differ_arithmetic` | 23 |
| `programs_total` | 44 |
| `statements_add` | 99 |
| `statements_compute` | 84 |
| `statements_decimal_risk` | 23 |
| `statements_divide` | 1 |
| `statements_flag_float` | 23 |
| `statements_flag_scale` | 1 |
| `statements_flag_sign` | 4 |
| `statements_flag_size` | 118 |
| `statements_harnessed` | 142 |
| `statements_multiply` | 0 |
| `statements_subtract` | 17 |
| `statements_total` | 201 |
| `statements_unsupported` | 59 |
| `unsupported_corresponding` | 0 |
| `unsupported_exponentiation` | 0 |
| `unsupported_floating_point_usage` | 0 |
| `unsupported_index_item` | 0 |
| `unsupported_intrinsic_function` | 28 |
| `unsupported_length_of` | 4 |
| `unsupported_non_numeric_field` | 0 |
| `unsupported_nonnumeric_literal` | 0 |
| `unsupported_numeric_edited_operand` | 0 |
| `unsupported_p_scaling` | 0 |
| `unsupported_reference_modification` | 0 |
| `unsupported_remainder` | 1 |
| `unsupported_rounded_mode` | 0 |
| `unsupported_special_register` | 1 |
| `unsupported_syntax` | 0 |
| `unsupported_unresolved_name` | 25 |

### Arithmetic differences

| Statement | Translations | Example (decimal) |
| --- | --- | --- |
| `CBACT04C:352:ADD` | float_truncate | WS-TOTAL-INT=79772.94, ACCT-CURR-BAL=-78930.80 -> COBOL ACCT-CURR-BAL=842.14; float_truncate ACCT-CURR-BAL=842.13 |
| `CBACT04C:464:COMPUTE` | float_round, decimal_half_even, float_truncate | WS-MONTHLY-INT=80730.38, TRAN-CAT-BAL=-86175.28, DIS-INT-RATE=-3899.65 -> COBOL WS-MONTHLY-INT=280044.52; float_round WS-MONTHLY-INT=280044.53 |
| `CBACT04C:467:ADD` | float_truncate | WS-MONTHLY-INT=-405130930.65, WS-TOTAL-INT=674681504.80 -> COBOL WS-TOTAL-INT=269550574.15; float_truncate WS-TOTAL-INT=269550574.14 |
| `CBPAUP0C:289:SUBTRACT` | float_truncate | PA-APPROVED-AMT=80961.00, PA-APPROVED-AUTH-AMT=-74274.42 -> COBOL PA-APPROVED-AUTH-AMT=-155235.42; float_truncate PA-APPROVED-AUTH-AMT=-155235.41 |
| `CBPAUP0C:292:SUBTRACT` | float_truncate | PA-TRANSACTION-AMT=-18033.49, PA-DECLINED-AUTH-AMT=-51000.14 -> COBOL PA-DECLINED-AUTH-AMT=-32966.65; float_truncate PA-DECLINED-AUTH-AMT=-32966.64 |
| `CBSTM03A:429:ADD` | float_truncate | TRNX-AMT=-706715378.72, WS-TOTAL-AMT=841215095.37 -> COBOL WS-TOTAL-AMT=134499716.65; float_truncate WS-TOTAL-AMT=134499716.64 |
| `CBTRN02C:403:COMPUTE` | float_truncate | WS-TEMP-BAL=43126.05, ACCT-CURR-CYC-CREDIT=-26495.38, ACCT-CURR-CYC-DEBIT=-11346.51, DALYTRAN-AMT=15558.30 -> COBOL WS-TEMP-BAL=409.43; float_truncate WS-TEMP-BAL=409.42 |
| `CBTRN02C:508:ADD` | float_truncate | DALYTRAN-AMT=-161388373.55, TRAN-CAT-BAL=352482685.01 -> COBOL TRAN-CAT-BAL=191094311.46; float_truncate TRAN-CAT-BAL=191094311.45 |
| `CBTRN02C:527:ADD` | float_truncate | DALYTRAN-AMT=63487.67, TRAN-CAT-BAL=-76458.23 -> COBOL TRAN-CAT-BAL=-12970.56; float_truncate TRAN-CAT-BAL=-12970.55 |
| `CBTRN02C:547:ADD` | float_truncate | DALYTRAN-AMT=-82107.04, ACCT-CURR-BAL=38331.29 -> COBOL ACCT-CURR-BAL=-43775.75; float_truncate ACCT-CURR-BAL=-43775.74 |
| `CBTRN02C:549:ADD` | float_truncate | DALYTRAN-AMT=-40852883.40, ACCT-CURR-CYC-CREDIT=-5327697491.32 -> COBOL ACCT-CURR-CYC-CREDIT=-5368550374.72; float_truncate ACCT-CURR-CYC-CREDIT=-5368550374.71 |
| `CBTRN02C:551:ADD` | float_truncate | DALYTRAN-AMT=-42290.57, ACCT-CURR-CYC-DEBIT=-21842.94 -> COBOL ACCT-CURR-CYC-DEBIT=-64133.51; float_truncate ACCT-CURR-CYC-DEBIT=-64133.50 |
| `CBTRN03C:200:ADD` | float_truncate | TRAN-AMT=-95896.15, WS-PAGE-TOTAL=67626.45, WS-ACCOUNT-TOTAL=45022.55 -> COBOL WS-PAGE-TOTAL=-28269.70, WS-ACCOUNT-TOTAL=-50873.60; float_truncate WS-PAGE-TOTAL=-28269.69, WS-ACCOUNT-TOTAL=-50873.59 |
| `CBTRN03C:287:ADD` | float_truncate | TRAN-AMT=72927.07, WS-PAGE-TOTAL=9973.01, WS-ACCOUNT-TOTAL=-89269.27 -> COBOL WS-PAGE-TOTAL=82900.08, WS-ACCOUNT-TOTAL=-16342.20; float_truncate WS-PAGE-TOTAL=82900.08, WS-ACCOUNT-TOTAL=-16342.19 |
| `CBTRN03C:297:ADD` | float_truncate | WS-PAGE-TOTAL=687167962.74, WS-GRAND-TOTAL=-991301806.53 -> COBOL WS-GRAND-TOTAL=-304133843.79; float_truncate WS-GRAND-TOTAL=-304133843.78 |
| `COBIL00C:217:ADD` | float_round, float_truncate | WS-TRAN-ID-NUM=9625004552692988 -> COBOL WS-TRAN-ID-NUM=9625004552692989; float_round WS-TRAN-ID-NUM=9625004552692988 |
| `COBIL00C:234:COMPUTE` | float_truncate | ACCT-CURR-BAL=9678357289.81, TRAN-AMT=247178171.28 -> COBOL ACCT-CURR-BAL=9431179118.53; float_truncate ACCT-CURR-BAL=9431179118.52 |
| `COPAUA0C:666:COMPUTE` | float_truncate | WS-AVAILABLE-AMT=-78443.95, PA-CREDIT-LIMIT=21925.47, PA-CREDIT-BALANCE=97565.43 -> COBOL WS-AVAILABLE-AMT=-75639.96; float_truncate WS-AVAILABLE-AMT=-75639.95 |
| `COPAUA0C:674:COMPUTE` | float_truncate | WS-AVAILABLE-AMT=-17716.14, ACCT-CREDIT-LIMIT=-80285.15, ACCT-CURR-BAL=-41428.20 -> COBOL WS-AVAILABLE-AMT=-38856.95; float_truncate WS-AVAILABLE-AMT=-38856.94 |
| `COPAUA0C:815:ADD` | float_truncate | WS-APPROVED-AMT=302400820.36, PA-APPROVED-AUTH-AMT=-382053667.07 -> COBOL PA-APPROVED-AUTH-AMT=-79652846.71; float_truncate PA-APPROVED-AUTH-AMT=-79652846.70 |
| `COPAUA0C:817:ADD` | float_truncate | WS-APPROVED-AMT=9450.97, PA-CREDIT-BALANCE=5669.11 -> COBOL PA-CREDIT-BALANCE=15120.08; float_truncate PA-CREDIT-BALANCE=15120.07 |
| `COPAUA0C:821:ADD` | float_truncate | PA-TRANSACTION-AMT=-64989.88, PA-DECLINED-AUTH-AMT=61579.37 -> COBOL PA-DECLINED-AUTH-AMT=-3410.51; float_truncate PA-DECLINED-AUTH-AMT=-3410.50 |
| `COTRN02C:449:ADD` | float_round, float_truncate | WS-TRAN-ID-N=9288065211967810 -> COBOL WS-TRAN-ID-N=9288065211967811; float_round WS-TRAN-ID-N=9288065211967812 |

### Storage

| Translation | Statements differ | Cases: storage | Cases: arithmetic |
| --- | ---: | ---: | ---: |
| exact_no_size | 88 | 8076 | 0 |
| float_round | 88 | 8076 | 430 |
| decimal_half_even | 88 | 8076 | 356 |
| float_truncate | 88 | 8076 | 3250 |

COBOL exact agreement: 1.000000 (0 differing cases).
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
- This is a measurement on CardDemo, not a COBOL compiler, a translator or a claim of general COBOL compatibility.

### Known gaps

The last automated code review found four medium issues. None touches a statement CardDemo contains, so the
measured results stand, but they are real and are not fixed:

- A sign and its digits split across a fixed-format continuation line are refused as unsupported. CardDemo's 11
  continuation lines are all inside HTML string literals.
- `COPY REPLACING` of a word also rewrites the same text inside a quoted literal. CardDemo's only copybook copied with
  `REPLACING` (`CSSETATY`) replaces names in `IF` and `MOVE` statements, and its one literal is `'*'`.
- There is no compiler-backed unit test for 32-bit `COMP` wrapping (16 and 64 bits have one). The experiment does
  run CardDemo's 32 harnessed statements with 32-bit binary targets through GnuCOBOL, but whether their random
  cases reach 32-bit overflow was not checked.
- The harness's compile-failure and wrong-output-count paths have no tests. Either failure stops the experiment;
  neither can change a stored value.

## Upstream data

`upstream/carddemo/` is a pinned copy of
[aws-mainframe-modernization-carddemo](https://github.com/aws-samples/aws-mainframe-modernization-carddemo) at
commit `59cc6c2fd7ebd7ef7925cad552a01a4b8b6e4d5e`, Apache-2.0; `LICENSE` and `NOTICE` are copied alongside it.
`tools/fetch_data.py --verify` checks every file against `upstream/MANIFEST.json`.

## Design notes

`docs/DESIGN.md` covers the parsing rules, the storage rule, the translations and the case design;
`docs/INTERVIEW.md` covers how to explain the project and what the numbers do and do not show.

## How this was built

Yash Gupta directed the project. AI coding agents (Claude Code and an agent build pipeline) wrote most of the code
and tests, and automated model reviews checked them. Those reviews are not an external audit. The evidence is the
code, the tests and the GnuCOBOL-measured results in `results/`.

## License

MIT for this repository's code (`LICENSE`). The CardDemo sources in `upstream/carddemo/` stay under their own
Apache-2.0 license, with its `LICENSE` and `NOTICE`.
