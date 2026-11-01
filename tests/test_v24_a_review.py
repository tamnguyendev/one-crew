"""2.4-A, the independent review of 5c34f4a..26a86e7 (D:/OneCrewRuns/v24/review-a/review-a.md): its probes as tests, written before the fixes.

A-R01 legal git names never vanish (typed withheld rows, honest coverage; a malformed default-grant entry is reported) · A-R02 max_rounds
is a hard cap for report and write nodes (held `rounds_exhausted`) · A-R03 a declared read grant binds node `read` too · A-R04 the round
count and the repeat memory hold across chains (a re-pin is recorded) · A-R05 the effective request is the repeat identity · A-R06 cut
lines are marked, every match of a long file is reachable · A-R07 execution refusals and undelivered results are in the receipt; unreadable
chain evidence refuses the round · A-R08 a write node's final answer writes a file · A-R09 the declaration is bounded · A-R10 no timing in
the node identity · A-R11 a case-different path gets a hint · plus the missing counterexamples (absolute/drive/glob request paths, the
default grant end to end, two concurrent continuations).
"""
import json
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

from onecrew.common_executor import NativeExecutor
from onecrew.ledger import LedgerError
from tests.test_v24_a_sources import GRANT, SourceFixture, ask, body_of, done, st


class TreeFixture(SourceFixture):
    light = True

    def tree(self, extra):
        """A tree id: HEAD plus `extra` {path: bytes}, written with git plumbing (any legal git name, no file system involved)."""
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(self.temp.name) / 'probe.index'))
        def git(*args, data=None):
            return subprocess.run(['git', '-c', 'core.protectNTFS=false', '-C', str(self.root), *args], check=True, capture_output=True, env=env, input=data).stdout.decode().strip()
        git('read-tree', 'HEAD')
        for path, data in extra.items():
            git('update-index', '--add', '--cacheinfo', f'100644,{git("hash-object", "-w", "--stdin", data=data)},{path}')
        return git('write-tree')


class NameTests(TreeFixture):
    def test_a_r01_legal_git_names_are_found_or_withheld_never_silently_missing(self):
        deep = 'src/lib/' + 'd' * 290 + '/deep.txt'                              # longer than the 240 of a scope path: read like any other
        huge = 'src/' + ('e' * 200 + '/') * 5 + 'huge.txt'                          # longer than a request may name: withheld, too_long
        tree = self.tree({'src/[id]/page.tsx': b'NEEDLE-ODD in a route\n', deep: b'NEEDLE-ODD deep\n', 'src/backup~1.txt': b'NEEDLE-ODD backup\n',
                          'src/a*b?.txt': b'NEEDLE-ODD glob name\n', huge: b'NEEDLE-ODD huge\n'})
        reader, scope = st().Reader(self.root, tree), st().Scope(GRANT, ['src/'])
        search = st().run(reader, scope, {'op': 'search', 'query': 'needle-odd', 'path': 'src'})['result']
        self.assertEqual(sorted(m['path'] for m in search['matches']), sorted(['src/[id]/page.tsx', 'src/a*b?.txt', deep]))
        self.assertIn('NEEDLE-ODD deep', st().run(reader, scope, {'op': 'read', 'path': deep})['result']['text'])
        reasons = {w['reason'] for w in search['withheld']}
        self.assertTrue({'too_long', 'control_name_alias'} <= reasons, search['withheld'])
        self.assertIn('not every file searched', search['conclusion'])
        listed = st().run(reader, scope, {'op': 'list', 'path': 'src'})['result']
        self.assertIn('src/[id]/page.tsx', [e['path'] for e in listed['entries']])
        self.assertIn('withheld', listed['coverage']['stop_reason'])
        read = st().run(reader, scope, {'op': 'read', 'path': 'src/[id]/page.tsx'})['result']
        self.assertIn('NEEDLE-ODD', read['text'])
        alias = st().run(reader, scope, {'op': 'read', 'path': 'src/backup~1.txt'})['result']
        self.assertEqual(alias['withheld'], [{'path': 'src/backup~1.txt', 'reason': 'control_name_alias'}])     # the same answer as list/search
        literal = st().run(reader, scope, {'op': 'read', 'path': 'src/*.py'})['result']
        self.assertIn('not found', literal['refused'])                              # a glob in a request is a literal name, never expanded

    def test_a_r01b_a_malformed_default_grant_entry_is_reported_and_the_rest_still_matches(self):
        scope = st().Scope(['src/', 'the parser module: see notes'], ['src/'])
        self.assertTrue(scope.allows('src/zz/later.py'))
        self.assertEqual([r['entry'] for r in scope.refused_grant], ['the parser module: see notes'])

    def test_a_r13_absolute_drive_and_unc_request_paths_are_refused(self):
        tree = st().pin_now(self.root)['tree']
        reader, scope = st().Reader(self.root, tree), st().Scope(GRANT, ['src/'])
        for path in ('/etc/passwd', 'C:/Windows/win.ini', 'c:secret.txt', '//host/share/x', 'src/../other/y.py'):
            result = st().run(reader, scope, {'op': 'read', 'path': path})['result']
            self.assertIn('refused', result, path)
            self.assertNotIn('text', result)

    def test_a_r06_cut_lines_are_marked_and_every_match_of_a_long_file_is_reachable(self):
        lines = [('match %02d ' % i) + ('x' * (500 if i == 3 else 5)) for i in range(1, 26)]
        tree = self.tree({'src/many.txt': ('\n'.join(lines) + '\n').encode()})
        reader, scope = st().Reader(self.root, tree), st().Scope(GRANT, ['src/'])
        first = st().run(reader, scope, {'op': 'search', 'query': 'match', 'path': 'src'})['result']
        self.assertEqual(len(first['matches']), 20)
        cut = next(m for m in first['matches'] if m['line'] == 3)
        self.assertEqual(cut['text_truncated'], {'delivered': 200, 'total': len(lines[2])})
        rest = st().run(reader, scope, {'op': 'search', 'cursor': first['next_cursor']})['result']
        self.assertEqual([m['line'] for m in rest['matches']], [21, 22, 23, 24, 25])
        self.assertTrue(rest['coverage']['exhausted'])

    def test_a_r11_a_case_different_path_gets_a_hint(self):
        tree = st().pin_now(self.root)['tree']
        result = st().run(st().Reader(self.root, tree), st().Scope(GRANT, ['src/']), {'op': 'read', 'path': 'SRC/MAIN.PY'})['result']
        self.assertIn('case_sensitive_tree: src/main.py', result['refused'])


class RoundTests(SourceFixture):
    def run_until_stop(self, limit=8):
        states = []
        for _ in range(limit):
            result = self.step()
            states.append(result['state'])
            if result['state'] != 'continuing': return states, result
        return states, result

    def test_a_r02_a_report_node_that_always_continues_stops_at_max_rounds(self):
        self.plan(self.item(read=('a.txt',), write=(), rounds=1))
        self.values += [lambda p, s: ask({'op': 'search', 'query': 'q%d' % len(self.calls)}, report=True)] * 12
        states, last = self.run_until_stop()
        self.assertEqual(states, ['continuing', 'held'])
        self.assertEqual(last['classification'], 'rounds_exhausted')
        self.assertEqual(len(self.calls), 2)                                    # max_rounds + 1 model rounds, then nothing more

    def test_a_r02b_a_write_node_with_empty_requests_stops_at_max_rounds(self):
        self.plan(self.item(rounds=1))
        self.values += [lambda p, s: ask()] * 12
        states, last = self.run_until_stop()
        self.assertEqual(states, ['continuing', 'held'])
        self.assertEqual(len(self.calls), 2)

    def test_a_r08_a_write_node_that_read_and_wrote_nothing_is_refused_at_its_final_answer(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'}),
                        lambda p, s: {'summary': 'nothing to change', 'files': [], 'backlog': []}]
        self.assertEqual(self.step()['state'], 'continuing')
        final = self.step()
        self.assertEqual(final['state'], 'held', final)
        self.assertIn('artifact file list', final['reason'])
        self.assertNotIn('node.produced', self.kinds())

    def test_a_r04_round_count_and_repeat_memory_hold_across_a_new_chain(self):
        self.plan(self.item(rounds=3))
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'}), lambda p, s: ask({'op': 'list', 'path': 'src/lib'})]
        self.assertEqual([self.step()['state'], self.step()['state']], ['continuing', 'continuing'])     # main.py was read in round 2
        changed = self.item(rounds=3); changed['goal'] = 'Produce evidence for O1 again'
        self.plan(changed)                                                      # a new generation without `continues`: a new chain
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'}, {'op': 'read', 'path': 'src/lib/x.py'}),
                        lambda p, s: ask({'op': 'list', 'path': 'src'})]
        third = self.step()
        self.assertEqual(third['state'], 'continuing')
        receipt = self.receipt(third)
        self.assertEqual([r['request'] for r in receipt['source']['refused']], [{'op': 'read', 'path': 'src/main.py'}])   # same tree: a repeat
        self.assertEqual(receipt['source']['rounds_used'], 3)                    # counted across the chains of the node
        fourth = self.step()
        self.assertEqual((fourth['state'], fourth.get('classification')), ('held', 'rounds_exhausted'))

    def test_a_r04b_a_re_pin_on_a_new_tree_is_recorded_and_allows_reading_the_new_content(self):
        self.plan(self.item(rounds=3))
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'})]
        self.step()
        (self.root / 'src' / 'main.py').write_text('print("changed")\n'); self.commit('changed main')
        changed = self.item(rounds=3); changed['goal'] = 'Produce evidence for O1 on the changed source'
        self.plan(changed)
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'})]
        receipt = self.receipt(self.step())
        self.assertEqual(receipt['source']['requests'], [{'op': 'read', 'path': 'src/main.py'}])
        self.assertTrue(receipt['source']['previous_tree'])
        self.assertNotEqual(receipt['source']['previous_tree'], receipt['source']['tree'])

    def test_a_r07_unreadable_chain_evidence_refuses_the_round_and_holds(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'})]
        first = self.step()
        results = self.receipt(first)['source']['results']
        (self.store.root / 'blobs' / results).unlink()
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/lib/x.py'})]
        held = self.step()
        self.assertEqual((held['state'], held.get('classification')), ('held', 'rounds_exhausted'), held)
        receipt = self.receipt(held)
        self.assertIn('cannot be read', receipt['source']['chain_problem'])
        self.assertEqual(receipt['source']['count'], 0)                          # nothing executed on a chain it cannot read

    def test_a_r05_a_forged_cursor_at_offset_zero_and_another_case_are_repeats(self):
        self.plan(self.item())
        kept = {}
        def first(prompt, schema):
            tools = body_of(prompt)['source_tools']
            kept.update(tree=tools['source']['tree'], scope=tools['results'][0]['result']['scope'])
            return ask({'op': 'read', 'path': 'src/main.py'}, {'op': 'search', 'query': 'helper'})
        def second(prompt, schema):
            class Scope: hash = kept['scope']
            forged = st().cursor(kept['tree'], Scope, 'read', {'path': 'src/main.py'}, 0)
            return ask({'op': 'read', 'cursor': forged}, {'op': 'search', 'query': 'HELPER'})
        self.values += [first, second]
        self.step()
        receipt = self.receipt(self.step())
        self.assertEqual(receipt['source']['requests'], [])
        self.assertTrue(all(r['reason'].startswith('repeat') for r in receipt['source']['refused']), receipt['source']['refused'])

    def test_a_r09_an_oversized_request_list_is_bounded(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask(*[{'op': 'search', 'query': 'q%d' % i} for i in range(30)])]
        receipt = self.receipt(self.step())
        self.assertEqual(len(receipt['source']['requests']), 8)
        self.assertEqual(len(receipt['source']['refused']), 9)                   # 8 past the round's 8, one row for the rest
        self.assertEqual(receipt['source']['refused'][-1]['count'], 14)

    def test_a_r10_the_node_identity_carries_no_timing(self):
        self.plan(self.item())
        seen, real = {}, self.adapter.prepare
        def spy(ledger, control, task, item, attempt):
            seen['item'] = dict(item)
            return real(ledger, control, task, item, attempt)
        self.values.append(lambda p, s: done())
        with patch.object(self.adapter, 'prepare', side_effect=spy):
            self.step()
        self.assertNotIn('seconds', seen['item']['source_tree'])
        started = next(p for k, p in self.events() if k == 'node.started')
        self.assertIn('seconds', started['source_tree'])                         # the timing stays observable in the event

    def test_a_r13_two_concurrent_continuations_run_one_attempt(self):
        self.plan(self.item())
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'src/main.py'}), lambda p, s: done(), lambda p, s: done()]
        self.step()
        results, barrier = [], threading.Barrier(2)
        def race():
            barrier.wait()
            try:
                results.append(self.engine.step(self.ledger, 'P1', NativeExecutor(self.ledger), control=self.control)['state'])
            except LedgerError as error:
                results.append('refused: ' + str(error)[:80])
        threads = [threading.Thread(target=race) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join(120)
        self.assertEqual(len(self.calls), 2, results)                            # one more model round, not two
        self.assertIn('produced', results)


class GrantRuleTests(SourceFixture):
    def test_a_r03_a_declared_read_grant_binds_node_read(self):
        node = self.item()
        del node['sources']
        node['read'] = ['other/y.py']
        with self.assertRaisesRegex(LedgerError, 'read grant'):
            self.plan(node)


class DefaultGrantTests(SourceFixture):
    grant = None                                                                 # no authority.read: scope.owned + understanding.target.paths

    def test_a_r13_the_default_grant_end_to_end(self):
        with self.assertRaisesRegex(LedgerError, 'read grant'):
            self.plan(self.item(read=('out.txt',), patterns=('src/',)))
        self.plan(self.item(read=('out.txt',), patterns=('out.txt', 'a.txt')))
        self.values += [lambda p, s: ask({'op': 'read', 'path': 'a.txt'}, {'op': 'read', 'path': 'src/main.py'}), lambda p, s: done()]
        self.step(); self.step()
        catalogue = [e['path'] for e in self.results(0)[0]['result']['entries']]
        self.assertEqual(catalogue, ['a.txt', 'out.txt'])
        read, outside = (r['result'] for r in self.results(1))
        self.assertEqual(read['text'], 'one\n')
        self.assertEqual(outside['refused'], 'outside the read scope')
        self.assertEqual(self.tools(0)['scope']['basis'], 'scope.owned + understanding.target.paths')
