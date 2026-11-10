# How to explain this project

## The one-sentence version

I took a real COBOL application, ran its arithmetic statements through the compiler and through four plausible
Python translations, and counted the statements and inputs where the Python code stores a different value.

## Why it matters

Every COBOL-to-Python migration has an arithmetic step that looks trivial and is not. COBOL stores exact fixed-point
decimals, truncates toward zero, keeps the low-order digits when a result does not fit the receiving field, sends
`ROUNDED` halves away from zero, and stores `COMP` values in binary fields whose width comes from the picture. A
Python translation written with `float` and `round()`, or with `Decimal` and its default half-even rounding, or with
no size handling at all, will silently store a different number on some inputs. Nothing crashes; the balance is just
wrong by a cent, or by a lot more when a field overflows.

So the useful question for a migration is not whether the arithmetic is right in general, but which statements are
exposed and on which inputs. That is what this measures.

## The method, in four moves

1. **Parse the real source.** Fixed-format columns, `COPY` expansion, `PICTURE` parsing, qualified names. Only the
   five arithmetic verbs are kept, and each statement becomes exact expressions over its variables.
2. **Run COBOL itself.** For each statement, generate a small GnuCOBOL program with the same pictures and usages,
   feed it cases, and print the stored values back. The ground truth is the compiler's output, not my reading of the
   standard.
3. **Run four translations.** The same statement, in exact Python arithmetic: with the COBOL storage rule, with no
   storage rule, in floats with `round`, in `Decimal` with half-even, and in floats truncated. Compare stored units.
4. **Find the interesting inputs.** Pinned random cases over the picture ranges, plus z3-solved boundary cases: a
   rounding tie, an exactly representable value, an overflow, a negative value into an unsigned field.

## What the numbers mean

- *Statements differ*: at least one case of that statement stored a different value under that translation.
- *Cases differ*: how many cases did, split into random and boundary.
- *Storage versus arithmetic*: a difference is counted as storage when the COBOL storage rule itself changed the
  exact result (overflow, wrap, size error) and as arithmetic otherwise. Keeping them apart is the honest part: it
  stops floating point from being blamed for a plain overflow.
- *COBOL exact agreement*: how often my implementation of the storage rule agrees with the compiler on the same
  cases. It should be 1.0; when it is not, the model is wrong and the differences are suspect.

## What the numbers do not mean

- They are not rates in production data. Inputs span the whole picture range on purpose, to find the differences.
- They say nothing about any vendor's translator, including Hypercubic's. The four translations were written for this
  measurement and stand for common hand or tool translations in general.
- They hold for GnuCOBOL 3.2 with `-std=ibm`. In particular `-std=ibm` leaves binary truncation off, so `COMP` fields
  wrap at 16, 32 or 64 bits. Whether IBM Enterprise COBOL agrees depends on its `TRUNC` option; that is an open
  question and is written down as one.
- Statements are measured one at a time, with no data flow, no intrinsic functions, and no MQ or CICS fields.

## Questions I expect, and the answers

**Why not just use `Decimal`?** Because `Decimal`'s default rounding is half-even while COBOL's `ROUNDED` is half
away from zero, and because `Decimal` says nothing about what a field can hold. The `decimal_half_even` row exists to
make exactly that point with numbers.

**Why z3?** Because the interesting inputs are rare. A rounding tie for `WS-A / 2` is one parity out of the whole
range; an overflow of a `COMP` field is a narrow band. Sampling would find some of them eventually; asking a solver
for one finds them in milliseconds and gives a reproducible witness.

**How do you know the harness is right?** Its tests compare against compiler behaviour that is easy to state and
easy to check: `200 * 200` into `S9(4) COMP` gives `-25536`, a size error keeps the prior value, display overflow
keeps the low-order digits, `125 / 2` rounded gives `63` and unrounded `62`. The `cobol_exact_agreement` metric is
the same check at scale.

**What would you do next?** Model data flow between statements, add IBM Enterprise COBOL as a second reference with
`TRUNC` variations, and turn the per-statement record into a regression check that a translator can be run against.

**What surprised you most?** Read it off the rendered table when asked rather than from memory. The `exact_no_size`
and `float_truncate` rows usually show that overflow, not rounding, is the larger source of disagreement.

## How I would present it in five minutes

1. One slide: `COMPUTE WS-BAL = WS-BAL - WS-AMT` and the five ways to write it in Python.
2. One slide: the pipeline, emphasising that the reference is the compiler.
3. The rendered results table.
4. The limits slide: GnuCOBOL only, one statement at a time, wide inputs, the open question about `TRUNC`.
5. The next step: data flow and a second compiler.
