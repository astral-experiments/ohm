"""Small offline tests. No compiler, working tree, ELF archive, or network writes."""
import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import aggregate as a
import durable
import evidence as e
import packets as p

def sample():
    title="Ruff upstream monomorphization experiment "+p.HEAD
    run=dict(head_sha=p.HEAD,head_branch=p.BRANCH,run_attempt=1,event="workflow_dispatch",status="completed",
             path=".github/workflows/ci.yml",head_repository={"full_name":p.REPO},repository={"full_name":p.REPO},
             name=title,display_title=title,id=123,conclusion="success")
    jobs=[dict(name=f"ordinary ({i})",run_id=123,head_sha=p.HEAD,status="completed",labels=[p.LABEL],id=800+i,
               conclusion="success",runner_id=i+1,runner_name="runner-"+str(i)) for i in range(6)]
    artifacts=[dict(name=p.NAME+str(i),workflow_run={"id":123,"head_sha":p.HEAD},expired=False,id=900+i,
                    size_in_bytes=123,digest="sha256:"+str(i)*64) for i in range(6)]
    return run,dict(total_count=6,jobs=jobs),dict(total_count=6,artifacts=artifacts)

class Receiver(unittest.TestCase):
    def test_portable_clock_record(self):
        reg={"shared":239,"private":35,"roster_sha256":"1543d3b84184059d74c9a48c65375d85d16013a357fd4f92316544876d545be1"}
        src=[dict(A="b5dba861cc38e3f7fb4524c9ceba3e01a474ea13",B="7b13f01ba1569887a25670820764b24c206da8e5")]
        q=dict(schema="normal-ruff-mono-owner-clocks-v1",study=p.SOURCE_RUN,head=p.HEAD,qualifier=p.QUALIFIER,
               factory=p.FACTORY,compiler_commits=e.SOURCE,registry=reg,ruff=src,edited_improved_on_all_six=True,
               ranks=[],cross_boot_native={},whole_cargo={v:a.distribution([(100,80)]*6,True) for v in e.PHASES})
        runs,jobs,artifacts=sample()
        for i in range(6):
            arm={}
            for role in "PC":
                clock=dict(code=0,event_errno=0,instructions=100 if role=="P" else 80,enabled=1,running=1,start=1,stop=2)
                arm[role]=dict(clock={v:dict(clock) for v in e.PHASES},
                               whole={v:dict(reader="d",cli=v if v in "AB" else "A") for v in (*e.PHASES,"repair")})
            native={rev:dict(reader="d",refs={"P":rev,"C":rev}) for rev in "AB"}
            spec=dict(name=p.NAME+str(i),id=200+i,digest="sha256:"+str(i)*64)
            q["ranks"].append(dict(rank=i,order=("PC","CP")[i%2],boot=str(i),job=jobs["jobs"][i],artifact=spec,
               source_archive_url=f"https://github.com/{p.REPO}/actions/runs/{p.SOURCE_RUN}/artifacts/{200+i}",arms=arm,native=native))
            if i:
                for rev in "AB":q["cross_boot_native"][f"0-vs-{i}-{rev}"]=dict(shas=[rev,rev],revision=rev,proof={"identical":True})
        self.assertEqual(durable.verify(q)["inference"]["two_sided_exact_sign_p"],"1/32")
        q["ranks"][0]["arms"]["P"]["clock"]["A"]["instructions"]+=2
        with self.assertRaisesRegex(ValueError,"raw-clock"):durable.verify(q)

    def test_simulated_complete_run_and_failures(self):
        def fake_rank(root,rank_id,out,modules,registration):
            out.mkdir(parents=True,exist_ok=True)
            row={"rank":rank_id,"order":("PC","CP")[rank_id%2],"identity":{"boot":str(rank_id)},"arms":{}}
            if scenario=="duplicate" and rank_id==5:row["identity"]["boot"]="0"
            for role in "PC":
                count=100 if role=="P" else (101 if rank_id==3 else 75)
                phases={v:{"clock":{"instructions":count,"user_us":3,"system_us":1,"start":100,"stop":200},
                           "storage":{"bytes":100,"files":2}} for v in (*e.PHASES,"repair")}
                named={o:{"donor":["common","gained"] if role=="C" else ["common"],"changed":["real"]} for o in e.OWNERS}
                graphs={o:{v:{"dep_graph":{"bytes":99,"nodes":10,"edges":25}} for v in "AB"} for o in e.OWNERS}
                row["arms"][role]=dict(phases=phases,named=named,graphs=graphs)
            return row
        for scenario in ("complete","duplicate","missing","bad-native"):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory(dir=HERE) as temp:
                d=Path(temp);out=d/"results";work=d/"scratch";r,j,f=sample()
                if scenario=="missing":f["artifacts"].pop();f["total_count"]-=1
                enroll=p.enrollment(r,j,f)
                def fake_cross(left,right,rev,m,w):
                    if scenario=="bad-native" and right.name=="rank-1" and rev=="B":raise ValueError("different ELF")
                    return {"identical":True}
                with (mock.patch.dict(e.os.environ,GITHUB_ACTIONS="true"),
                      mock.patch.object(sys,"argv",["receiver","123","--producer",str(d),"--work",str(work),"--out",str(out)]),
                      mock.patch.object(e,"readers",return_value=({},{"source":[]})),
                      mock.patch.object(p,"register",return_value=enroll),mock.patch.object(p,"bind_job",return_value={}),
                      mock.patch.object(p,"archive",return_value=d/"unused.zip"),mock.patch.object(p,"unpack"),
                      mock.patch.object(a,"free_space"),mock.patch.object(e,"rank",side_effect=fake_rank),
                      mock.patch.object(e,"cross",side_effect=fake_cross) as cross,
                      contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO())):
                    status=a.main()
                data=p.load(out/"summary.json")
                self.assertEqual((status,data["admitted"]),(0,True) if scenario=="complete" else (1,False))
                self.assertEqual(len(data["phase"]["A"]["pairs"]),5 if scenario=="missing" else 6)
                self.assertEqual(cross.call_count,8 if scenario=="missing" else 10)
                self.assertEqual(data["phase"]["A"]["pairs"][3]["reduction"]["fraction"],"-1/100")
                if scenario=="complete":
                    self.assertIs(data["edited_improved_on_all_six"],False)
                    self.assertEqual(data["phase"]["A"]["inference"]["two_sided_exact_sign_p"],"7/32")
                else:self.assertIsNone(data["phase"]["A"]["inference"])

    def test_authenticated_roster(self):
        r,j,f=sample()
        enrolled=p.enrollment(r,j,f)
        self.assertEqual(len(enrolled["artifacts"]),6)
        for key,value in (("run_attempt",2),("head_sha","a"*40),("status","in_progress"),("display_title","another study")):
            with self.subTest(key=key),self.assertRaises(ValueError): p.enrollment({**r,key:value},j,f)
        for rows,field,k,value in ((j,"jobs","name","ordinary (0)"),(j,"jobs","id",800),
                                   (f,"artifacts","name",p.NAME+"0"),(f,"artifacts","id",900),
                                   (f,"artifacts","expired",True),(f,"artifacts","digest","fake")):
            bad=copy.deepcopy(rows);bad[field][1][k]=value
            with self.subTest(k=k),self.assertRaises(ValueError):
                p.enrollment(r,bad if field=="jobs" else j,bad if field=="artifacts" else f)
        self.assertEqual(len(p.enrollment(r,j,dict(total_count=5,artifacts=f["artifacts"][:-1]))["artifacts"]),5)

    def test_actual_upload_output(self):
        # Literal upload logging protocol seen in terminal pilot job 125219703436.
        rid=41428147193;aid=13132624747;sha="a5404eb4945346f5f1dbd7c4221daa66825fa43c025c2dcbc6ba79af74558058"
        name="ruff-upstream-mono-ruff";size=154071274
        raw="".join("2026-11-02T10:38:37.3476858Z "+x+"\n" for x in (
          "SHA256 digest of uploaded artifact is "+sha,f"Artifact {name} successfully finalized. Artifact ID {aid}",
          f"Artifact {name} has been successfully uploaded! Final size is {size} bytes. Artifact ID is {aid}",
          f"Artifact download URL: https://github.com/{p.REPO}/actions/runs/{rid}/artifacts/{aid}")).encode()
        spec=dict(id=aid,name=name,bytes=size,digest="sha256:"+sha)
        self.assertEqual(p.upload_proof(raw,rid,{"id":125219703436},spec)["artifact"],aid)
        for k,v in (("name",name+"-other"),("id",aid+1),("bytes",size+2),("digest","sha256:"+"0"*64)):
            with self.assertRaises(ValueError):p.upload_proof(raw,rid,{"id":9},{**spec,k:v})

    def test_statistics(self):
        for pairs,m,n,pval in (([(200,150)]*6,"1/4",6,"1/32"),
                               ([(150,200)]*6,"-1/3",0,"1/32"),
                               ([(10,9)]*5+[(10,11)],"1/10",5,"7/32"),
                               ([(10,9)]*3+[(10,11)]*3,"0",3,"1"),
                               ([(10,10)]*6,"0",0,"1"), ([(10,9)]*4+[(10,10)]*2,"1/10",4,"1/8")):
            got=a.distribution(pairs,True)
            self.assertEqual(got["median"]["fraction"],m)
            self.assertEqual(got["inference"]["positive"],n)
            self.assertEqual(got["inference"]["two_sided_exact_sign_p"],pval)
            self.assertEqual(got["inference"]["median_interval"]["coverage"],"31/32")
            self.assertEqual(len(got["pairs"]),6)
        self.assertIsNone(a.distribution([(10,11)]*5,False)["inference"])
        with self.assertRaises(ValueError):a.distribution([(1,1)]*5,True)

    def test_archives(self):
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            root=Path(tmp); arc=root/"r.zip"
            with zipfile.ZipFile(arc,"w") as z:z.writestr("a/b",b"small")
            p.unpack(arc,root/"good")
            self.assertEqual((root/"good/a/b").read_bytes(),b"small")
            spec={"name":"r","id":777,"bytes":arc.stat().st_size,"digest":"sha256:"+p.digest(arc)}
            self.assertEqual(p.archive(spec,root),arc)
            with self.assertRaises(ValueError):p.archive({**spec,"digest":"sha256:"+"0"*64},root)
            for i,name in enumerate(("../escape","/abs","x\\y","sym")):
                with zipfile.ZipFile(arc,"w") as z:
                    info=zipfile.ZipInfo(name)
                    if name=="sym": info.external_attr=(stat.S_IFLNK|0o777)<<16
                    z.writestr(info,"elsewhere")
                with self.assertRaises(ValueError):p.unpack(arc,root/("bad-"+str(i)))

    def test_recorded_physical_rosters(self):
        # The earlier compact-layout study has a separately admitted, small range
        # capture. Use original ledgers only if available locally; never fetch them.
        root=HERE.parents[1]/"rustc-owner-scout/bucket-ruff-named-01/raw"
        if not root.exists():self.skipTest("optional historical ledgers unavailable")
        for index in (0,1):
            for role,expected in (("P",(83,12)),("C",(122,15))):
                raw=p.load(root/f"{index}-{role}"/"objects.json")
                named,graphs=e.donors(raw,role)
                self.assertEqual(tuple(len(named[o]["donor"]) for o in e.OWNERS),expected)
                self.assertEqual(tuple(sum(map(len,named[o].values())) for o in e.OWNERS),(124,256))
                self.assertTrue(graphs["ruff_workspace"]["A"]["dep_graph"]["edges"])
                item=next(iter(raw["ruff_workspace"]["objects"].values()));item["same_inode"]=not item["same_inode"]
                with self.assertRaises(ValueError):e.donors(raw,role)

    def test_real_factory_map_and_reader(self):
        root=HERE.parent/"bucket-full-factory-receipts.zip"
        producer=Path("/home/dev-user/code/oss/ohm-package-qa-upstream-mono-ruff-20261102")
        if not (root.exists() and producer.exists()):self.skipTest("optional exact factory unavailable")
        _,registration=e.readers(producer)
        self.assertEqual(p.digest(root),registration["factory_artifacts"]["ohm-upstream-mono-owner-stage1-receipts"][2][7:])
        with zipfile.ZipFile(root) as z:
            install=json.loads(z.read("rustcs.json"))
            for role,label in (("P","normal"),("C","defer")):
                raw=json.loads(z.read(role+".json"));self.assertEqual(raw["commit"],e.SOURCE[role])
                files=install["arms"][label]["files"]; signed=set(files)-set(raw["files"])
                self.assertEqual(signed,{"bin/cargo","lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"})
                self.assertEqual({k:files[k] for k in raw["files"]},{k:v[0] for k,v in raw["files"].items()})
                self.assertIn("bin/rustdoc",files)
            archive_sha=z.read("archive.sha256").decode().split()[0]
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            d=Path(temp)
            meta={"run":p.FACTORY,"head":registration["factory_head"],"artifacts":{
                k:dict(id=v[0],bytes=v[1],digest=v[2]) for k,v in registration["factory_artifacts"].items()},
                "archive_sha256":archive_sha}
            p.save(d/"factory.json",meta);p.save(d/"compiler-installations.json",install)
            cpu={"boot":"98198072-eb06-4f3a-9a77-8e486fa7acfc","cpus":[0,2,4,6],"cpuinfo":"synthetic"}
            p.save(d/"cpu.json",cpu)
            self.assertEqual(e.provenance(d,registration)["boot"],cpu["boot"])
            install["arms"]["defer"]["files"]["bin/rustdoc"]="0"*64;p.save(d/"compiler-installations.json",install)
            with self.assertRaisesRegex(ValueError,"compiler map"):e.provenance(d,registration)

    def test_cross_parent_uses_observed_dirs(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            d=Path(temp); roots=[d/"0",d/"1"]
            text=[b"left",b"right"];sha=[hashlib.sha256(v).hexdigest() for v in text]
            for root,value,h in zip(roots,text,sha):
                (root/"reference-bodies").mkdir(parents=True)
                (root/"reference-bodies"/(h+".zst")).write_bytes(value)
            def reference(root,role,rev):
                i=roots.index(root);self.assertEqual((role,rev),("P","A"))
                return {"cli":{"whole":sha[i],"size":len(text[i])},"reader":{"whole":"abc"},"typed":"same"}, "roster",b"/j"+str(i).encode()
            def compare(l,r,old,new):
                self.assertEqual([l.read_bytes(),r.read_bytes()],text);self.assertEqual((old,new),(b"/j0",b"/j1"))
                return {"qualified":True}
            class Fam:pass
            class Native:pass
            Fam.reference=staticmethod(reference);Native.compare=staticmethod(compare)
            def pretend_zstd(argv,stdout,check):stdout.write(Path(argv[-1]).read_bytes())
            with mock.patch.object(e.subprocess,"run",pretend_zstd):
                self.assertEqual(e.cross(*roots,"A",dict(live_family=Fam,native_reference=Native),d)["proof"],{"qualified":True})
                self.assertEqual(e.cross(roots[0],roots[0],"A",dict(live_family=Fam,native_reference=Native),d)["proof"],{"identical":True})

if __name__=="__main__":
    unittest.main(verbosity=2)
