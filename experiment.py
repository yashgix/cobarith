'''Run harnessed CardDemo arithmetic statements through GnuCOBOL and write metrics.'''

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path

from cobarith import DATA_DIR
from cobarith.cases import boundary_cases, random_cases
from cobarith.harness import run
from cobarith.inventory import Inventory, inventory
from cobarith.stmt import Statement
from cobarith.translate import TRANSLATIONS, translate

COMPARED = tuple(name for name in TRANSLATIONS if name != 'cobol_exact')
VERBS = ('ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE', 'COMPUTE')
FLAGS = ('scale', 'float', 'size', 'sign')


def _slug(text: str) -> str:
    return re.sub(r'[\s-]+', '_', text.strip().lower())


def _prepare_cases(stmt: Statement) -> tuple[list[tuple[int, ...]], list[tuple[int, ...]]]:
    random = [tuple(case) for case in random_cases(stmt)]
    seen = set(random)
    boundary: list[tuple[int, ...]] = []
    for _kind, _target, case in boundary_cases(stmt):
        key = tuple(case)
        if key in seen:
            continue
        seen.add(key)
        boundary.append(key)
    return random, boundary


def _statement_record(stmt: Statement) -> dict:
    record = {
        'id': stmt.id,
        'program': stmt.program,
        'file': stmt.file,
        'line': stmt.line,
        'verb': stmt.verb,
        'status': stmt.status,
        'reason': stmt.reason,
    }
    if stmt.status != 'harnessed':
        return record

    random, boundary = _prepare_cases(stmt)
    cases = random + boundary
    results = run(stmt, cases) if cases else []
    per = {
        name: {
            'cases_differ_random': 0,
            'cases_differ_boundary': 0,
            'cases_differ_storage': 0,
            'cases_differ_arithmetic': 0,
            'example': None,
        }
        for name in COMPARED
    }
    exact_differ = 0

    for index, case in enumerate(cases):
        cobol = tuple(results[index][0])
        translated = translate(stmt, case)
        if tuple(translated['cobol_exact']) != cobol:
            exact_differ += 1
        storage = translated['cobol_exact'] != translated['exact_no_size']
        for name in COMPARED:
            values = tuple(translated[name])
            if values == cobol:
                continue
            info = per[name]
            if index < len(random):
                info['cases_differ_random'] += 1
            else:
                info['cases_differ_boundary'] += 1
            if storage:
                info['cases_differ_storage'] += 1
            else:
                info['cases_differ_arithmetic'] += 1
            if info['example'] is None:
                info['example'] = {
                    'inputs': list(case),
                    'cobol': list(cobol),
                    'translation': list(values),
                }

    record.update(
        {
            'flags': {flag: bool((stmt.flags or {}).get(flag)) for flag in FLAGS},
            'variables': [
                [variable.name, variable.pic.text if variable.pic else None, variable.usage]
                for variable in stmt.variables
            ],
            'targets': list(stmt.targets),
            'cases_random': len(random),
            'cases_boundary': len(boundary),
            'cobol_exact_cases_differ': exact_differ,
        }
    )
    record.update(per)
    return record


def _metrics(inv: Inventory, records: Sequence[dict]) -> dict:
    metrics = {
        'programs_total': len(inv.programs),
        'copybooks_missing': len(inv.missing_copybooks),
        'statements_total': len(records),
        'statements_harnessed': 0,
        'statements_unsupported': 0,
        'statements_decimal_risk': 0,
        'cases_random': 0,
        'cases_boundary': 0,
        'cobol_exact_cases_differ': 0,
        'cobol_exact_agreement': 1.0,
    }
    for verb in VERBS:
        metrics[f'statements_{verb.lower()}'] = 0
    for flag in FLAGS:
        metrics[f'statements_flag_{flag}'] = 0
    for name in COMPARED:
        metrics[f'{name}_statements_differ'] = 0
        metrics[f'{name}_statements_differ_arithmetic'] = 0
        for kind in ('random', 'boundary', 'arithmetic', 'storage'):
            metrics[f'{name}_cases_differ_{kind}'] = 0

    for record in records:
        verb = str(record['verb']).lower()
        verb_key = f'statements_{verb}'
        metrics[verb_key] = metrics.get(verb_key, 0) + 1
        if record['status'] != 'harnessed':
            metrics['statements_unsupported'] += 1
            reason = record.get('reason') or 'unknown'
            reason_key = f'unsupported_{_slug(str(reason))}'
            metrics[reason_key] = metrics.get(reason_key, 0) + 1
            continue

        metrics['statements_harnessed'] += 1
        flags = record['flags']
        if flags.get('scale') or flags.get('float'):
            metrics['statements_decimal_risk'] += 1
        for flag in FLAGS:
            if flags.get(flag):
                metrics[f'statements_flag_{flag}'] += 1

        metrics['cases_random'] += record['cases_random']
        metrics['cases_boundary'] += record['cases_boundary']
        metrics['cobol_exact_cases_differ'] += record['cobol_exact_cases_differ']

        for name in COMPARED:
            info = record[name]
            if info['cases_differ_random'] + info['cases_differ_boundary']:
                metrics[f'{name}_statements_differ'] += 1
            if info['cases_differ_arithmetic']:
                metrics[f'{name}_statements_differ_arithmetic'] += 1
            for kind in ('random', 'boundary', 'arithmetic', 'storage'):
                metrics[f'{name}_cases_differ_{kind}'] += info[f'cases_differ_{kind}']

    total_cases = metrics['cases_random'] + metrics['cases_boundary']
    if total_cases:
        metrics['cobol_exact_agreement'] = round(
            1.0 - metrics['cobol_exact_cases_differ'] / total_cases, 6
        )
    return metrics


def experiment(root: str | Path = DATA_DIR) -> tuple[dict, list[dict]]:
    inv = inventory(root)
    records = [_statement_record(stmt) for stmt in inv.statements]
    return _metrics(inv, records), records


def write_outputs(out: str | Path, metrics: dict, records: Sequence[dict]) -> None:
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(metrics, indent=2, sort_keys=True) + '\n')
    statements_path = out_path.with_name('statements.jsonl')
    with statements_path.open('w', encoding='utf-8', newline='\n') as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n')


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--root', default=DATA_DIR, type=Path)
    args = parser.parse_args(argv)
    metrics, records = experiment(args.root)
    write_outputs(args.out, metrics, records)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
