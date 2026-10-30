"""Exercise the shell ordering and two stream pairs using a small ordinary command."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from ast_point_clock import combined


class Contiguous(unittest.TestCase):
    def test_real_shell_prefix(self):
        original=subprocess.Popen
        def local_time(cmd,*args,**kwargs):
            self.assertEqual(cmd[:3],['/usr/bin/time','-l','-o'])
            Path(cmd[3]).write_text('  0.22 real  0.07 user  0.12 sys\n    10000 instructions retired\n')
            return original(cmd[4:],*args,**kwargs)
        with tempfile.TemporaryDirectory() as t, patch('ast_point_clock.subprocess.Popen',local_time):
            root=Path(t)
            visit='if test -f first; then echo edited-to-repeat; echo repeat-err >&2; else : > first; echo edited; echo edit-err >&2; fi'
            rows,clock=combined(['/bin/sh','-c',visit],root,{'HOME':t,'PATH':'/usr/bin:/bin'},root/'pass')
            self.assertEqual([r[1:3] for r in rows],[(b'edited\n',b'edit-err\n'),(b'edited-to-repeat\n',b'repeat-err\n')])
            self.assertGreater(clock['ns'],0)
            fail='if test -f never; then echo second-ran > bad; else : > never; exit 9; fi'
            with self.assertRaisesRegex(RuntimeError,'consecutive ordinary Cargo builds failed'):
                combined(['/bin/sh','-c',fail],root,{'HOME':t,'PATH':'/usr/bin:/bin'},root/'fail')
            self.assertFalse((root/'bad').exists())
if __name__=='__main__':unittest.main()
