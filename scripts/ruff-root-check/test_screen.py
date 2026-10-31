import copy
import gzip
import hashlib
import json
import subprocess
import zipfile
from unittest.mock import patch
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("RUNNER_TEMP",tempfile.gettempdir())
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import graph
import witness as q
import reopen as v
import screen as s
import originals
import guard


class Gates(unittest.TestCase):
    def test_full_graph(self):
        self.assertEqual(graph.census(s.EXPECTED),{"units":564,"roots":55,"members":52,"packages":405,"edges":1743,
            "modes":{"check":357,"build":155,"run-custom-build":52},"sha256":"f0438acde485ba8b7eb01f00c0772d5182fa0879dffd3bdf1fa9037a60210df5"})
        ids=set(s.EXPECTED["roots"])
        roots=[r["unit"] for r in s.EXPECTED["units"] if r["id"] in ids]
        self.assertEqual(sum(r["target"]["kind"]==["bin"] for r in roots),6)
        self.assertTrue({"ruff_dev","ruff_wasm","ty_server","ty_wasm","ruff_benchmark"}<={r["target"]["name"] for r in roots})

    def test_selection(self):
        tree=Path("/example/ruff")
        src="/home/.cargo/registry/src/index.crates.io-1234567890abcdef/thing-1.0.0/src/lib.rs"
        pkg="registry+https://github.com/rust-lang/crates.io-index#thing@1.0.0"
        self.assertEqual(graph.target_path(pkg,src,tree),"thing-1.0.0/src/lib.rs")
        for strange in (src.replace("1.0.0","9.0.0"),src.replace("registry/src","outside"),src.replace("1234567890abcdef","NOTHEX")):
            with self.assertRaises(ValueError):graph.target_path(pkg,strange,tree)
        with self.assertRaises(ValueError):graph.package("path+file:///different/lib#1",tree)

    def test_actual_roster(self):
        tree=Path("/p");meta="path+file:///p/crates/tool#0.0.0"
        target={"kind":["lib"],"name":"tool","crate_types":["lib"],"src_path":"/p/crates/tool/src/lib.rs"}
        original={"pkg_id":"path+ruff/crates/tool#0.0.0","target":target|{"src_path":"crates/tool/src/lib.rs"},"mode":"check","features":["default"]}
        expected={"units":[{"unit":original}]}
        row={"reason":"compiler-artifact","package_id":meta,"target":target,"features":["default"]}
        self.assertEqual(graph.typed_graph([row],expected,tree),1)
        for rows in ([],[row,row],[row|{"features":[]}]):
            with self.assertRaises(ValueError):graph.typed_graph(rows,expected,tree)

    def test_complete_file_and_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/"target").mkdir();(p/"target/a.rmeta").write_bytes(b"abcdef")
            msgs=[{"reason":"compiler-artifact","target":{"name":"a"},"filenames":[str(p/"target/a.rmeta")]}]
            orig=q.files(msgs,p);store=p/"store";ret=p/"ret";ret.mkdir();q.keep(p/"target/a.rmeta",orig["target/a.rmeta"],store)
            (p/"target/a.rmeta").write_bytes(b"abcxef")
            second=q.files(msgs,p);diff=q.matched_products(second,orig,p,store,ret,p)
            self.assertEqual(diff,{"target/a.rmeta":[orig["target/a.rmeta"],second["target/a.rmeta"]]})
            self.assertEqual(len(list(ret.glob("*.zst"))),2);q.verify_bodies(ret)
            file=next(ret.glob("*.zst"));file.write_bytes(b"bogus")
            with self.assertRaises(ValueError):q.verify_bodies(ret)

    def test_actual_physical_owner_and_flags(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);tree=root/"ruff";deps=root/"target/debug/deps"
            args=["rustc","--crate-name","ruff_dev","crates/ruff_dev/src/main.rs","--emit=dep-info,metadata",
                  "-Zohm-check-relink-inputs","-Zohm-branch-cache=yes","-C","incremental="+str(root/"inc"),"-L","dependency="+str(deps)]
            args+=[word for name in graph.PROVIDERS for word in ("--extern",name+"="+str(deps/("lib"+name+".rmeta")))]
            row={"crate":"ruff_dev","mode":"full","argv":args,"pid":211}; phys={"rustcs":[row]}
            self.assertEqual(set(q.owner(phys,tree,root,"Fon")["providers"]),set(graph.PROVIDERS))
            for r,a in ((row,"Foff"),(row|{"argv":args+args[-2:]},"Fon"),(row|{"argv":args[:-2]},"Fon"),
                        (row|{"argv":[x for x in args if x!="-Zohm-check-relink-inputs"]},"Fon")):
                with self.assertRaises(ValueError):q.owner({"rustcs":[r]},tree,root,a)

    def test_real_invalid_parser_diagnostic(self):
        p={"reason":"compiler-message","target":{"name":"ruff_python_parser"},"message":{"level":"error","code":{"code":"E0308"},
           "spans":[{"is_primary":True,"text":[{"text":"const ohm_branch_switch_invalid: () = 1u32;"}]}]}}
        q.error_check([p])
        with self.assertRaises(ValueError):q.error_check([p,p])
        with self.assertRaises(ValueError):q.error_check([p|{"target":{"name":"unrelated"}}])

    def test_generated_zip_member_and_source_changes(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"typeshed.zip"
            data={n:n.encode() for n in q.STUBS}
            stubs={n:(q.STUBS[n][0],hashlib.sha256(b).hexdigest()) for n,b in data.items()}
            with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED) as z:
                for n,b in data.items():z.writestr(n,b)
                for i in range(501):z.writestr("stub/"+str(i),b"A")
            with patch.dict(q.STUBS,stubs,clear=True):self.assertEqual(q.read_typeshed(path)["entries"],503)
            with self.assertRaises(ValueError):q.read_typeshed(path)

    def test_original_run_and_resource_guards(self):
        run=dict(id=500,head_sha="a"*40,head_branch=s.BRANCH,run_attempt=1,repository={"full_name":s.b.REPO},event="workflow_dispatch",
                 path=".github/workflows/ci.yml",display_title="Two fresh root Ruff check screenings "+"a"*40,status="completed",conclusion="success")
        jobs={"total_count":2,"jobs":[dict(id=i,name=originals.LABEL+p,head_sha=run["head_sha"],run_id=500,run_attempt=1,status="completed",conclusion="success") for i,p in enumerate(s.ORDERS,10)]}
        art={"total_count":2,"artifacts":[dict(id=i,name=originals.PREFIX+p,workflow_run={"id":500,"head_sha":run["head_sha"]},expired=False,size_in_bytes=150,digest="sha256:"+"2"*64) for i,p in enumerate(s.ORDERS,20)]}
        self.assertEqual(set(originals.bind(run,jobs,art,500,"a"*40)),set(s.ORDERS))
        for rr,jj,aa in [(run|{"run_attempt":2},jobs,art),(run|{"conclusion":"failure"},jobs,art),(run,jobs|{"total_count":3},art),
                          (run,jobs,art|{"artifacts":2*[art["artifacts"][0]]})]:
            with self.assertRaises(ValueError): originals.bind(rr,jj,aa,500,"a"*40)
        capacity={k:n*2**30 for k,n in zip(("available_memory","work_free","durable_free"),(12,14,32))}
        self.assertTrue(guard.passes(capacity,(12,14,32)))
        for k,v in capacity.items():self.assertFalse(guard.passes(capacity|{k:v-1},(12,14,32)))

    def test_registered_entrypoints(self):
        for file,args in (("screen.py",["--print-command"]),("reopen.py",["--help"]),("originals.py",["--help"])):
            raw=subprocess.check_output([sys.executable,"-IB",HERE/file,*args],cwd=tempfile.gettempdir())
            if file=="screen.py":self.assertEqual(json.loads(raw),graph.CARGO)
            else:self.assertIn(b"usage:",raw)
        workflow=(HERE.parent.parent/".github/workflows/ci.yml").read_text()
        self.assertIn("path: enrolled\n          fetch-depth: 2",workflow)
        self.assertIn("max-parallel: 2",workflow)

    def test_pair(self):
        def role(p):
            a={arm:{name:{"instructions":12 if arm=="Foff" else 4} for name,b in s.w.PHASES} for arm in s.ORDERS[p]}
            return {"position":p,"verified":True,"run":200,"head":"abc","order":s.ORDERS[p],"boot":p,
                    "calibration":{"cpu":{"model":"X"},"pmu":"Y"},"selection":{"units":564},"all":a}
        x,y=role("01"),role("02");self.assertTrue(v.decide(x,y)["screen_pass"])
        y["all"]["Foff"]["return-A"]["instructions"]=8
        self.assertFalse(v.decide(x,y)["screen_pass"])
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"boot":"01"})
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"run":201})
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"calibration":{"cpu":{},"pmu":"other"}})
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"order":s.ORDERS["01"]})
        y["all"]["Foff"]["return-A"]["instructions"]=True
        with self.assertRaises(ValueError):v.decide(x,y)


if __name__=="__main__":
    unittest.main()
