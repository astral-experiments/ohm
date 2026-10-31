import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native
import formats
import dylib
import subject


class Protocol(unittest.TestCase):
    def test_registered_source(self):
        s = json.loads((native.HERE / "source.json").read_bytes())
        self.assertEqual(s["candidate"], "00526133a6352eb88eca70382000e6221253235c")
        self.assertEqual(s["previous"],"bbd6c9b7da30dee3f8b3ed8121116873707b7a58")
        self.assertEqual(s["parent"], native.PARENT)
        self.assertEqual(s["trees"]["compiler"], "56204f7d037d7dfcac798c33568b544c7e5cbe18")
        self.assertEqual(s["trees"][""], "2080285f6fcfa69a23f4589eef8e5306dd4161ea")
        self.assertEqual(len(s["files"]),14)
        self.assertEqual(s["pack_sha256"],native.sha(native.HERE/"source.pack"))

    def test_exact_factors(self):
        for case in native.CASES:
            f,_,_,args = native.parameters(case)
            a,b = (native.hidden(f,case,x) for x in "AB")
            if case in ("abi","nested"):
                self.assertEqual(a.replace(b"u32",b"u64"), b)
            else:
                self.assertEqual(a.replace(b"_aaaa",b"_bbbb" if case!="body" else b"_aaaa").replace(
                   b".store(17,", b".store(83," if case!="name" else b".store(17,"), b)
            self.assertIn("--locked",args)
            self.assertIn("--offline",args)
            self.assertNotIn("-Z",str(args))

    def test_graph_and_metadata_controls(self):
        self.assertEqual((formats.GRAPH["P"],formats.GRAPH["C"]),(8,10))
        for c in (b"rustc x (Ohm metadata 1)",b"rustc x (Ohm metadata 2)",b"rustc x (Ohm metadata 3)"):
            buf=b"rust\0\0\0\n"+bytes(8)+bytes([len(c)])+c
            self.assertEqual(formats.meta(buf),(17,c.decode()))
            with self.assertRaises(ValueError):
                formats.meta(b"X"+buf[1:])

    def test_real_rust_dylib_sources(self):
        self.assertEqual(len(dylib.CASES),4)
        for case in dylib.CASES:
            d=dylib.specification(case)
            self.assertNotEqual(d['A'],d['B'])
            self.assertNotIn('export_name',d['files']['dep/src/lib.rs']+d['A']+d['B'])
        pure=dylib.specification("pure-rust-dylib-client")
        self.assertTrue(all("unsafe" not in v for v in pure["files"].values()))
        self.assertIn("dylib_client",pure["commands"])

    def test_distinct_named_suites(self):
        self.assertEqual(len(set(subject.REGRESSIONS)),5)
        self.assertIn(subject.TEST,subject.REGRESSIONS)
        self.assertEqual(len(subject.INCREMENTAL_TESTS),2)
        self.assertTrue(any('trait_impl_unreachable_local_trait' in x for x in subject.INCREMENTAL_TESTS))


if __name__=="__main__":
    unittest.main()
