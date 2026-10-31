import copy
import base64
import uuid
import gzip
import hashlib
import json
import subprocess
import zipfile
from unittest.mock import patch,Mock
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
import boot_identity as boots


def authority():
    def fake_uuid(i):return str(uuid.UUID(int=i))
    r={p:{"boot":fake_uuid(1000+i),"job":i,"artifact":100+i,"bytes":200,"archive_sha256":"a"*64,
        "identity_sha256":{n:"b"*64 for n in ("host.json","enrollment.json","meter-ready.json")}} for i,p in enumerate(boots.POSITIONS,1)}
    return {"repository":boots.REPO,"run":boots.RUN,"head":boots.HEAD,"branch":boots.BRANCH,"attempt":1,"hosts":r}


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
           "spans":[{"is_primary":True,"file_name":q.PARSER,"text":[{"text":"const ohm_branch_switch_invalid: () = 1u32;"}]}]}}
        q.error_check([p],Path("/repo"))
        with self.assertRaises(ValueError):q.error_check([p,p],Path("/repo"))
        with self.assertRaises(ValueError):q.error_check([p|{"target":{"name":"unrelated"}}],Path("/repo"))
        bad=copy.deepcopy(p);bad["message"]["spans"][0]["file_name"]="other/src/lib.rs"
        with self.assertRaises(ValueError):q.error_check([bad],Path("/repo"))
        summary={"level":"error","message":"aborting due to 1 previous error","spans":[],"children":[]}
        q.type_error([p["message"],summary],"ohm_branch_switch_invalid",{q.PARSER})
        with self.assertRaises(ValueError):q.type_error([p["message"],summary|{"message":"other fatal diagnostic"}],"ohm_branch_switch_invalid",{q.PARSER})
        with self.assertRaises(ValueError):q.type_error([p["message"]],"ohm_branch_switch_invalid",{"wrong/path.rs"})
        for dirty in (True,False):
            row={"parser_sha256":q.PARSER_BYTES[dirty],"status":"M "+q.PARSER if dirty else ""};q.source_check(row,dirty)
            with self.assertRaises(ValueError):q.source_check(row|{"parser_sha256":q.PARSER_BYTES[not dirty]},dirty)

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
        jobs={"total_count":2,"jobs":[dict(id=i,name=originals.LABEL+p,runner_name="fresh-"+p,head_sha=run["head_sha"],run_id=500,run_attempt=1,status="completed",conclusion="success") for i,p in enumerate(s.ORDERS,10)]}
        art={"total_count":2,"artifacts":[dict(id=i,name=originals.PREFIX+p,workflow_run={"id":500,"head_sha":run["head_sha"]},expired=False,size_in_bytes=150,digest="sha256:"+"2"*64) for i,p in enumerate(s.ORDERS,20)]}
        self.assertEqual(set(originals.bind(run,jobs,art,500,"a"*40)),set(s.ORDERS))
        for rr,jj,aa in [(run|{"run_attempt":2},jobs,art),(run|{"conclusion":"failure"},jobs,art),(run,jobs|{"total_count":3},art),
                          (run,jobs,art|{"artifacts":2*[art["artifacts"][0]]})]:
            with self.assertRaises(ValueError): originals.bind(rr,jj,aa,500,"a"*40)
        for old in s.PREVIOUS_RUNNERS | {"fresh-02"}:
            reused=copy.deepcopy(jobs);reused["jobs"][0]["runner_name"]=old
            with self.assertRaises(ValueError):originals.bind(run,reused,art,500,"a"*40)
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
        enrolled=workflow.split("path: enrolled\n",1)[1].split("      - ",1)[0]
        self.assertIn("            .github/workflows",enrolled.splitlines())
        self.assertIn("max-parallel: 2",workflow)

    def test_boot_provenance_and_competing_enrollments(self):
        historical=boots.prior();self.assertEqual(len(historical),66)
        rs={str(uuid.UUID(int=i)) for i in (1,2)};ledger=authority();self.assertEqual(len(boots.validate(ledger,rs)),12)
        new=set(json.loads((HERE/"boot-provenance.json").read_bytes())["added"])
        for b in new|{ledger["hosts"]["12"]["boot"]}:
            with self.assertRaises(ValueError):boots.validate(ledger,{min(rs),b})
        for key,val in (("run",999),("attempt",2),("head","x"*40),("hosts",{k:v for k,v in ledger["hosts"].items() if k!="12"})):
            with self.assertRaises(ValueError):boots.validate(ledger|{key:val},rs)
        ix=copy.deepcopy(ledger);ix["hosts"]["12"]["artifact"]=ix["hosts"]["01"]["artifact"]
        with self.assertRaises(ValueError):boots.validate(ix,rs)

    def test_boot_only_reads_no_competing_result(self):
        p="01";b=authority()['hosts'][p]['boot'];en={'run':boots.RUN,'head':boots.HEAD,'attempt':1,'position':p,'boot':b}
        with tempfile.TemporaryDirectory() as td:
            z=Path(td)/'E.zip'
            with zipfile.ZipFile(z,'w') as w:
                for name,vv in [('enrollment.json',en),('host.json',{'raw_system':{'/proc/sys/kernel/random/boot_id':b}}),('meter-ready.json',{'boot':b})]:
                    w.writestr(name,json.dumps(vv))
                w.writestr('complete.json',b'not an outcome field');w.writestr('clock.json',b'never open')
            archive={'id':28,'size_in_bytes':z.stat().st_size,'digest':'sha256:'+q.file_sha(z)}
            original_read=zipfile.ZipFile.read
            def identity_only(obj,name,*args):
                self.assertIn(name,('enrollment.json','meter-ready.json','host.json'));return original_read(obj,name,*args)
            with patch.object(zipfile.ZipFile,'read',identity_only):
                self.assertEqual(boots.extract(z,{'id':29},archive,p)['boot'],b)
                with self.assertRaises(ValueError):boots.extract(z,{'id':29},archive,'12')
                with self.assertRaises(ValueError):boots.extract(z,{'id':29},archive|{'digest':'sha256:'+'0'*64},p)

    def test_full_native_images_and_effective_memory(self):
        sdk=Path('/sdk');proxy=Path('/home/.cargo/bin/rustup');wild='lib/dist/wild/ld.bfd';d=['bin/cargo','bin/rustc',wild]
        e=[(1,str(sdk/d[0]),['cargo','check']),(2,str(sdk/d[1]),['rustc','--crate-name','ruff_dev']),
           (3,str(sdk/d[1]),['rustc','--crate-name','dep','-Zlink-only']),(4,str(sdk/wild),['ld','-o','native']),
           (5,str(sdk/wild),['ld','--version']),(6,'/usr/bin/ld',['ld','-v']),(7,'random-tool',['tool'])]
        paths={str(sdk/f):[1,i] for i,f in enumerate(d,100)}|{str(proxy):[1,50],'/usr/bin/ld':[1,60],'random-tool':None}
        tools={f:['0'*64,*paths[str(sdk/f)]] for f in d};pr={'paths':{str(proxy):[1,50]},'sha256':'1'*64}
        rek=s.native.read(e,paths,sdk,tools,wild,proxy,pr)
        self.assertEqual(s.native.counts(rek),{'full':1,'link_only':1,'wild':1,'images':7});self.assertEqual(len(rek['wild_queries']),1);self.assertEqual(len(rek['other_linkers']),1)
        for key in ('rustcs','wild_processes','other_linkers','wild_queries'):
            wrong=rek|{key:rek[key][1:]};self.assertNotEqual(wrong,s.native.read(e,paths,sdk,tools,wild,proxy,pr))
        with self.assertRaises(ValueError):s.native.read(e,{k:v for k,v in paths.items() if k!='random-tool'},sdk,tools,wild,proxy,pr)
        level={'host_memory':100,'cgroup_remaining':[17],'available_memory':17,'cgroup_leaf':'/group','cgroup_levels':[{'group':'/group','max':20,'current':3},{'group':'/','max':'unlimited-unified-root','current':None}]}
        self.assertTrue(guard.checked(level));self.assertFalse(guard.checked(level|{'available_memory':100}));self.assertFalse(guard.checked(level|{'cgroup_levels':level['cgroup_levels'][:1]}))

    def test_broken_runtime_guard_stops_only_owned_group(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"ohm-branch-object-qa";root.mkdir();(root/'logs').mkdir()
            child=Mock();child.pid=998877;child.poll.return_value=None;child.wait.side_effect=[subprocess.TimeoutExpired('owned',3),-9]
            env=os.environ|{'RUNNER_TEMP':td};sample={'host_memory':40<<30,'available_memory':40<<30,'work_free':24<<30,'durable_free':64<<30,
                'cgroup_remaining':[],'cgroup_leaf':'/','cgroup_levels':[{'group':'/','max':'unlimited-unified-root','current':None}]}
            with patch.dict(os.environ,env),patch.object(guard,'resources',side_effect=[sample,OSError('lost live memory controller')]), \
                 patch.object(guard.subprocess,'Popen',return_value=child) as launch,patch.object(guard.os,'killpg') as stop:
                with self.assertRaises(OSError):guard.main()
                self.assertTrue(launch.call_args.kwargs['start_new_session']);stop.assert_called_once_with(child.pid,guard.signal.SIGKILL);self.assertEqual(child.wait.call_count,2)

    def test_genuine_metadata_listings(self):
        c=q.read_gz(HERE/"native-listing-controls.json.gz");self.assertEqual(c["client_codes"]["renamed_reexport"],0)
        for n,record in c["listings"].items():
            b=base64.b64decode(record['bytes'] or '');cert=[len(b),hashlib.sha256(b).hexdigest()];out=record['stdout'].encode();err=record['stderr'].encode()
            if n=='correct':
                self.assertEqual(q.listing('ruff_linter','libruff_linter.rmeta',cert,out,err,record['status'])['status'],0)
                for path,body,stderr,code in [('libruff_linter.rmeta',out,b'warning',0),('libruff_linter-0123456789abcdef.rmeta',out,b'',0),
                                               ('libruff_linter.rmeta',out[:35],b'',0),('libruff_linter.rmeta',out,b'',1)]:
                    with self.assertRaises(ValueError):q.listing('ruff_linter',path,cert,body,stderr,code)
            else:
                with self.assertRaises(ValueError):q.listing('ruff_linter','libruff_linter.rmeta',cert,out,err,record['status'])
        self.assertIn('ruff_linter',c['listings']['reexport']['stdout']);self.assertIn('name decoy',c['listings']['reexport']['stdout'])

    def test_missing_provider_or_listing(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);owners={n:str(d/'target'/('lib'+n+'-0123456789abcdef.rmeta')) for n in graph.PROVIDERS}
            with self.assertRaises(ValueError):v.reopen_listings(d,owners,{n:{} for n in owners},d,Path('/unreachable/rustc'))
            with self.assertRaises(ValueError):v.provider_records({'owner':{'providers':owners},'files':{},'providers':{}},[],d,d)
            for n in owners:(d/(n+'.metadata-listing.gz')).touch()
            with self.assertRaises(ValueError):v.reopen_listings(d,owners,{n:{} for n in owners},d,Path('/unreachable/rustc'))

    def test_pair(self):
        def role(p):
            a={arm:{name:{"instructions":12 if arm=="Foff" else 4} for name,b in s.w.PHASES} for arm in s.ORDERS[p]}
            return {"position":p,"verified":True,"run":200,"head":"abc","order":s.ORDERS[p],"boot":str(uuid.UUID(int=int(p))),
                    "calibration":{"cpu":{"model":"X"},"pmu":"Y"},"selection":{"units":564},"all":a}
        x,y=role("01"),role("02");self.assertTrue(v.decide(x,y,authority())["screen_pass"])
        y["all"]["Foff"]["return-A"]["instructions"]=8
        self.assertFalse(v.decide(x,y,authority())["screen_pass"])
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"boot":x["boot"]},authority())
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"run":201},authority())
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"calibration":{"cpu":{},"pmu":"other"}},authority())
        with self.assertRaises(ValueError):v.decide(x,role("02")|{"order":s.ORDERS["01"]},authority())
        y["all"]["Foff"]["return-A"]["instructions"]=True
        with self.assertRaises(ValueError):v.decide(x,y,authority())


if __name__=="__main__":
    unittest.main()
