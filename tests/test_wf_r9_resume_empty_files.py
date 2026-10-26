"""R9: a resumed attempt that answers `files: []` and no continuation says the partial candidate is complete; the same answer on a
fresh attempt stays refused."""
import json as _json

import tests.test_wf_managed_hold as hold


class ResumeEmptyFilesTests(hold.ManagedHoldFixture):
    answers = ()

    def factory(self, control, provider):
        from onecrew.process_core import Supervisor, native_python
        from onecrew.subscription import environment
        case = self
        self.go = self.temp_path() / 'operation-go'
        self.prompts = getattr(self, 'prompts', [])
        class Worker:
            def capability(self): return {'provider': provider, 'mode': 'local-test-artifact-no-tools'}
            def run(self, attempt, prompt, schema, profile):
                case.launches.append(attempt['id']); case.prompts.append(prompt)
                directory = case.ledger.state_root / 'worker-io' / attempt['id']; directory.mkdir(parents=True)
                script = ('import pathlib,sys,time\n'
                          'pathlib.Path(sys.argv[1]).write_text("started")\n'
                          'until=time.monotonic()+float(sys.argv[3])\n'
                          'while not pathlib.Path(sys.argv[5]).exists() and time.monotonic()<until: time.sleep(0.05)\n'
                          'with pathlib.Path(sys.argv[2]).open("a") as out: out.write("operation completed\\n")\n'
                          'pathlib.Path("answer.json").write_text(sys.argv[4])\n')
                value = case.answers[len(case.launches) - 1]
                return Supervisor(control).run(attempt, [native_python(), '-c', script, str(case.started), str(case.marker), '25', _json.dumps(value), str(case.go)],
                                               cwd=directory, timeout=min(30, profile['step_seconds']), env=environment())
            def result(self, attempt):
                return _json.loads((case.ledger.state_root / 'worker-io' / attempt['id'] / 'answer.json').read_text()), []
        return Worker()

    PARTIAL = {'summary': 'first half', 'files': [{'path': 'a.txt', 'content': 'part one\n'}], 'backlog': [], 'continuation': {'remaining': 'maybe nothing'}}
    EMPTY = {'summary': 'nothing left', 'files': [], 'backlog': []}
    TAKEN = {'summary': 'second half', 'files': [{'path': 'a.txt', 'content': 'part one\npart two\n'}], 'backlog': []}

    def second_step(self, answers):
        self.answers = answers; (self.temp_path() / 'operation-go').write_text('go')
        first = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual(first['state'], 'continuing', first)
        return self.engine.step(self.ledger, 'P1', self.adapter)

    def test_a_resumed_attempt_with_empty_files_finishes_with_the_partial_candidate(self):
        second = self.second_step([self.PARTIAL, self.EMPTY])
        self.assertEqual(second['state'], 'produced', second)
        self.assertEqual(self.store.context(second['artifact'])['a.txt'], 'part one\n')

    def test_b_a_fresh_attempt_with_empty_files_is_still_refused(self):
        self.answers = [self.EMPTY]; (self.temp_path() / 'operation-go').write_text('go')
        first = self.engine.step(self.ledger, 'P1', self.adapter)
        self.assertEqual((first['state'], first['reason']), ('held', 'Invalid artifact file list.'))
        self.assertNotIn('node.produced', self.kinds())

    def test_c_a_resumed_attempt_that_returns_files_takes_them(self):
        second = self.second_step([self.PARTIAL, self.TAKEN])
        self.assertEqual(second['state'], 'produced')
        self.assertEqual(self.store.context(second['artifact'])['a.txt'], 'part one\npart two\n')


if __name__ == '__main__':
    import unittest; unittest.main()
