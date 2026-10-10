"""Conservative Dart reference-assignment handling for native patch scanning.

Only bare identifier-to-identifier statements in code are exempt from the
generic environment-assignment heuristic. Literals/comments remain scanned.
"""
import re

from .discovery import scan_text, SECRET
from .ledger import LedgerError


REFERENCE = re.compile(r'(?m)^[ \t]*[A-Za-z_]\w*[ \t]*=[ \t]*([A-Za-z_]\w*)[ \t]*;[ \t]*(?=\r?$)')


def scan_dart(data):
    # Decode/null validation remains identical to discovery; masking never
    # changes the bytes installed or used to compute the candidate hash.
    try:
        return scan_text(data)
    except LedgerError as error:
        original_error = error
    try:
        value = data.decode('utf-8-sig')
    except UnicodeError:
        raise original_error
    if '\0' in value:
        raise original_error
    code = [True] * len(value)
    i = 0
    while i < len(value):
        start = i
        if value.startswith('//', i):
            end = value.find('\n', i)
            i = len(value) if end < 0 else end
        elif value.startswith('/*', i):
            depth = 1
            i += 2
            while i < len(value) and depth:
                if value.startswith('/*', i): depth += 1; i += 2
                elif value.startswith('*/', i): depth -= 1; i += 2
                else: i += 1
        elif value[i] in "\"'" or (value[i] == 'r' and i + 1 < len(value) and value[i + 1] in "\"'"):
            raw = value[i] == 'r'
            if raw: i += 1
            quote = value[i]
            delimiter = quote * 3 if value.startswith(quote * 3, i) else quote
            i += len(delimiter)
            while i < len(value):
                if value.startswith(delimiter, i): i += len(delimiter); break
                if not raw and value[i] == '\\': i = min(i + 2, len(value))
                else: i += 1
        else:
            i += 1
            continue
        code[start:i] = [False] * (i - start)
    scanned = list(value)
    for match in REFERENCE.finditer(value):
        if all(code[match.start():match.end()]) and not SECRET.search(match.group(1)):
            scanned[match.start():match.end()] = [' '] * (match.end() - match.start())
    scan_text(''.join(scanned).encode())
    return value
