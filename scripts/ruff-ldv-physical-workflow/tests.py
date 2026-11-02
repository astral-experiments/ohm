import copy
from fractions import Fraction
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
import zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import decision as d
import raw


def subjects():
    rows=[]
    ids={"P":"physical-parent","C":"physical-candidate"}
    admissions={"sha":"a"*40,"boots":{s:{"boot":str(uuid.UUID(int=i)),"roles":ids} for i,s in enumerate(("e2e","option"),200)}}
    for i in range(1,7):
        events={s:{r:{p:{"instructions":(132000 if r=="P" else 114000)+i*(100 if r=="P" else -3),
                 "enabled":50,"running":50,"status":0,"raw_sha256":"1"*64} for p in ("old","new","unchanged")} for r in ("P","C")}
                 for s in ("e2e","option")}
        rows.append({"slot":i,"qa":admissions["sha"],"run":874,"stage":"score","boot":str(uuid.UUID(int=i)),
            "assignment":copy.deepcopy(raw.assignment("score",i)),"roles":ids,"confirmation":raw.t.CONFIRM,"factory":raw.t.BUILD,
            "coverage":{"ordinary":28,"probes":24},"terminal_sha":str(i)*64,"events":events,"original_archive":{}})
    return rows,admissions


def archive(data):
    f=io.BytesIO()
    with zipfile.ZipFile(f,"w") as z:
        for n,b in data.items():
            z.writestr(n,b)
    return zipfile.ZipFile(io.BytesIO(f.getvalue()))


class Controls(unittest.TestCase):
    def test_all_six_favorable(self):
        rows,prior=subjects()
        v=d.analyze(rows,prior)
        self.assertTrue(v["primary_all_above_one"])
        self.assertEqual(v["restricted_one_sided_assignment_p"],[1,20])
        self.assertEqual(v["sign_probability_all_positive_if_independent"],[1,64])

    def test_null_and_adverse(self):
        rows,p=subjects()
        for row in rows:
            row["events"]["option"]["P"]=copy.deepcopy(row["events"]["option"]["C"])
        v=d.analyze(rows,p)
        self.assertFalse(v["primary_all_above_one"])
        self.assertEqual(v["restricted_one_sided_assignment_p"],[20,20])
        rows[0]["events"]["option"]["P"]["new"]["instructions"]=3000
        self.assertLess(d.analyze(rows,p)["median_interval"][0],1)

    def test_false_arm_or_repeated_boot(self):
        for k in ("slot","boot","terminal_sha"):
            rows,p=subjects()
            rows[1][k]=rows[0][k]
            with self.assertRaises(ValueError):
                d.analyze(rows,p)
        rows,p=subjects()
        rows[1]["assignment"]["compilers"]=list(reversed(rows[1]["assignment"]["compilers"]))
        with self.assertRaises(ValueError):
            d.analyze(rows,p)

    def test_unavailable_or_scaled_counter(self):
        for action in ("delete","scaled","negative"):
            rows,p=subjects()
            events=rows[0]["events"]["option"]["P"]
            if action=="delete":
                del events["new"]
            elif action=="scaled":
                events["new"]["running"]=17
            else:
                events["new"]["instructions"]=-4
            with self.assertRaises(ValueError):
                d.analyze(rows,p)

    def test_edit_plus_next(self):
        rows,_=subjects()
        g=rows[0]["events"]["option"]
        for r,a,b in (("P",111,30),("C",50,100)):
            g[r]["new"]["instructions"]=a
            g[r]["unchanged"]["instructions"]=b
        self.assertEqual(d.ratio_at(rows[0],"option","edit_plus_next"),Fraction(141,150))

    def test_unaltered_natives(self):
        blob=b"\x7fELF\x02abc"
        key=hashlib.sha256(blob).hexdigest()
        n="physical/native-bodies/"+key+".gz"
        with archive({n:gzip.compress(blob)}) as z:
            self.assertEqual(raw.verify_bytes(z)["native-bodies"],{key})
        for m in (blob[:-1],b"!<arch>\n"+blob):
            with archive({n:gzip.compress(m)}) as z,self.assertRaises(ValueError):
                raw.verify_bytes(z)

    def test_actual_exec_and_inheritance(self):
        key="x/trace/exec."
        f={key+"33":b'clone(child_stack=NULL, flags=1) = 34\nexecve("/count", ["/count"], []) = 0\n',
           key+"34":b'execve("/x/cargo", ["cargo", "+ohm", "build"], []) = 0\nexecve("/sdk/bin/cargo", ["/sdk/bin/cargo", "build"], []) = 0\n'}
        with archive(f) as z:
            parents,execs,exports=raw.fresh_trace(z,"x",list(f),"/sdk",{})
        self.assertEqual(exports,{"execs_with_export":0,"build_scripts":0})
        self.assertEqual(parents,{34:33})
        self.assertTrue(raw.descendant(34,33,parents))
        self.assertFalse(raw.descendant(33,34,parents))
        self.assertEqual(len(execs[34]),2)
        bad=f|{key+"34":f[key+"34"].replace(b'[]) = 0',b'["LD_PRELOAD=/tmp/lib.so"]) = 0')}
        with archive(bad) as z,self.assertRaises(ValueError):
            raw.fresh_trace(z,"x",list(bad),"/sdk",{})

    def test_signed_cargo_build_script_flags(self):
        sdk="/sdk"
        flags=raw.childenv.flags(sdk)
        key="CARGO_ENCODED_RUSTFLAGS"
        base={"CARGO_BUILD_BUILD_DIR":"/private/build"}
        generated=[(33,"/private/build/pkg/41/out/build_script_build"),(35,"/sdk/bin/rustc"),(37,"/usr/bin/cc")]
        graph={33:30,35:33,37:34,34:33}
        self.assertTrue(raw.childenv.check({key:flags},sdk))
        self.assertEqual(raw.childenv.owners(generated,graph,{30},base),{"execs_with_export":3,"build_scripts":1})
        for env,kit in (({key:flags},None),({key:flags+"x"},sdk),({key:flags[::-1]},sdk),({key:flags},"/different"),
                        ({"RUSTFLAGS":flags},sdk),({"CARGO_UNSTABLE_OHM_PROC_MACRO_TRUST":"all"},sdk)):
            with self.assertRaises(ValueError):
                raw.childenv.check(env,kit)
        for events,parents,actual,entry in ((generated,graph,{31},base),(generated,graph|{35:30},{30},base),
                (generated,graph,{30},base|{key:flags}),(generated,graph,{30},{"CARGO_BUILD_BUILD_DIR":"/other"}),
                (generated+[(30,"/sdk/bin/cargo")],graph,{30},base)):
            with self.assertRaises(ValueError):
                raw.childenv.owners(events,parents,actual,entry)

    def test_scope_of_the_source_compiler_namespace(self):
        import shards
        paths={"CARGO_BUILD_BUILD_DIR":"/work/build","CARGO_TARGET_DIR":"/work/target"}
        def rec(key):
            r="/work/build/debug/build/registries/v2-"+key+"/dep/aaa/out/libdep.rmeta"
            w="/work/target/debug/build/workspaces/123456789abcdef0/v2-"+key+"/owner/bbb/out"
            body={"suffix":"0","owner":w+"/build_script_build","argv":["rustc","--out-dir",w],
                  "stdin_sha256":"abc","owner_sha256":"def"}
            return {"root_argv":[["owner",["rustc","--extern","dep="+r,"--out-dir",w,"-L","dependency="+str(Path(r).parent),
                                          "-Z","temps-dir="+w+"/test.rlink-objects"]]],"roster":{"rustc":[],"linkers":[],"autocfg":[body]}}
        a,b=rec("0"*16),rec("1"*16)
        self.assertEqual(shards.comparable(a,paths),shards.comparable(b,paths))
        self.assertEqual(shards.project(a,paths)[2]["ids"],["v2-"+"0"*16])
        bad=copy.deepcopy(b); bad["roster"]["autocfg"][0]["stdin_sha256"]="changed"
        self.assertNotEqual(shards.comparable(a,paths),shards.comparable(bad,paths))
        bad=copy.deepcopy(b); bad["root_argv"][0][1][2]=bad["root_argv"][0][1][2].replace("libdep","libother")
        self.assertNotEqual(shards.comparable(a,paths),shards.comparable(bad,paths))
        for rewrite in (lambda a:a.replace("/work/build/","/external/"),lambda a:a.replace("registries/","other/"),
                        lambda a:a.replace("dep/aaa","../aaa")):
            bad=copy.deepcopy(b); bad["root_argv"][0][1][2]=rewrite(bad["root_argv"][0][1][2])
            with self.assertRaises(ValueError): shards.project(bad,paths)
        for change in (lambda args:args.__setitem__(1,"--cfg"),lambda args:args.__setitem__(4,args[4].replace("1"*16,"2"*16))):
            bad=copy.deepcopy(b); change(bad["root_argv"][0][1])
            with self.assertRaises(ValueError): shards.project(bad,paths)

    def test_sort_out_the_pmu_proxy(self):
        ordinary=["cargo","+ohm","build"]
        a=["/count","/m/pmu.json","/proxy",*ordinary]
        task={"actual":["strace","--",*a],"ordinary":ordinary}
        pm={"pid":34,"instructions":312,"enabled":1,"running":1,"status":0}
        b=json.dumps(pm).encode();key=raw.digest(b)
        data={"x/pmu.json":b}
        procs={33:[("/count",a)],34:[("/proxy",ordinary),("/sdk/bin/cargo",["/sdk/bin/cargo","build"])],
                  35:[("/cc",["cc"])]}
        for parents,okay in (({35:34,34:33},True),({35:10,34:33},False),({35:34},False)):
            with archive(data) as z:
                if okay:
                    self.assertEqual(raw.genuine_counter(z,"x",task,parents,procs,"/sdk","new",key)["pid"],34)
                else:
                    with self.assertRaises(ValueError):
                        raw.genuine_counter(z,"x",task,parents,procs,"/sdk","new",key)

    def test_every_real_load(self):
        info={"sha256":"f"*64,"device":[1,1],"inode":20,"build_id":None,"exec_loads":[]}
        values=[]
        for i in (1,2):
            segment={"offset":i*4096,"vaddr":i*4096,"size":63,"sha256":str(i)*64}
            info["exec_loads"].append(segment)
            values.append({"segment":segment,"prot":5,"file_sha":info["sha256"],"fd_inode":[os.makedev(1,1),20],
                   "address":segment["vaddr"]+4096,"returned_address":segment["vaddr"]+4096,"length":4096,"actual_rx_sha256":segment["sha256"]})
        live={"segments":values,"file_sha":info["sha256"],"fd_inode":[os.makedev(1,1),20],"mapped_build_id":None}
        self.assertEqual(raw.t.live_input(live,info),4096)
        for field,value in (("segments",values[:1]),("mapped_build_id",[10,"abc"]),("fd_inode",[22,20])):
            with self.assertRaises(ValueError):
                raw.t.live_input(live|{field:value},info)
        changed=copy.deepcopy(live)
        changed["segments"][0]["actual_rx_sha256"]="a"*64
        with self.assertRaises(ValueError):
            raw.t.live_input(changed,info)


    def test_link_only_positional_exact_outfile(self):
        import shards
        root="/build/target";mem="/build/shared"
        dst=root+"/debug/build/workspaces/123456789abcdef0/v2-9999888877776666/pkg/2513aa8180818188/out"
        out=dst+"/e2e-2513aa8180818188.rlink"
        args=["rustc","--crate-name","e2e",out,"--out-dir",dst,"-C","extra-filename=-2513aa8180818188","-Z","link-only"]
        env={"CARGO_TARGET_DIR":root,"CARGO_BUILD_BUILD_DIR":mem}
        accepted=shards.argv(args,env,set())
        self.assertEqual(accepted[3],out.replace("v2-9999888877776666",shards.PLACEHOLDER))
        for i,value in ((3,out+"x"),(2,"other"),(9,"ordinary"),(7,"extra-filename=-0000000000000000")):
            bad=args.copy();bad[i]=value
            with self.assertRaises(ValueError):
                shards.argv(bad,env,set())

    def test_reject_substituted_documentation(self):
        import doc_support
        o=json.loads((doc_support.t.STAGE/"documentation-originals.json").read_bytes())["P"]
        driver,=[n for n in o["files"] if n.startswith("lib/librustc_driver-")]
        row={"source":o["commit"],"tree":o["compiler_tree"],"driver":[driver,o["files"][driver][0]],
             "all_previous_files":63,"before_differences":{},"after_differences":{},"original_physical_kit_untouched":True,
             "native_compile_verified":True,"stage0_matches_original":True,"stage0":[o["stage0_rustc"],o["stage0_cargo"]],
             "html_sha256":"1"*64,"rustdoc":["2"*64,7032,0o755],"actual_loader_init_paths":["/lib/driver"]}
        self.assertEqual(doc_support.qualification("P",row,o),("2"*64,7032))
        for change in ({"driver":[driver,"3"*64]},{"before_differences":{"bin/rustc":["4"*64,"5"*64]}},
                       {"rustdoc":["2"*64,7032,0o644]},{"stage0_matches_original":False},{"all_previous_files":62}):
            with self.assertRaises(ValueError):
                doc_support.qualification("P",row|change,o)


if __name__=="__main__":
    unittest.main()
