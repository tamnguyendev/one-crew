"""Exact namespace supersession rules. Synthetic observations prove rules only."""
import copy
import unittest

from wfkit import development_gate as dev, kitguard, namespace_lineage as lineage


class NamespaceLineageTests(unittest.TestCase):
    def setUp(self):
        self.record=lineage.validate(dev.ROOT)
        self.raw={'ok':False,'unchecked':[],'problems':[{'code':'changed','release':'R00','pin':lineage.FILE,
            'pinned_sha256':self.record['old_sha256'],'actual_sha256':self.record['new_sha256']}]}
        observed={'exit_code':0,'tests_run':5,'tests_passed':5,'tests_errors':0,'tests_skipped':0,'result':'pass',
                  'loaded':{'fixture':{'path':'fixture-only'}}}
        self.receipt={'record':copy.deepcopy(self.record),'record_sha256':kitguard.canon_sha(self.record),
                      'wheel_sha256':'a'*64,'kind':'actual dual-history execution','old':copy.deepcopy(observed),'new':copy.deepcopy(observed)}

    def test_exact_history_is_retained_and_only_this_change_can_be_superseded(self):
        result=lineage.assess(self.raw,self.record,self.receipt,'a'*64)
        self.assertTrue(result['ok']); self.assertEqual(result['raw'],self.raw)
        self.assertFalse(result['raw']['ok']); self.assertEqual(len(result['superseded']),1)
        extra=copy.deepcopy(self.raw); extra['problems'].append({'code':'changed','pin':'other.py'})
        self.assertFalse(lineage.assess(extra,self.record,self.receipt,'a'*64)['ok'])

    def test_each_history_wrong_wheel_empty_skipped_and_failed_proof_refuse(self):
        for side in ('old','new'):
            for change in ({'tests_run':0},{'tests_skipped':1},{'exit_code':1},{'loaded':{}},{'result':'fail'}):
                receipt=copy.deepcopy(self.receipt); receipt[side].update(change)
                with self.subTest(side=side,change=change):
                    self.assertFalse(lineage.assess(self.raw,self.record,receipt,'a'*64)['ok'])
        self.assertFalse(lineage.assess(self.raw,self.record,self.receipt,'b'*64)['ok'])
        self.assertFalse(lineage.assess(self.raw,self.record,None,'a'*64)['ok'])

    def test_movable_old_revision_arbitrary_file_and_changed_source_refused(self):
        for change in ({'old_commit':'HEAD'},{'file':'tests/test_other.py'},{'new_sha256':'0'*64}):
            record=copy.deepcopy(self.record); record.update(change)
            with self.subTest(change=change),self.assertRaises(ValueError): lineage.validate(dev.ROOT,record)
        record=copy.deepcopy(self.record); record['sources'][0]['sha256']='0'*64
        with self.assertRaises(ValueError): lineage.validate(dev.ROOT,record)


if __name__=='__main__': unittest.main()
