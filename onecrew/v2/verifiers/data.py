"""W39 data verifier: bounded CSV/JSON tables, schema, reconciliation, samples.

This adapter reads artifact files only. It neither transforms data nor decides
the plan's lifecycle. Reconciliation compares exact keys/values and Decimal sums.
"""
import csv
import hashlib
import io
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation

from ...ledger import LedgerError
from ...snapshots import scoped_path
from . import port

NAME = 'data'
TYPES = ('string', 'integer', 'number', 'boolean')
MAX_ROWS = 50_000


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise LedgerError(label + ': invalid object fields.')
    return value


def _names(value, columns, label, minimum=0):
    if (not isinstance(value, list) or not minimum <= len(value) <= len(columns) or
            any(not isinstance(v, str) or v not in columns for v in value) or len(set(value)) != len(value)):
        raise LedgerError(label + ': expected unique declared column names.')
    return list(value)


def validate_config(config, label):
    _object(config, ('path', 'format', 'columns', 'key', 'row_count', 'reconcile', 'samples'), label)
    path = scoped_path(config.get('path'))
    format_ = config.get('format', 'csv')
    if format_ not in ('csv', 'json'): raise LedgerError(label + '.format: csv or json.')
    columns = config.get('columns')
    if (not isinstance(columns, dict) or not 1 <= len(columns) <= 100 or
            any(not isinstance(k, str) or not k or len(k) > 100 or v not in TYPES for k, v in columns.items())):
        raise LedgerError(label + '.columns: 1-100 named string/integer/number/boolean columns.')
    key = _names(config.get('key', []), columns, label + '.key', 1)
    count = config.get('row_count')
    if count is not None and (type(count) is not int or not 0 <= count <= MAX_ROWS):
        raise LedgerError(label + '.row_count: integer within the row cap.')
    reconcile = config.get('reconcile')
    if reconcile is not None:
        _object(reconcile, ('path', 'format', 'compare', 'totals'), label + '.reconcile')
        source = scoped_path(reconcile.get('path'))
        if source == path: raise LedgerError(label + ': reconciliation source must differ from output.')
        source_format = reconcile.get('format', format_)
        if source_format not in ('csv', 'json'): raise LedgerError(label + '.reconcile.format: csv or json.')
        compare = _names(reconcile.get('compare', []), columns, label + '.reconcile.compare')
        totals = _names(reconcile.get('totals', []), columns, label + '.reconcile.totals')
        if any(columns[c] not in ('integer', 'number') for c in totals):
            raise LedgerError(label + ': totals require numeric columns.')
        reconcile = {'path': source, 'format': source_format, 'compare': compare, 'totals': totals}
    samples = config.get('samples', [])
    if not isinstance(samples, list) or len(samples) > 100: raise LedgerError(label + '.samples: at most 100 rows.')
    for sample in samples:
        _object(sample, ('key', 'values'), label + '.samples')
        if not isinstance(sample.get('key'), dict) or set(sample['key']) != set(key):
            raise LedgerError(label + ': sample must identify every key column.')
        if not isinstance(sample.get('values'), dict) or not sample['values'] or not set(sample['values']) <= set(columns):
            raise LedgerError(label + ': sample values must name declared columns.')
        for c, v in {**sample['key'], **sample['values']}.items():
            _value(v, columns[c], False)
    return {'path': path, 'format': format_, 'columns': dict(columns), 'key': key,
            'row_count': count, 'reconcile': reconcile, 'samples': samples}


def json_value(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise LedgerError('JSON has duplicate object keys.')
            result[key] = value
        return result
    def constant(value):
        raise LedgerError('JSON nonfinite number: ' + value)
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except ValueError as error:
        raise LedgerError('Invalid JSON: ' + str(error)[:120]) from error


def _value(value, kind, csv_value):
    if kind == 'string':
        if not isinstance(value, str): raise LedgerError('expected string')
        return value
    if kind == 'boolean':
        if csv_value and value in ('true', 'false'): return value == 'true'
        if type(value) is bool: return value
        raise LedgerError('expected boolean (CSV: true or false)')
    if kind == 'integer':
        if csv_value and isinstance(value, str) and re.fullmatch(r'-?(0|[1-9][0-9]*)', value): return int(value)
        if type(value) is int: return value
        raise LedgerError('expected integer')
    if type(value) not in (str, int, float) or (isinstance(value, str) and not csv_value):
        raise LedgerError('expected number')
    try:
        number = Decimal(str(value))
        if not number.is_finite(): raise InvalidOperation
        return number
    except InvalidOperation as error:
        raise LedgerError('expected finite number') from error


def _table(box, path, format_, columns, key):
    text = box.read_text(path)
    if format_ == 'csv':
        reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')), strict=True)
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise LedgerError(path + ': missing/duplicate CSV column names.')
        if set(reader.fieldnames) != set(columns): raise LedgerError(path + ': CSV schema differs.')
        rows = []
        try:
            for row in reader:
                if len(rows) >= MAX_ROWS: raise port.Inconclusive('Data row cap exceeded.')
                rows.append(row)
        except csv.Error as error:
            raise LedgerError(path + ': malformed CSV.') from error
    else:
        rows = json_value(text)
        if not isinstance(rows, list): raise LedgerError(path + ': JSON must contain a record array.')
        if len(rows) > MAX_ROWS: raise port.Inconclusive('Data row cap exceeded.')
    indexed = {}
    for number, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != set(columns): raise LedgerError(f'{path}:{number}: row schema differs.')
        try:
            normalized = {c: _value(row[c], kind, format_ == 'csv') for c, kind in columns.items()}
        except LedgerError as error:
            raise LedgerError(f'{path}:{number}: {error}') from error
        identity = tuple(normalized[k] for k in key)
        if identity in indexed: raise LedgerError(f'{path}:{number}: duplicate key.')
        indexed[identity] = normalized
    return indexed


def report(checks):
    return {'checks': checks, 'findings': [
        {'id': 'F-' + hashlib.sha256((c['id'] + p).encode()).hexdigest()[:12], 'text': p, 'status': 'open'}
        for c in checks for p in c['problems']], 'unverified': []}


def run(config, box):
    checks = []
    def add(name, count, problems):
        checks.append({'id': name, 'checked': count, 'ok': not problems, 'problems': problems})
    try:
        rows = _table(box, config['path'], config['format'], config['columns'], config['key'])
    except (LedgerError, FileNotFoundError, UnicodeDecodeError) as error:
        add('schema', 0, [str(error)])
        return report(checks)
    add('schema', len(rows), [])
    count = config['row_count']
    if count is not None:
        add('row_count', len(rows), [] if len(rows) == count else [f'Expected {count} rows; observed {len(rows)}.'])
    reconciliation = config['reconcile']
    if reconciliation:
        problems = []
        try:
            source = _table(box, reconciliation['path'], reconciliation['format'], config['columns'], config['key'])
            if set(rows) != set(source): problems.append('Reconciliation keys differ: missing or extra output rows.')
            for key in set(rows) & set(source):
                for column in reconciliation['compare']:
                    if rows[key][column] != source[key][column]: problems.append(f'Reconciliation differs at key {key}, column {column}.')
            for column in reconciliation['totals']:
                if sum(r[column] for r in rows.values()) != sum(r[column] for r in source.values()):
                    problems.append(f'Reconciliation total differs for {column}.')
        except (LedgerError, FileNotFoundError, UnicodeDecodeError) as error:
            problems.append(str(error))
        add('reconcile', len(rows), problems)
    if config['samples']:
        problems = []
        for sample in config['samples']:
            key = tuple(_value(sample['key'][k], config['columns'][k], False) for k in config['key'])
            if key not in rows:
                problems.append(f'Sample key {key} is absent.')
            else:
                for column, value in sample['values'].items():
                    if rows[key][column] != _value(value, config['columns'][column], False):
                        problems.append(f'Sample key {key}, column {column} differs.')
        add('samples', len(config['samples']), problems)
    return report(checks)


port.register(sys.modules[__name__])
