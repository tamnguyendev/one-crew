"""W05 / T19: a milestone's test suite may not be weakened to reach a pass.

Compares the test files between the base tree (what the owner approved, or the last accepted artifact) and the tree a verdict runs on.
A test function that disappeared or whose body changed is a WEAKENING candidate (U1, HD-04/HD-39); a new test function is accepted with
provenance and never asks the owner. Judged per test function by its normalised AST, so moving code or renaming a helper is not a weakening
while loosening an assert is. Pure Git reads: nothing is written, no checkout.
"""
import ast
import hashlib
import re

from ..ledger import LedgerError
from .verifiers import command

TEST_FILE = re.compile(r'(^|/)(tests?/.*\.py|test_[^/]*\.py|[^/]*_tests?\.py)$')


def _functions(source):
    """{qualified test name: ast hash} for every test function/method of a module (def test_* at module level or inside a class)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    out = {}
    def visit(node, prefix):
        for child in getattr(node, 'body', []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith('test'):
                body = ast.Module(body=child.body, type_ignores=[])
                out[prefix + child.name] = hashlib.sha256(ast.dump(body, annotate_fields=True, include_attributes=False).encode('utf-8')).hexdigest()[:16]
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + '.')
    visit(tree, '')
    return out


def _blob(top, tree, path):
    try:
        return command._git(top, 'show', f'{tree}:{path}')
    except LedgerError:
        return None


def compare(directory, base_tree, current_tree):
    """{'base', 'current', 'files', 'weakened': [{'file','test','kind'}], 'added': [{'file','test'}], 'unparsed': [...]} for the test files that differ."""
    top = command.toplevel(directory)
    names = command._git(top, 'diff', '--name-status', '-z', base_tree, current_tree) if base_tree != current_tree else ''
    files, weakened, added, unparsed = [], [], [], []
    parts = [p for p in names.split('\0') if p]
    pairs, i = [], 0
    while i < len(parts):
        status = parts[i]
        if status.startswith('R') or status.startswith('C'):
            pairs.append((status[0], parts[i + 1], parts[i + 2])); i += 3
        else:
            pairs.append((status[0], parts[i + 1], parts[i + 1])); i += 2
    for status, old_path, new_path in pairs:
        if not (TEST_FILE.search(old_path) or TEST_FILE.search(new_path)):
            continue
        files.append({'status': status, 'path': new_path, 'from': old_path})
        before = _functions(_blob(top, base_tree, old_path) or '') if status != 'A' else {}
        after = _functions(_blob(top, current_tree, new_path) or '') if status != 'D' else {}
        if before is None or after is None:
            unparsed.append(new_path); continue
        for name, digest in before.items():
            if name not in after:
                weakened.append({'file': new_path, 'test': name, 'kind': 'removed'})
            elif after[name] != digest:
                weakened.append({'file': new_path, 'test': name, 'kind': 'changed'})
        for name in sorted(set(after) - set(before)):
            added.append({'file': new_path, 'test': name})
    return {'base': base_tree, 'current': current_tree, 'files': files, 'weakened': weakened, 'added': added, 'unparsed': unparsed}
