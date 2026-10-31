"""A lost installed image, bad return status, or unknown lifetime always refuses."""
from io import BytesIO
from pathlib import Path
import os
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));os.environ.setdefault('RUNNER_TEMP',tempfile.gettempdir())
import trace_events as t

START=b'/usr/bin/strace: ptrace_setoptions = 0x1000df\n'
EXEC=b'/usr/bin/strace: [wait(0x04057f) = 11] WIFSTOPPED,sig=SIGTRAP,EVENT_EXEC (4)\n'

def life(pid,code,images):
    p=str(pid).encode()
    return (b'/usr/bin/strace: new tcb for pid '+p+b', active tcbs:1\n'+
            b'/usr/bin/strace: [wait(0x80057f) = '+p+b'] WIFSTOPPED,sig=SIGTRAP,EVENT_STOP (128)\n'+images+
            f'/usr/bin/strace: [wait(0x{code<<8:06x}) = {pid}] WIFEXITED,exitcode={code}\n'.encode()+
            b'/usr/bin/strace: dropped tcb for pid '+p+b', 0 remain\n')

OK=b'11 execve("/bin/true", ["true"], 0x7ff12 /* 3 vars */) = 0\n'
OPAQUE=b'12 execve(0x12345000, 0x12346000, 0x12347000 <detached ...>\n'
DBG=START+life(11,0,EXEC)+life(12,42,b'')

def check(raw=OK+OPAQUE,events=DBG):return t.parse(BytesIO(raw),BytesIO(events))

class KernelWitness(unittest.TestCase):
    def test_proven_retiring_thread(self):
        normalized,r=check();self.assertEqual(normalized,OK);self.assertEqual(r['installed_images'],1)
        self.assertEqual(r['noninstalled_terminal_tasks']['12']['terminal'],42)
    def test_committed_image_lost_argument_vector(self):
        with self.assertRaises(ValueError):check(raw=OPAQUE.replace(b'12 ',b'11 '))
        with self.assertRaises(ValueError):check(events=DBG+EXEC.replace(b'= 11]',b'= 12]'))
    def test_missing_kernel_exec(self):
        with self.assertRaises(ValueError):check(events=DBG.replace(EXEC,b''))
    def test_dead_task_without_final_status_or_unique_lifetime(self):
        lines=DBG.splitlines(True)
        with self.assertRaises(ValueError):check(events=b''.join(x for x in lines if b'= 12] WIFEXITED' not in x))
        with self.assertRaises(ValueError):check(events=DBG+life(12,42,b''))
        with self.assertRaises(ValueError):check(raw=OK+OPAQUE.replace(b'12 ',b'13 '))
    def test_nonzero_positive_or_surprising_success(self):
        for status in (b'0',b'59'):
            with self.assertRaises(ValueError):check(raw=OK+OPAQUE+b'12 <... execve resumed>) = '+status+b'\n')
    def test_do_not_excuse_uncertain_entry_on_an_executing_pid(self):
        with self.assertRaises(ValueError):check(raw=OK+OPAQUE.replace(b'12 ',b'11 '))
    def test_unknown_or_killed_task_not_quarantined(self):
        with self.assertRaises(ValueError):check(events=DBG.replace(b'0x002a00) = 12] WIFEXITED,exitcode=42',b'0x000009) = 12] WIFSIGNALED,sig=SIGKILL'))
        with self.assertRaises(ValueError):check(events=DBG.replace(b'0x04057f',b'0x03057f'))
    def test_filter_and_fork_trace_required(self):
        with self.assertRaises(ValueError):check(events=DBG.replace(b'1000df',b'1000c1'))

if __name__=='__main__':unittest.main()
