"""Negative controls for complete OS custody of a real examples census."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from examples_reader import NAMES, checked_example_artifacts, events_census, typed_rustc

class TestAdmission(unittest.TestCase):
    def setUp(self):
        self.tools={name:{"physical":"/physical/"+name,"cdhash":(str(i+1)*40)}
                    for i,name in enumerate(("cargo","rustc","clang","ld"))}
        def row(name,seq,pid,ppid,args):
            t=self.tools[name]
            return {"seq":seq,"pid":pid,"ppid":ppid,"pgid":42,"path":t["physical"],
                    "cdhash":t["cdhash"].upper(),"argv":[t["physical"]]+args}
        self.rows=[row("cargo",10,42,1,["build","--examples"]),
                   row("rustc",11,50,42,["--crate-name","format", "crates/ruff_annotate_snippets/examples/format.rs",
                                          "-C","incremental=/target/inc"]),
                   row("clang",12,59,50,["-o","/target/format"]),
                   row("ld",13,60,59,["-o","/target/format","one.o"])]

    def test_observed_ld(self):
        c=events_census(self.rows,self.tools)
        self.assertEqual(c["all_typed_rustcs"],{"full":1})
        self.assertEqual([(k["crate"],k["output"],k["parent_rustc"],k["parent_clang"]) for k in c["true_xcode_ld"]],
                         [("format","/target/format",11,12)])
        self.assertEqual(events_census(self.rows[:-1],self.tools)["true_xcode_ld"],[])

    def test_untrusted_process(self):
        for i,k,v in ((3,"cdhash","f"*40),(3,"ppid",48),(3,"path","/other/ld"),(3,"path","/other/ld64"),
                      (3,"seq",12),(2,"path","/fake/clang"),(3,"argv",["ld","@/tmp/l.rsp"]),
                      (3,"argv",["ld","-o","a","-o","b"]),(1,"argv",["rustc","--crate-name","format",
                        "crates/ruff_annotate_snippets/examples/format.rs"])):
            with self.subTest(field=(i,k,v)):
                rows=copy.deepcopy(self.rows);rows[i][k]=v
                with self.assertRaises(RuntimeError): events_census(rows,self.tools)

    def test_link_only(self):
        r=copy.deepcopy(self.rows[1])
        r["argv"]=["rustc","--crate-name","format","/target/format.rlink","-Z","link-only"]
        self.assertEqual(typed_rustc(r,self.tools),{"crate":"format","mode":"link-only","example":True,"incremental":[]})

    def test_complete_typed_cargo(self):
        rows=[{"reason":"compiler-artifact","package_id":"path+file:///ruff/crates/ruff_annotate_snippets#0.0.15",
               "target":{"name":n,"kind":["example"],"src_path":"/ruff/crates/ruff_annotate_snippets/examples/"+n+".rs"},
               "executable":"/target/examples/"+n} for n in NAMES]
        def parse(xs):
            return checked_example_artifacts(b"\n".join(json.dumps(q).encode() for q in xs+[{"reason":"build-finished","success":True}]),True)
        self.assertEqual(set(parse(rows)),set(NAMES))
        for wrong in (rows[:-1],rows+rows[:1],[dict(rows[0],package_id="path+file:///other#0.0.15"),*rows[1:]]):
            with self.assertRaises(RuntimeError): parse(wrong)

if __name__=="__main__": unittest.main()
