"""W46b evidence for T49c E21, E22 and E13 (the S2 state root of tests.test_wf_namespace_compat, real archived old binary d3120c6).

No product code is touched; every cell is the prediction of the real `compat_scan.scan` compared with what the real old CLI does on a
disposable copy of S2, run from the root's own project, with the hash of `plans/` taken before and after.
"""
import hashlib
import json
from unittest.mock import patch

from onecrew.v2 import compat_scan
import tests.test_wf_namespace_compat as base


def plans_hash(state):
    digest = hashlib.sha256()
    for path in sorted((state / 'plans').rglob('*')):
        if path.is_file() and path.name != 'active-plan.json':
            digest.update(str(path.relative_to(state)).replace('\\', '/').encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def report_violations(report, old_says_unreadable, old_reads_other=()):
    """The T49c report check (E9/E13): a root the old binary cannot see must not be called readable, continuable or lost; and a cell
    where the old binary shows ANOTHER root under the requested name must carry the reads_other_root label (never refused/readable)."""
    bad = []
    for anchor, project_id, command in old_reads_other:
        root = next((r for r in report['roots'] if (r['anchor'], r['project_id']) == (anchor, project_id)), None)
        cell = root['commands'].get(command, '') if root else ''
        if not cell.startswith(compat_scan.READS_OTHER_ROOT):
            bad.append(f'{anchor} {command}: old binary reads another root, scan says {cell!r}')
        elif not any(r['command'] == command and r['label'] == compat_scan.READS_OTHER_ROOT and not r['blocking']
                     for r in root.get('command_risks', [])):
            bad.append(f'{anchor} {command}: reads_other_root not recorded as a (non-blocking) warning risk')
        elif not any(w['anchor'] == anchor and w['project_id'] == project_id and w['command'] == command for w in report.get('warnings', [])):
            bad.append(f'{anchor} {command}: reads_other_root not surfaced in the report warnings')
    for root in report['roots']:
        key = (root['anchor'], root['project_id'])
        if key in old_says_unreadable:
            if root['properties']['old_readable'] or root['properties']['old_continuable']:
                bad.append(f'{root["anchor"]}: labelled readable by the old binary, which answers No plan named')
            if not root['preserved_only']:
                bad.append(f'{root["anchor"]}: not labelled preserved-only')
            if 'lost' in json.dumps(root).lower() or root['status'] == 'lost':
                bad.append(f'{root["anchor"]}: labelled lost although its data is intact')
    return bad


class T49cEvidence(base.NamespaceCompatTests):
    for _name in [n for n in dir(base.NamespaceCompatTests) if n.startswith('test_')]:
        locals()[_name] = None
    del _name

    def ask_old(self, label, command):
        """Run one old command for root `label` on a fresh copy of S2; return (exit, output, plans hash before, after, state)."""
        index, name = {'R2': (1, 'r2'), 'R3': (0, 'r3'), 'DUPb': (1, 'dup'), 'DUPk': (2, 'dup'), 'DUPa': (0, 'dup')}[label]
        state = self.copy()
        before = plans_hash(state)
        if command == 'plan show':
            args = ['plan', 'show', name]
        elif command == 'plan digest':
            args = ['plan', 'digest']
        elif command == 'plan report':
            args = ['plan', 'report', name]
        elif command == 'plan amend':
            args = ['plan', 'amend', name, '--file', str(self.runs / 'r1.json'), '--reason', 'fixture', '--author', 'codex-fixture']
        elif command == 'verdict run':
            args = ['verdict', 'run', '--plan', name, '--milestone', 'M1']
        else:
            args = ['plan', 'propose', name, '--file', str(self.runs / 'r1.json'), '--author', 'codex-fixture']
        code, out = self.old.run(self.projects[index], state, *args)
        return code, out, before, plans_hash(state), state

    def test_t49c_e21_one_row_per_s2_root_with_the_expected_properties(self):
        """W46b / T49c E21: S2 yields one row per root: R2 preserved-only + B1; R3 preserved-only, no block; DUPa readable and
        continuable; DUPb preserved-only, 'same name, not blocking'; DUPk branches into another project's directory, B3."""
        report = compat_scan.scan(self.copy())
        self.assertEqual(len(report['roots']), 7)
        rows = {label: self.root(report, label) for label in ('R2', 'R3', 'DUPa', 'DUPb', 'DUPk')}
        self.assertTrue(rows['R2']['preserved_only'])
        self.assertEqual([b['id'] for b in rows['R2']['blocks']], ['B1'])
        self.assertTrue(rows['R3']['preserved_only'])
        self.assertEqual(rows['R3']['blocks'], [])
        self.assertTrue(rows['DUPa']['properties']['old_readable'] and rows['DUPa']['properties']['old_continuable'])
        self.assertEqual(rows['DUPa']['blocks'], [])
        self.assertTrue(rows['DUPb']['preserved_only'])
        self.assertEqual(rows['DUPb']['blocks'], [])
        self.assertIn('same name', rows['DUPb']['duplicate_note'])
        self.assertIn('not', rows['DUPb']['duplicate_note'])
        self.assertTrue(rows['DUPb']['duplicates'])
        self.assertEqual([b['id'] for b in rows['DUPk']['blocks']], ['B3'])
        self.assertEqual(rows['DUPk']['blocks'][0]['type'], 'continue')
        self.assertFalse(rows['DUPk']['properties']['old_continuable'])
        self.assertIn('B3', rows['DUPk']['commands']['plan amend'])
        self.assertIn('cross-project', rows['DUPk']['duplicate_note'])

    def check_cell(self, label, command, predicted=None):
        """The scan's prediction for (root, command) against the real old binary: exit class, message, and plans/ effect.
        `predicted` overrides the scan's cell (a counter-example)."""
        row = self.root(compat_scan.scan(self.copy()), label)
        predicted = row['commands'][command] if predicted is None else predicted
        code, out, before, after, state = self.ask_old(label, command)
        text = f'{label} {command}: predicted {predicted!r}, old exit {code}: {out[:200]}'
        if predicted.startswith(compat_scan.READS_OTHER_ROOT):
            # The old binary answers about the OTHER root the scan names (its project), neither refused nor about this root.
            risk = next(r for r in row.get('command_risks', []) if r['command'] == command)
            self.assertFalse(risk['blocking'], text)                 # round 6: a warning, not a B1-B4 blocker
            self.assertEqual(code == 0, predicted.split(': ', 1)[1].startswith('exit 0'), text)
            self.assertIn(str(risk['reads']['project_path']).lower(), out.lower(), text)
            self.assertNotIn(str(self.projects[1 if label in ('R2', 'DUPb') else 0]).lower(), out.lower(), text)
            self.assertNotIn('No plan named', out, text)
            self.assertEqual(before, after, 'plans/ changed: ' + text)
            return predicted, code, before, after, state
        if predicted.startswith('refused'):
            self.assertNotEqual(code, 0, text)
        elif predicted.startswith('exit 0'):
            self.assertEqual(code, 0, text)
        else:
            self.fail('unrecognised prediction ' + text)
        if 'No plan named' in predicted:
            self.assertIn('No plan named', out, text)
        if 'writes nothing' in predicted or predicted.startswith('refused'):
            self.assertEqual(before, after, 'plans/ changed: ' + text)
        return predicted, code, before, after, state

    def test_t49c_e22_every_cell_of_the_plan_ns_columns_matches_the_old_binary(self):
        """W46b / T49c E22: for R3 (P1), DUPb (P2) and R2 (P2) every old command row (show, digest, report, amend, verdict run, propose)
        behaves as the scan predicted: exit class, message and the hash of plans/. Propose of r2 from P2 creates a new plan:r2 root."""
        for label in ('R3', 'DUPb', 'R2'):
            for command in ('plan show', 'plan digest', 'plan report', 'plan amend', 'verdict run', 'plan propose <same name>'):
                with self.subTest(root=label, command=command):
                    predicted, code, before, after, state = self.check_cell(label, command)
                    if command == 'plan propose <same name>' and predicted.startswith('exit 0'):
                        self.assertNotEqual(before, after)
                        self.assertIn('creates a separate', predicted)
                        name = 'r2' if label == 'R2' else 'r3'
                        self.assertTrue((state / 'plans' / name / 'v1.json').is_file())
                        self.assertTrue(self.root(compat_scan.scan(state), label)['preserved_only'])

    def test_t49c_e22_dupb_report_reads_dupk_and_a_refused_prediction_goes_red(self):
        """W46b / T49c E22: the old `plan report dup` from P2 does not refuse: it exits 0 with the partial report of DUPk (P3's legacy
        plan:dup). The scan labels the cell reads_other_root (a non-blocking warning, reads P3's plan:dup); a scan that predicts 'refused, No plan
        named' (the d3120c6-blind prediction) or a plain 'exit 0' readable cell for it is caught."""
        row = self.root(compat_scan.scan(self.copy()), 'DUPb')
        cell = row['commands']['plan report']
        self.assertTrue(cell.startswith('reads_other_root'), cell)
        self.assertNotIn('refused', cell)
        self.assertNotIn('lost', cell.lower())
        self.assertEqual([(r['label'], r['blocking'], r['reads']['anchor'], r['reads']['project_id']) for r in row['command_risks']],
                         [('reads_other_root', False, 'plan:dup', self.pids[2])])
        self.assertEqual(row['blocks'], [])                       # E21 unchanged: not a B3 write hazard
        self.check_cell('DUPb', 'plan report')
        with self.assertRaises(AssertionError):           # counter-example: the old scan's refusal is red against the old binary
            self.check_cell('DUPb', 'plan report', predicted='refused, No plan named; writes nothing')
        other = self.reads_other()
        for wrong in ('refused, No plan named; writes nothing', 'exit 0'):       # ...and a refused or readable label fails the report check
            with self.subTest(wrong=wrong):
                self.assertTrue(report_violations(self.patched_report('DUPb', 'plan report', wrong), set(), other))
        self.assertEqual(report_violations(compat_scan.scan(self.copy()), set(), other), [])

    def reads_other(self):
        """Cells where the real old binary shows another project's root: `plan report dup` from P2 (DUPb) and from P1 (DUPa, legacy)
        both print P3's report (DUPk, the last plan:dup of the state root)."""
        found = set()
        for label, index, anchor in (('DUPb', 1, 'plan-ns:dup'), ('DUPa', 0, 'plan:dup')):
            code, out, before, after, state = self.ask_old(label, 'plan report')
            self.assertEqual(code, 0, out)
            self.assertIn(str(self.projects[2]).lower(), out.lower())
            self.assertEqual(before, after)
            found.add((anchor, self.pids[index], 'plan report'))
        return found

    def test_round6_dupa_legacy_report_reads_dupk_and_is_a_warning_not_a_blocker(self):
        """T49c round 6 (decided 25/10 under delegated authority; source: 00 §6.1 / 05 T49 two block types, B1-B4; T49c [E21] "DUPb ...
        tên trùng, không chặn"; T49d N5/N6 succeed): the real old `plan report dup` from P1 shows DUPk (P3) — the scan predicts
        reads_other_root for the legacy DUPa cell as well; DUPa stays readable/continuable for show/amend/verdict (E21); the misreads are
        warnings in the report and the CLI table, and blocking.total stays the B1+B2+B3 of S2 (= 3)."""
        report = compat_scan.scan(self.copy())
        row = self.root(report, 'DUPa')
        self.assertTrue(row['commands']['plan report'].startswith(compat_scan.READS_OTHER_ROOT), row['commands']['plan report'])
        self.assertTrue(row['properties']['old_readable'] and row['properties']['old_continuable'])
        self.assertEqual(row['blocks'], [])
        self.assertEqual([(r['label'], r['blocking'], r['reads']['anchor'], r['reads']['project_id']) for r in row['command_risks']],
                         [('reads_other_root', False, 'plan:dup', self.pids[2])])
        self.check_cell('DUPa', 'plan report')                                    # real old binary
        for other in ('plan show', 'plan amend', 'verdict run'):                  # the cells of DUPa that resolve inside P1 are unchanged
            self.assertFalse(row['commands'][other].startswith(compat_scan.READS_OTHER_ROOT))
        self.assertEqual(report['blocking']['total'], 3)
        self.assertEqual(sorted(b['id'] for r in report['roots'] for b in r['blocks']), ['B1', 'B2', 'B3'])
        self.assertEqual(sorted((w['anchor'], w['project_id']) for w in report['warnings']),
                         sorted([('plan-ns:dup', self.pids[1]), ('plan:dup', self.pids[0])]))
        self.assertTrue(self.root(report, 'DUPk')['commands']['plan report'].startswith('exit 0'))   # DUPk is what the lookup renders
        # counter-example: the earlier plain 'exit 0' (readable) cell for DUPa fails the report check against the real old binary
        self.assertTrue(report_violations(self.patched_report('DUPa', 'plan report', 'exit 0'), set(), self.reads_other()))
        import contextlib, io
        from onecrew.v2 import compat_cli
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(compat_cli.main(['--state-root', str(self.copy()), 'compat', 'scan']), 0)
        table = out.getvalue()
        self.assertIn('blocking conditions: 3', table)
        self.assertIn('warnings (not blocking): 2', table)
        self.assertEqual(table.count('WARNING reads_other_root: '), 4, table)       # 2 summary lines + 2 per-root lines

    def patched_report(self, label, command, value):
        report = json.loads(json.dumps(compat_scan.scan(self.copy())))
        self.root(report, label)['commands'][command] = value
        return report

    def test_t49c_e22_propose_dup_from_p2_is_refused_because_p1_owns_the_directory(self):
        """W46b / T49c E22: `propose dup` from P2 is refused (plans/dup/ belongs to P1) and writes nothing, while `propose r2` from P2 succeeds."""
        predicted, code, before, after, state = self.check_cell('DUPb', 'plan propose <same name>')
        self.assertIn('already exists', predicted)
        self.assertEqual(before, after)
        predicted, code, before, after, state = self.check_cell('R2', 'plan propose <same name>')
        self.assertEqual(code, 0)
        self.assertNotEqual(before, after)

    def test_t49c_e22_dupk_cells_match_and_amend_writes_into_the_global_directory(self):
        """W46b / T49c E22: DUPk from P3 - show refused (hash mismatch), digest lists with ?/?, amend exits 0 and writes
        plans/dup/v2.json (the B3 branch) exactly as the scan predicted."""
        for command in ('plan show', 'plan digest', 'plan report', 'verdict run', 'plan propose <same name>'):
            with self.subTest(command=command):
                self.check_cell('DUPk', command)
        predicted, code, before, after, state = self.check_cell('DUPk', 'plan amend')
        self.assertIn('B3', predicted)
        self.assertNotEqual(before, after)
        self.assertTrue((state / 'plans' / 'dup' / 'v2.json').is_file())
        self.assertFalse((state / 'plans' / self.pids[2] / 'dup' / 'v2.json').exists())

    def unreadable_by_old(self):
        """Roots the real old binary cannot see: its own `plan show` answers No plan named from their project."""
        found = set()
        state = self.copy()
        for index, name in ((1, 'r2'), (0, 'r3')):
            code, out = self.old.run(self.projects[index], state, 'plan', 'show', name)
            self.assertNotEqual(code, 0)
            self.assertIn('No plan named', out)
            found.add(('plan-ns:' + name, self.pids[index]))
        return found, state

    def test_t49c_e13_report_check_passes_the_real_scan_and_catches_readable_or_lost_labels(self):
        """W46b / T49c E13: the check accepts the real scan (R2, R3 preserved-only, not readable, not lost) and goes red when a report
        labels R2 readable, continuable or lost; and when the scan itself treats every anchor in the ledger as readable."""
        unreadable, state = self.unreadable_by_old()
        other = self.reads_other()
        report = compat_scan.scan(state)
        self.assertEqual(report_violations(report, unreadable, other), [])
        for wrong in ('refused, No plan named; writes nothing', 'exit 0'):
            mutated = json.loads(json.dumps(report))
            self.root(mutated, 'DUPb')['commands']['plan report'] = wrong
            self.assertTrue(report_violations(mutated, unreadable, other), f'DUPb report {wrong!r} not caught')
        for variant in (1, 2, 3):
            mutated = json.loads(json.dumps(report))
            row = self.root(mutated, 'R2')
            if variant == 1:
                row['properties']['old_readable'] = True
            if variant == 2:
                row['properties']['old_continuable'] = True
            if variant == 3:
                row['status'] = 'lost'
            self.assertTrue(report_violations(mutated, unreadable), f'mutation {variant} not caught')
        real = compat_scan.scan_root

        def everything_readable(*args, **kwargs):
            row = real(*args, **kwargs)
            row['properties'] = {'unchanged': True, 'old_readable': True, 'old_continuable': True}
            row['preserved_only'] = False
            return row
        with patch.object(compat_scan, 'scan_root', everything_readable):
            violations = report_violations(compat_scan.scan(state), unreadable)
        self.assertEqual(len([v for v in violations if 'labelled readable' in v]), 2)
        self.assertTrue(any('plan-ns:r2' in v for v in violations))
        self.assertTrue(any('plan-ns:r3' in v for v in violations))
