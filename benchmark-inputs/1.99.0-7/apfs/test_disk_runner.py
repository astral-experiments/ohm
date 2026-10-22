import importlib.util, os, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('disk_runner',Path(__file__).with_name('run-disk.py'))
disk=importlib.util.module_from_spec(spec);spec.loader.exec_module(disk)

class DiskRunnerTests(unittest.TestCase):
    def command_with_output(self,output,returncode=0):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);study=disk.DiskReplay.__new__(disk.DiskReplay)
            study.options=SimpleNamespace(require_idle=False,compiler_accounting='verbose',timeout=30)
            study.output=root/'evidence'
            scenario=SimpleNamespace(project='ruff')
            step={'program':'cargo','args':['test']}
            with patch.object(study,'environment',return_value={}),patch.object(disk.subprocess,'run',return_value=subprocess.CompletedProcess([],returncode,output)):
                return study.run_command(scenario,root,step,'ohm','ohm-1.99.0-7',1,1)
    def test_package_cache_waits_are_recorded_for_allocation(self):
        sample=self.command_with_output('    Blocking waiting for file lock on package cache\nrunning 2 tests\ntest result: ok. 2 passed; 0 failed\n')
        self.assertEqual(sample['tests_started'],2)
        self.assertEqual(sample['package_cache_waits'],['Blocking waiting for file lock on package cache'])
        self.assertFalse(sample['wall_seconds_are_performance_measurement'])
    def test_private_target_lock_still_rejected(self):
        with self.assertRaisesRegex(disk.replay.BenchmarkError,'build-directory lock'):
            self.command_with_output('Blocking waiting for file lock on build directory\nrunning 2 tests\n')
    def test_failed_command_still_rejected(self):
        with self.assertRaisesRegex(disk.replay.BenchmarkError,'exited 1'):
            self.command_with_output('Blocking waiting for file lock on package cache\nrunning 2 tests\n',1)
    def test_zero_tests_still_rejected(self):
        with self.assertRaisesRegex(disk.replay.BenchmarkError,'zero tests'):
            self.command_with_output('Blocking waiting for file lock on package cache\nrunning 0 tests\n')
    def test_published_command_counts(self):
        total=0
        for project,fixture,single,forks in [('ruff','disk-1.99.0-1-ruff.json',13,77),('uv','disk-1.99.0-1-uv.json',20,92)]:
            scenario=disk.replay.load_scenario(disk.REPO/'scripts/session_replays'/fixture)
            edits=[i for i,s in enumerate(scenario.steps) if s['kind']=='edit']
            count=lambda steps:sum(s['kind']=='command' for s in steps)
            self.assertEqual(len(scenario.warmup)+count(scenario.steps),single)
            self.assertEqual(len(scenario.warmup)+count(scenario.steps[:edits[1]])+9*count(scenario.steps[edits[1]:]),forks)
            total+=2*(single+forks)
        self.assertEqual(total,404)
    def test_private_namespace_hardlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'targets/1/debug/build/workspaces/a';b=root/'targets/2/debug/build/workspaces/b'
            a.mkdir(parents=True);b.mkdir(parents=True);(a/'output').write_bytes(b'data');os.link(a/'output',b/'output')
            with self.assertRaisesRegex(RuntimeError,'share private inodes'):disk.private_inode_audit(root,'ohm')
    def test_separate_inodes_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ['1','2']:
                p=root/'targets'/name/'debug/build/workspaces'/name;p.mkdir(parents=True);(p/'output').write_bytes(b'data')
            self.assertEqual(disk.private_inode_audit(root,'ohm')['cross_workspace_shared_inodes'],[])
    def test_target_hardlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'targets/1';b=root/'targets/2';a.mkdir(parents=True);b.mkdir(parents=True)
            (a/'output').write_bytes(b'data');os.link(a/'output',b/'output')
            with self.assertRaisesRegex(RuntimeError,'share private inodes'):disk.private_inode_audit(root,'stock')

if __name__=='__main__':unittest.main()
