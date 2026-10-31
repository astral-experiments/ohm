"""Offline checks for the selected native endpoints and the fail-closed paired comparisons."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

p=Path(__file__).with_name("study.py")
spec=importlib.util.spec_from_file_location("ruff_release_check",p)
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)

def unit(n,kind,exe):
    return {"reason":"compiler-artifact","package_id":"path+file:///source#ruff@0.0.0",
            "target":{"name":n,"kind":[kind]},"features":[],"profile":{"test":kind=="test"},
            "executable":exe,"filenames":[exe],"fresh":True}
def records(rows):
    return b"\n".join(json.dumps(v).encode() for v in [*rows,{"reason":"build-finished","success":True}])
def result(rev):
    return {"revision":rev,"cli":[int(rev==s.NEW)],"tests":([s.COMMON,s.ADDED] if rev==s.NEW else [s.COMMON]),
            "proofs":{k:{"raw":rev,"output":"/work/"+k,"same_path_image":"checked-"+rev,"modules":{"cgu":rev}} for k in s.NAMES}}
class Contract(unittest.TestCase):
    def test_actual_source_shapes(self):
        a=unit("ruff","bin","/target/ruff");b=unit("integration_test","test","/target/deps/test")
        self.assertEqual(set(s.read_units(records([a,b]))[1]),set(s.NAMES))
        for bad in ([a],[a,b,b],[a,{**b,"profile":{"test":False}}]):
            with self.assertRaises(RuntimeError):s.read_units(records(bad))
    def test_two_native_outputs_and_disjoint_unrelated_link(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"ruff").write_bytes(b"APP");(root/"integration_test").write_bytes(b"TEST")
            (root/"ruff-0123456789abcdef").write_bytes(b"APP")
            selected={k:root/k for k in s.NAMES}
            def row(x):return {"argv":["/xcode/ld","-o",str(root/x)]}
            def hits(xs):return s.native_outputs({"linkers":[row(x) for x in xs]},selected)
            self.assertEqual(set(hits(["ruff-0123456789abcdef","integration_test","build_script_build"])),set(s.NAMES))
            self.assertEqual(hits([]),{})
            with self.assertRaises(RuntimeError):hits(["ruff","ruff-0123456789abcdef"])
            (root/"ruff-0123456789abcdef").write_bytes(b"STALE")
            with self.assertRaises(RuntimeError):hits(["ruff-0123456789abcdef"])
    def test_pure_linker_queries_are_separate(self):
        self.assertIsNone(s.ld_output(["ld","-v"]))
        self.assertEqual(s.ld_output(["ld","-v","file.o","-o","app"]),Path("app"))
        with self.assertRaises(RuntimeError):s.ld_output(["ld","file.o"])
    def test_seeded_whole_byte_and_interface_rejections(self):
        for mutation in ("same_path_image","modules","output","cli","tests"):
            a,b=result(s.OLD),result(s.NEW)
            rows={"A":result(s.OLD),"B":result(s.NEW)}
            if mutation in ("cli","tests"):rows["B"][mutation]=[]
            else:rows["B"]["proofs"]["integration_test"][mutation]="different"
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                s.hashes_by_revision(rows,{s.OLD:a,s.NEW:b})
    def test_all_source_states_both_independently_empty(self):
        refs={r:result(r) for r in (s.OLD,s.NEW)}
        rows={n:result(r) for n,r in s.STEPS}
        checked=s.hashes_by_revision(rows,refs)
        self.assertEqual(set(checked),set(rows))
        self.assertTrue(all(all(all(v.values()) for v in x.values()) for x in checked.values()))
        rows["edit-B"]["proofs"]["ruff"]["raw"]="different-nonce-in-authenticated-MachO"
        checked=s.hashes_by_revision(rows,refs)
        self.assertFalse(checked["edit-B"]["ruff"]["raw_equal"])

if __name__=="__main__":unittest.main()
