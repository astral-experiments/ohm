"""Run without a compiler or Cargo. Fail if a stale generation can pass the AST evidence gate."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
from ast_developer import VERBS, orders
from ast_developer_witness import before, after, runtime
from study import env_for, load


class Witness(unittest.TestCase):
    def test_local_crate_generation(self):
        for verb in VERBS:
            with self.subTest(verb=verb), tempfile.TemporaryDirectory() as t:
                root=Path(t).resolve();sdk=root/'native';work=root/'study-work'
                (sdk/'bin').mkdir(parents=True);(sdk/'bin/rustc').write_bytes(b'synthetic file, never executed')
                (work/'target').mkdir(parents=True);(work/'shared').mkdir()
                env=env_for(work,sdk);host=runtime(env)
                inc=work/'target/debug/incremental/abc'
                crate=inc/'ruff_python_ast-abc'
                def create(state):
                    folder=crate/state;folder.mkdir(parents=True)
                    for name in ('dep-graph.bin','work-products.bin','0.native.o'):(folder/name).write_bytes(state.encode())
                argv=['rustc','--crate-name','ruff_python_ast','--emit=dep-info,link','-C','incremental='+str(inc)]
                if verb=='test':argv.append('--test')
                event={'pid':19,'path':str(sdk/'bin/rustc'),'argv':argv}
                original=before(work);create('s-first')
                after(host,env,root/'cold',[event],original,verb)
                first=before(work);create('s-second')
                after(host,env,root/'edit',[event],first,verb)
                after(host,env,root/'repeat-1',[],before(work),verb)
                self.assertEqual(load(root/'edit'/'ast-generations.json')['new_or_changed'].keys(),{str((crate/'s-second').relative_to(work))})
                with self.assertRaisesRegex(RuntimeError,'distinct AST generation'):
                    after(host,env,root/'other'/'edit',[event],before(work),verb)
                with self.assertRaises(RuntimeError):runtime({**env,'CI':'true'})
                self.assertEqual(sorted(orders(verb,'confirm')),['CP']*6+['PC']*6)

if __name__=='__main__':unittest.main()
