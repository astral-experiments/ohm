import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import provider_edges as edge

class Inputs(unittest.TestCase):
    def test_native_policy_and_one_statement(self):
        with tempfile.TemporaryDirectory() as name:
            base=Path(name)
            for place in ("direct","library"):
                for policy in (False,True):
                    src=base/f"{place}-{policy}";src.mkdir()
                    leaf=edge.form(src,place,policy);self.assertEqual(leaf,src/"trigger/src/lib.rs")
                    all_rs="".join(p.read_text() for p in src.rglob("*.rs"))
                    self.assertEqual(all_rs.count("::asm!("),1)
                    self.assertEqual(all_rs.count('asm!("crc32w {v:w}, {v:w}, {d:w}", v = inout(reg) value, d = in(reg) data);'),1)
                    self.assertNotIn("inout(vreg)",all_rs)
                    build=(src/"build.rs").read_text()
                    self.assertEqual("rerun-if-changed={name}" in build,policy)
                    self.assertIn('["early","late"]',build)

    def test_empty_reference_preserves_state(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);paths=[root/n for n in ("target","shared","cargo-home")]
            previous=[]
            for p in paths:p.mkdir();(p/"test").write_bytes(b"warm");previous.append(p.stat().st_ino)
            def cold():
                self.assertTrue(all(not list(p.iterdir()) for p in paths))
                self.assertTrue(all(p.stat().st_ino!=ino for p,ino in zip(paths,previous)))
                for p in paths:(p/"test").write_bytes(b"clean")
                return "matched"
            self.assertEqual(edge.with_empty(root,cold),"matched")
            self.assertTrue(all((p/"test").read_bytes()==b"warm" for p in paths))
            self.assertTrue(all(p.stat().st_ino==ino for p,ino in zip(paths,previous)))

    def test_unwatched_and_changed_rust_are_separate(self):
        data={}
        for role in "PC":
            for policy in ("unwatched","declared"):
                arm={}
                for name,state,rust in edge.STEPS:
                    ok=edge.NATIVE[state] is not None
                    value=[0,[edge.NATIVE[state],rust],"good"] if ok else [101,None,None]
                    warm=value
                    if role=="C" and name in ("higher-no-rust","missing-rust-edit"):
                        warm=[0,[17,rust],"bad"]
                    arm[name]={"warm":warm,"empty":value,"same_raw":warm==value,"same_text":warm==value}
                data[f"{role}-direct-{policy}-default"]=arm
        result=edge.classify(data)
        self.assertEqual(len(result["unwatched_classification"]),1)
        self.assertEqual(len(result["unexpected_declared_or_Rust_outcomes"]),3)
        self.assertEqual(len(result["parent_child_differences"]),4)

if __name__=="__main__":unittest.main()
