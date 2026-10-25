"""W05 / T19: a milestone's test suite may not be weakened to reach a pass.

Compares the test files between the base tree (what the owner approved, or the last accepted artifact) and the tree a verdict runs on.
Per approved test (a `test*` function or method of a Python test file that the usual discovery finds — `test*.py` or `*_test(s).py`):
  * gone, renamed to a non-test name, or in a file that is no longer discoverable  -> WEAKENED (removed / undiscoverable);
  * its definition changed — body OR decorators (a `@skip` leaves the body intact)  -> WEAKENED (changed);
  * its class gained a skip/expectedFailure/xfail decorator                          -> WEAKENED (class_skipped);
  * anything else in the file changed (imports, helpers, fixtures, setUp, class bases, module code) while approved tests remain
    -> INSUFFICIENT (support_changed): the tests may now check less and this analysis cannot prove they do not; a file that does not
    parse, or a test file in another language, is INSUFFICIENT too (unparsed / unanalysed).
  * a changed Python file under a test path that is not itself discoverable (a shared helper, fixture module or conftest the approved
    tests import) -> INSUFFICIENT (support_changed), the same rule as changed support code inside a test file.
A new test function is accepted with provenance; a pure reformat (same AST) or a move inside the discovery pattern changes nothing.
Weakened is U1 (HD-04/HD-39); insufficient means "not established", never silently intact. Pure Git reads: nothing is written.

Limits (stated, not hidden): Python only, discovery by file/function name; dynamic test generation, `load_tests`, conftest/pytest.ini
and changes outside the test files (the code under test, environment) are outside this comparison — the receipt's argv/config binding and
the artifact identity cover those.
"""
import ast
import hashlib
import re

from ..ledger import LedgerError
from .verifiers import command

TEST_FILE = re.compile(r'(^|/)(tests?/[^/]*|test_[^/]*|[^/]*_tests?)(\.[A-Za-z0-9]+)?$')
DISCOVERABLE = re.compile(r'(^|/)(test[^/]*|[^/]*_tests?)\.py$')
SKIP_DECORATORS = ('skip', 'skipif', 'skipunless', 'expectedfailure', 'xfail')


def _is_test_path(path):
    return bool(TEST_FILE.search(path))


def _discoverable(path):
    return bool(DISCOVERABLE.search(path))


def _hash(node):
    return hashlib.sha256(ast.dump(node, annotate_fields=True, include_attributes=False).encode('utf-8')).hexdigest()[:16]


def _decorator_name(node):
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute): return target.attr
    if isinstance(target, ast.Name): return target.id
    return ''


def _skips(decorators):
    return [name for name in (_decorator_name(d) for d in decorators) if name.lower() in SKIP_DECORATORS]


def analyse(source):
    """{'tests': {qualname: hash of the whole definition incl. decorators}, 'classes': {name: {'skipped': bool}}, 'support': hash of
    everything else in the module (test definitions removed)} — None when the file does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    tests, classes = {}, {}
    def visit(node, prefix):
        for child in list(getattr(node, 'body', [])):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith('test'):
                tests[prefix + child.name] = _hash(child)
            elif isinstance(child, ast.ClassDef):
                classes[prefix + child.name] = {'skipped': bool(_skips(child.decorator_list))}
                visit(child, prefix + child.name + '.')
    visit(tree, '')
    class Stub(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name.startswith('test'):
                return None                      # tests are compared one by one; adding or removing one is not a change of the support code
            return self.generic_visit(node)
        visit_AsyncFunctionDef = visit_FunctionDef
    support = Stub().visit(tree)
    return {'tests': tests, 'classes': classes, 'support': _hash(support)}


def _blob(top, tree, path):
    try:
        return command._git(top, 'show', f'{tree}:{path}')
    except LedgerError:
        return None


def compare(directory, base_tree, current_tree):
    """{'base', 'current', 'files', 'weakened': [{'file','test','kind'}], 'added': [{'file','test'}], 'insufficient': [{'file','kind',...}],
    'unparsed': [...]} for the test files that differ between the two trees."""
    top = command.toplevel(directory)
    names = command._git(top, 'diff', '--name-status', '-z', base_tree, current_tree) if base_tree != current_tree else ''
    files, weakened, added, insufficient, unparsed = [], [], [], [], []
    parts = [p for p in names.split('\0') if p]
    pairs, i = [], 0
    while i < len(parts):
        status = parts[i]
        if status.startswith('R') or status.startswith('C'):
            pairs.append((status[0], parts[i + 1], parts[i + 2])); i += 3
        else:
            pairs.append((status[0], parts[i + 1], parts[i + 1])); i += 2
    for status, old_path, new_path in pairs:
        if not (_is_test_path(old_path) or _is_test_path(new_path)):
            continue
        files.append({'status': status, 'path': new_path, 'from': old_path})
        if not (old_path.endswith('.py') or new_path.endswith('.py')):
            insufficient.append({'file': new_path, 'kind': 'unanalysed', 'detail': 'a test file in another language changed; not analysed'})
            continue
        if not _discoverable(old_path) and not _discoverable(new_path):
            # W05: a shared helper/fixture/conftest under the test directory is support code of the approved tests that import it; its
            # change cannot be proven harmless here (same rule as a changed support hash inside a test file). A pure reformat is no change.
            old_tree = analyse(_blob(top, base_tree, old_path) or '') if status != 'A' else None
            new_tree = analyse(_blob(top, current_tree, new_path) or '') if status != 'D' else None
            if old_tree is not None and old_tree == new_tree: continue
            insufficient.append({'file': new_path, 'kind': 'support_changed',
                                 'detail': 'a helper module under the test directory changed; the tests that use it are not proven intact'})
            continue
        before = analyse(_blob(top, base_tree, old_path) or '') if status != 'A' and _discoverable(old_path) else {'tests': {}, 'classes': {}, 'support': None}
        after = analyse(_blob(top, current_tree, new_path) or '') if status != 'D' and _discoverable(new_path) else {'tests': {}, 'classes': {}, 'support': None}
        if before is None or after is None:
            unparsed.append(new_path)
            insufficient.append({'file': new_path, 'kind': 'unparsed', 'detail': 'the test file does not parse; nothing can be told about its tests'})
            continue
        if status != 'D' and _discoverable(old_path) and not _discoverable(new_path):
            for name in before['tests']:
                weakened.append({'file': new_path, 'test': name, 'kind': 'undiscoverable'})
            continue
        for name, digest in before['tests'].items():
            cls = name.rsplit('.', 1)[0] if '.' in name else None
            if name not in after['tests']:
                weakened.append({'file': new_path, 'test': name, 'kind': 'removed'})
            elif cls and after['classes'].get(cls, {}).get('skipped') and not before['classes'].get(cls, {}).get('skipped'):
                weakened.append({'file': new_path, 'test': name, 'kind': 'class_skipped'})
            elif after['tests'][name] != digest:
                weakened.append({'file': new_path, 'test': name, 'kind': 'changed'})
        for name in sorted(set(after['tests']) - set(before['tests'])):
            added.append({'file': new_path, 'test': name})
        if before['tests'] and before['support'] is not None and after['support'] is not None and before['support'] != after['support']:
            insufficient.append({'file': new_path, 'kind': 'support_changed',
                                 'detail': 'helpers, fixtures, imports or class definitions around the approved tests changed; the tests are not proven intact'})
    return {'base': base_tree, 'current': current_tree, 'files': files, 'weakened': weakened, 'added': added, 'insufficient': insufficient, 'unparsed': unparsed}
