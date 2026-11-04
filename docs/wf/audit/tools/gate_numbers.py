# Honest counts for a development snapshot gate (review a2476ab P2): checks, suite runs (receipts), test executions summed over receipts (a module
# registered under several releases runs once per release), and the DISTINCT test ids of the registered modules (counted by id with the unittest
# loader, without running). Also splits the decision: implementation checks vs acceptance rows.
#   python docs/wf/audit/tools/gate_numbers.py <snapshot-gate out dir>
import glob, json, os, sys, unittest
from pathlib import Path

R = Path(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..')))


def test_ids(module):
    sys.path.insert(0, str(R)); sys.path.insert(0, str(R / 'tests'))
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    ids = []
    def walk(s):
        for t in s:
            if isinstance(t, unittest.TestSuite): walk(t)
            else: ids.append(t.id())
    walk(suite)
    return ids


def main():
    out = Path(sys.argv[1])
    decision = json.load(open(out / 'decision.json', encoding='utf-8'))
    receipts = [json.load(open(f, encoding='utf-8')) for f in glob.glob(str(out / 'gate' / 'receipts' / '*.json'))]
    cfg = json.load(open(R / 'wfkit' / 'development-testcases.json', encoding='utf-8'))
    modules = sorted({m for rel in cfg['releases'].values() for k, c in rel['testcases'].items() for m in c.get('modules', [])})
    distinct = {}
    for m in modules:
        try: distinct[m] = len(set(test_ids(m)))
        except Exception as error:  # noqa: BLE001
            distinct[m] = f'unloadable: {type(error).__name__}'
    kinds = {}
    for p in decision.get('problems', []): kinds[p['kind']] = kinds.get(p['kind'], 0) + 1
    summary = {'commit': decision.get('commit'), 'wheel_sha256': decision.get('wheel_sha256'), 'decision': decision.get('decision'),
               'implementation_checks': decision.get('implementation_checks'), 'problem_kinds': kinds,
               'suite_runs (receipts)': len(receipts),
               'test_executions_summed_over_receipts': sum(int(r.get('tests_run') or 0) for r in receipts),
               'passed_summed': sum(int(r.get('tests_passed') or 0) for r in receipts), 'skipped_summed': sum(int(r.get('tests_skipped') or 0) for r in receipts),
               'registered_modules': len(modules), 'distinct_test_ids': sum(v for v in distinct.values() if isinstance(v, int)),
               'unloadable_modules': {m: v for m, v in distinct.items() if not isinstance(v, int)},
               'note': 'test_executions counts a module once per release that registers it; distinct_test_ids counts each test id once (loader, not run).'}
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
