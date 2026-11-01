"""Exercise the original 50 argv pairs, physical process lineage, recipe joins and admission refusals."""
import base64
import copy
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import linux_common as lc
from linux_controls import Controls as OriginalControls
import rc22_sdk as sdk
import rc22_trace as trace
import rc22_units as units
from packages import save, need

def historical():
    old = OriginalControls()
    old.setUp()
    observed = lc.native(old.rows, old.tools, old.alias)
    indexed = {r["old_unchanged_pid"]: k for k, r in lc.SUBJECTS.items()}
    returned, bound = {}, []
    for link in observed["wild"]:
        ident = indexed[link["pid"]]
        assert Path(link["output"]).name == lc.SUBJECTS[ident]["physical_basename"]
        returned[ident] = {"target": {"name": ident.split("|")[1], "src_path": "/ruff/"+ident.split("|")[-1]},
                           "executable": link["output"], "fresh":False}
        bound.append(link | {"unit": ident})
    row, = (r for r in old.q["rows"] if r[2] == "full")
    _, argv = lc.event(row[1].encode())
    source, = [s for s in argv if s.endswith(".rs")]
    ron = {"package_id":"registry+https://github.com/rust-lang/crates.io-index#ron@0.12.0",
           "target":{"name":"ron","kind":["lib"],"src_path":source}, "filenames":[str(units.resolver(argv))],"fresh":False}
    return [*returned.values(), ron], returned, old.rows, observed, bound, "/ruff", {r["pid"]:"0" for r in observed["compilers"]}

def encode(rows):
    return [str(pid).encode() + b"\t" + base64.b64encode(raw) for pid, raw in rows.items()]

class Controls(unittest.TestCase):
    def test_original_50_pairs_and_ron(self):
        args = historical()
        result = units.group_by_product(*args)
        self.assertEqual([r["mode"] for k,r in result.items() if k in lc.SUBJECTS], ["link-only"]*50)
        custom = {k for k, r in result.items() if k in lc.SUBJECTS and not r["rustc"][0]["test_harness"]}
        self.assertEqual({k.split("|")[-1] for k in custom},
                         {"crates/ruff_python_formatter/tests/fixtures.rs", "crates/ruff_python_parser/tests/fixtures.rs",
                          "crates/ruff_mdtest/tests/mdtest.rs", "crates/ty_python_semantic/tests/mdtest.rs"})
        self.assertEqual(result[units.RON]["mode"], "full")
        self.assertFalse(result[units.RON]["rustc"][0]["test_harness"])
        for k in lc.SUBJECTS:
            self.assertEqual(result[k]["wild"][0]["pid"], lc.SUBJECTS[k]["old_unchanged_pid"])

    def test_absent_changed_and_foreign_process(self):
        a, returned, rows, actual, bound, cwd, exits = historical()
        with self.assertRaisesRegex(RuntimeError, "owner mismatch"):
            units.group_by_product(a, returned, rows, actual, bound[1:], cwd, exits)
        item = next(iter(returned))
        returned[item]["fresh"] = True
        with self.assertRaisesRegex(RuntimeError, "fresh Cargo"):
            units.group_by_product(a, returned, rows, actual, bound, cwd, exits)
        returned[item]["fresh"] = False
        by_pid = {r["pid"]:r for r in actual["compilers"]}
        bad = copy.deepcopy(rows)
        pid, line = next(r for r in bad if r[0] in by_pid and '.rlink"' in r[1])
        path, argv = lc.event(line.encode())
        recipe, = [v for v in argv if v.endswith(".rlink")]
        replacement = line.replace(recipe, "/foreign/input.rlink", 1)
        next(row for row in bad if row[0] == pid)[1] = replacement
        by_pid[pid]["argv_sha256"] = lc.digest(replacement.encode())
        with self.assertRaisesRegex(RuntimeError, "own recipe"):
            units.group_by_product(a, returned, bad, actual, bound, cwd, exits)

    def test_complete_lineage_and_negative_interventions(self):
        child = b'+++ exited with 0 +++\n'
        parent = b'clone(child_stack=NULL, flags=SIGCHLD) = 20\n' + child
        raw = {10:parent,20:child}
        _, parents, leader, exits = trace.read(encode(raw))
        traces = {"one":{"rustc":[{"pid":10}],"wild":[{"pid":20}]}}
        self.assertEqual(trace.owners(traces, parents, leader, [{"pid":10}], exits)["one"][0]["chain"], [20,10])
        with self.assertRaises(RuntimeError):
            trace.owners(traces, parents, leader, [{"pid":10},{"pid":20}], exits)
        for changed in ({10:parent},{20:child,10:child},{10:parent,20:b""},
                        {10:parent.replace(b"SIGCHLD",b"CLONE_UNTRACED|SIGCHLD"),20:child},
                        {10:parent.replace(b") = 20",b" <unfinished ...>"),20:child},
                        {10:b'execveat(5, "", ["true"], NULL, AT_EMPTY_PATH) = 0\n'+child}):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                trace.read(encode(changed))

    def test_fingerprint_sources_and_mode(self):
        src = "/ruff/crates/ruff/src/main.rs"
        key = "crates/ruff|ruff|bin|true|crates/ruff/src/main.rs"
        a = {key:{"target":{"src_path":src},"fresh":False}}
        prefix = "INFO cargo::compiler::fingerprint: "
        target = 'ruff v0.16.7 (/ruff/crates/ruff)/Test/TargetInner { name: "ruff", ..: with_path("' + src + '", Edition2024) }'
        for mode, body in (("dirty","    dirty: FsStatusOutdated(StaleItem(MissingFile))"),("error","    err: no such file")):
            msg = (prefix+"fingerprint "+mode+" for "+target+"\n"+prefix+body+"\n").encode()
            self.assertEqual(len(units.log_reasons(msg,a)[key]),1)
            for bad in (msg.replace(b"/Test/",b"/Build/"),msg.replace(b"main.rs",b"lib.rs"),msg.splitlines()[0]+b"\n"):
                with self.assertRaises(RuntimeError): units.log_reasons(bad,a)

    def test_physical_saved_recipe_and_missing_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            phase=base/"22/native/unchanged"
            phase.mkdir(parents=True)
            root=base/"slot/shared/unit/1234567890abcdef"
            out=root/"out/probe-1234567890abcdef"
            out.parent.mkdir(parents=True)
            out.write_bytes(b"ELF test fixture")
            ri=out.with_suffix(".rlink")
            manifest=out.with_suffix(".rlink-cache.json")
            obj=out.with_suffix(".rlink-objects")/"one.o"
            obj.parent.mkdir()
            obj.write_bytes(b"fixture object")
            ri.write_bytes(b"rustlink\x01fixture")
            hexdigest=lambda p: subprocess.check_output(["b3sum","--",p]).split()[0].decode()
            declaration={"version":5,"input_checksum":1,"proof_checksum":2,
                         "rlink":{"path":str(ri),"blake3":hexdigest(ri)},
                         "executable":{"path":str(out),"len":out.stat().st_size,"modified_nanos":out.stat().st_mtime_ns},
                         "objects":[{"path":str(obj),"blake3":hexdigest(obj)}]}
            manifest.write_text(json.dumps(declaration))
            tracked={"probe":{"product":str(out)}}
            read=lambda h: gzip.decompress((base/"22/recipe-blobs"/(h+".gz")).read_bytes())
            def verdict():
                return units.recipe_matches(str(out),units.facts(phase,tracked)["probe"],read)
            self.assertEqual(verdict(),"matches-recorded-files")
            obj.write_bytes(b"a different object")
            self.assertEqual(verdict(),"differs-from-recorded-files")
            ri.unlink()
            self.assertEqual(verdict(),"missing")

    def test_actual_optimized_cargo_speculative_retry_and_true_repeat(self):
        packet=json.loads(gzip.decompress((lc.FIX/"rc22-small-native.json.gz").read_bytes()))
        for role, path in (("rustc","bin/rustc"),("cargo","bin/cargo"),("wild","lib/rustlib/"+sdk.HOST+"/bin/wild-ld/ld.bfd")):
            self.assertEqual(packet["tools"][role]["sha256"],sdk.SPEC["files"][path][1])
        for phase, raw in packet["stages"].items():
            self.assertIn(sdk.CARGO,raw["cargo_version"])
            rows,parents,leader,exits=trace.read(gzip.decompress(base64.b64decode(raw["process_gz"])).splitlines())
            expected=raw["actual"]
            tools=packet["tools"]
            self.assertEqual(lc.native(rows,tools,raw["aliases"]),expected)
            launch=trace.launch(rows,leader,raw["aliases"],tools)
            self.assertEqual(launch["rustc_pids"],sorted(c["pid"] for c in expected["compilers"]))
            with self.assertRaises(RuntimeError):
                trace.launch(rows,leader,raw["aliases"],tools|{"cargo":tools["rustc"]})
            arts=[j for line in raw["stdout"].splitlines() if (j:=json.loads(line)).get("executable")]
            items={lc.unit_key(a):a for a in arts}
            self.assertEqual(len(items),2)
            by_output={str(units.literal_output(a)):k for k,a in items.items()}
            self.assertEqual(set(raw["native_stdout_digest"]),set(by_output))
            links=[r|{"unit":by_output[r["output"]]} for r in expected["wild"]]
            cwd=arts[0]["manifest_path"].split("/crates/",1)[0]
            tracked=units.join(items,rows,expected,links,cwd,exits)
            owners=trace.owners(tracked,parents,leader,expected["compilers"],exits)
            self.assertEqual(owners,raw["owners"])
            load=lambda h:gzip.decompress(base64.b64decode(packet["bodies"][h]))
            for facts in (raw["facts"],raw["pre"]):
                if facts:
                    self.assertEqual(set(facts),set(tracked))
                    for k,v in facts.items():
                        self.assertEqual(units.recipe_matches(tracked[k]["product"],v,load),"matches-recorded-files")
            manual=next(k for k in items if items[k]["target"]["name"]=="manual")
            self.assertEqual(len(owners), 0 if phase=="unchanged" else 2)
            self.assertEqual(sorted(c["exit"] for c in tracked[manual]["rustc"]),
                             {"cold":["0","1"],"unchanged":[],"edited-diagnostic":["0"]}[phase])
            if phase=="cold":
                failed, = [c["pid"] for c in tracked[manual]["rustc"] if c["exit"]=="1"]
                actual=owners[manual][0]["rustc"]
                self.assertNotEqual(failed,actual)
                with self.assertRaises(RuntimeError):
                    trace.owners(tracked,parents,leader,expected["compilers"],exits|{actual:"1"})
            elif phase=="edited-diagnostic":
                why=units.log_reasons(raw["stderr"].encode(),items)
                self.assertIn("StaleDepFingerprint",why[manual][0][1])
                self.assertTrue(any("ChangedChecksum" in row[1] for v in why.values() for row in v))
            else:
                self.assertTrue(all(r["mode"]=="fresh" for r in tracked.values()))

    def test_original_gnu_job_in_its_failed_workflow(self):
        source=json.loads((lc.FIX/"rc22-gnu-origin.json").read_bytes())
        sdk.check_origin(source)
        for group,field,value in (("run","conclusion","success"),("run","head_sha","0"*40),
                                  ("job","conclusion","failure"),("job","run_attempt",2),("job","id",124701560586),
                                  ("artifact","digest","sha256:"+"0"*64),("artifact","id",13065158467)):
            bad=copy.deepcopy(source);bad[group][field]=value
            with self.assertRaises(RuntimeError): sdk.check_origin(bad)
        bad=copy.deepcopy(source);bad["job"]["steps"]=[]
        with self.assertRaises(RuntimeError): sdk.check_origin(bad)

    def test_dist_and_dispatch_substitutions(self):
        sdk.check_members(sdk.SPEC["files"])
        for name in ("bin/cargo","bin/rustc","bin/rustdoc",next(k for k in sdk.SPEC["files"] if "librustc_driver" in k)):
            bad=copy.deepcopy(sdk.SPEC["files"]);bad[name][1]="0"*64
            with self.assertRaises(RuntimeError): sdk.check_members(bad)
        head="1"*40
        q={"head":head,"parent":sdk.PARENT,"ref":"refs/heads/"+sdk.PILOT,"repository":sdk.REPO,
           "workflow":".github/workflows/ci.yml","event":"workflow_dispatch","attempt":1,
           "job":"linux-workspace","run":9,"system":"Linux","machine":"x86_64","cpus":16,"free_at_entry":111<<30,
           "boot":"6d32b5cf-40c5-4ddc-aebc-cf164b21502d","work_root":"/tmp/packaged-linux-50"}
        sdk.check_worker(q,head)
        for field, bad in (("head","0"*40),("parent","0"*40),("event","push"),("attempt",2),("machine","aarch64"),
                           ("free_at_entry",65<<30),("cpus",8),("ref","refs/heads/main")):
            with self.assertRaises(RuntimeError): sdk.check_worker(q|{field:bad},head)

def native_fixture(dest):
    dest.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as temporary:
        p = Path(temporary)
        binary = p/"native"
        cc = shutil.which("gcc")
        prog = b'#include <stdio.h>\nint main(void){puts("native-50");return 0;}\n'
        subprocess.run(["strace",*trace.FLAGS,"-o",p/"exec",cc,"-x","c","-","-o",binary],input=prog,check=True)
        ledger=dest/"process.tsv.gz"
        trace.retain(p, ledger)
        with gzip.open(ledger,"rb") as f: rows, parents, leader, exits = trace.read(f)
        tools=[(pid, Path(lc.event(line.encode())[0]).name) for pid,line in rows]
        ld, = (pid for pid,name in tools if name in lc.LINKERS)
        collect, = (pid for pid,name in tools if name == "collect2")
        chain=trace.ancestry(ld,parents,leader)
        need(collect in chain and chain[-1] == leader, "native GCC/collect2/ld ancestry lost")
        need(subprocess.check_output([binary])==b"native-50\n","different physical linked ELF")
        save(dest/"native.json",{"collector":collect,"linker":ld,"root":leader,"chain":chain,
                                  "program":lc.elf_bytes(binary.read_bytes())["sha256"],
                                  "ledger":lc.digest(ledger.read_bytes())})

if __name__=="__main__":
    native = Path(sys.argv[2]) if len(sys.argv)==3 and sys.argv[1]=="--native" else None
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
    if native:native_fixture(native)
