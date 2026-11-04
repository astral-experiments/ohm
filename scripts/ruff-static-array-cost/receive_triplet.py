"""Authenticate, reopen and score original three-compiler Actions artifacts. No dispatch."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

kit = Path(__file__).resolve().parent
sys.path.insert(0, str(kit))
import triplet

def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()

def checksum(data):
    return hashlib.sha256(data).hexdigest()

def hardware(row):
    assert row["status"] == 0 and row["instructions"] > 0 and row["enabled"] == row["running"] > 0
    return row["instructions"]

def target_counter(z, name, observed):
    prefix = name + "/execs/"
    images = {}
    actual = {}
    totals = []
    for line in z.read(prefix + "epochs.tsv").decode().splitlines():
        s = line.split()
        if s[0] == "I":
            idx, pid = map(int, s[1:3])
            argv = z.read(prefix + f"{idx:05}.nul").split(b"\0")
            assert argv.pop() == b"" and int(argv[0]) == pid and idx not in images
            images[idx] = (pid, argv[3], argv[4:], s[-1])
        elif s[0] == "R":
            idx,pid,ins,en,ran,status = map(int, s[1:])
            p,exe,argv,origin = images[idx]
            assert status == 0 and origin == "exec" and p == pid and en == ran > 0 and ins > 0
            assert idx not in actual
            actual[idx] = (exe,argv,ins)
        elif s[0] == "W":
            ins,en,ran,status = map(int, s[1:])
            assert status == 0 and ins > 0 and en == ran > 0
            totals.append(ins)
    assert totals == [observed["traced_total"]]
    assert set(actual) == {r["image"] for r in observed["actual"]}
    selected = []
    for row in observed["actual"]:
        exe, argv, ins = actual[row["image"]]
        assert [a.decode() for a in argv] == row["argv"] and ins == row["instructions"]
        if row["tool"] == "rustc" and row["crate"] == "unicode_names2":
            assert exe.endswith(b"/sdk/bin/rustc") and argv[argv.index(b"--crate-name")+1] == b"unicode_names2"
            assert b"crates/ruff_unicode_names2/src/lib.rs" in argv and b"-Zlink-only" not in argv
            selected.append(ins)
    value, = selected
    assert value == observed["target_rustc"]
    return value

def disk(row):
    inodes = row["inodes"]
    assert len(inodes) == row["files"] == len({(v["dev"],v["ino"]) for v in inodes})
    paths = [p for v in inodes for p in v["paths"]]
    assert len(paths) == len(set(paths)) and all(p.startswith(("target/","shared/")) and ".." not in Path(p).parts for p in paths)
    for name in ("logical","allocated"):
        assert row[name] == sum(v[name] for v in inodes) > 0
    return {n:row[n] for n in ("logical","allocated","files")}

def open_job(z, role_reg, trans, fixture, host, native_witness):
    read = lambda p: json.loads(z.read(p))
    totals = read("result.json")
    assert set(totals) == set(triplet.ARMS)
    assert read("cargo-inputs.json") == role_reg["archives"] and len(role_reg["archives"]) == 502
    controls = [hardware(read(f"calibrate-{n}.json")) for n in ("single","fork")]
    assert 1.99 < controls[1]/controls[0] < 2.01
    frozen_tables = json.loads((kit/"rng-tables.json").read_bytes())
    for state in ("old","new"):
        data = z.read(f"generated/{state}-phf.rs")
        assert {"file_sha256":checksum(data),**triplet.census(data)} == frozen_tables[state]
        assert checksum(data) == fixture[state+"_generated"]["generated_phf.rs"]
    records, stores, native = {}, {}, {}
    bootstraps = set()
    for arm in triplet.ARMS:
        before = f"sdk-{arm}/"
        source, sdk = read(before+"source.json"),read(before+"sdk.json")
        signed = role_reg["compiler_arms"][arm]
        spec = trans[arm]
        assert source["source"] == signed["source"] and source["tree"] == signed["tree"] and source["role"] == signed["factory_role"]
        assert source["factory"] == signed["factory_head"] == spec["qa"] and int(source["run"]) == signed["factory_run"] == spec["run"]
        assert sdk["driver"] == spec["driver"] and z.read(before+"sdk-sha256").decode().strip() == spec["tar"]
        assert signed["source"] in sdk["versions"]["rustc"] and role_reg["cargo"] in sdk["versions"]["cargo"]
        assert sdk["release_cargo"] == role_reg["release_members"]["bin/cargo"]["sha256"]
        assert sdk["wild"] == role_reg["release_members"]["lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"]["sha256"]
        training = read(before+"training.json")
        assert {k for k,v in training["profiles"].items() if len(v[0]) == 64 and v[1] > 0} == {"rustc","rustdoc","clippy","rustfmt"}
        assert training["script"] == spec["script"] and training["config"] == spec["config"] == checksum(z.read(before+"bootstrap.toml"))
        bootstraps.add(z.read(before+"bootstrap.json"))
        scalar = read(before+"probes/verdict.json")
        assert scalar["marked_arrays"] == (0 if arm == "F5" else 4) and scalar["native_repaired"] == scalar["native_empty"] != scalar["native_old"]
        extra = read(before+"aggregate-verdict.json")
        assert extra["marker_count"] == (4 if arm == "C7" else 0) and extra["old"]["output"] != extra["repair"]["output"]
        assert extra["repair"] == extra["empty"] and len(extra["invalid"]) == 2 and extra["invalid"][0] == extra["invalid"][1]
        records[arm],stores[arm],native[arm] = {},{},{}
        for mode in triplet.MODES:
            fields, snapshots, products, bodies = {},{},{},{}
            stem = f"{arm}/{mode}/"
            stages = ["cold-old","ordinary-edit","unchanged","observed-edit","empty-new","observed-empty-new"]
            if mode == "build":
                stages.append("repaired")
            counters = {"cold-old":"cold","ordinary-edit":"whole_edit","unchanged":"unchanged",
                        "empty-new":"empty","observed-edit":"observed_whole"}
            for phase in stages:
                at = stem + phase
                state = "old" if phase == "cold-old" else "new"
                result = read(at+"/result.json")
                rows = [json.loads(l) for l in z.read(at+"/stdout.jsonl").splitlines()]
                assert rows[-1] == {"reason":"build-finished","success":True}
                typed = [r for r in rows if r["reason"] == "compiler-artifact"]
                assert len(typed) == result["unit_count"] == fixture[state+"_units"]
                dirty = sorted(r["target"]["name"] for r in typed if not r["fresh"])
                assert dirty == result["dirty"]
                if phase in ("ordinary-edit","observed-edit"):
                    assert dirty == fixture["edit_dirty"]
                elif phase == "unchanged": assert not dirty
                elif phase != "repaired": assert len(dirty) == len(typed)
                assert result["command"] == ["cargo","+ohm",mode,"-p","ruff_unicode_names2","--lib","--locked","--offline","--message-format=json"]
                assert result["commit"] == fixture[state] and result["generated"] == fixture[state+"_generated"]
                hw = hardware(read(at+"/hardware.json"))
                assert hw == result["hardware"]
                if phase in counters:
                    fields[counters[phase]] = hw
                if phase in ("observed-edit","observed-empty-new"):
                    key = "target_rustc" if phase=="observed-edit" else "empty_target_rustc"
                    fields[key] = target_counter(z, at, result["lifetime"])
                if phase in ("ordinary-edit","unchanged","empty-new"):
                    snapshots[phase] = disk(read(at+"/storage.json"))
                products[phase] = result["product_sha256"]
                if mode == "build":
                    elf = z.read(at+"/reader")
                    stream = z.read(at+"/native.bin")
                    assert len(stream) == fixture["native_bytes"] and checksum(stream) == fixture[state+"_stdout"]
                    assert elf.startswith(b"\x7fELF") and {"elf":checksum(elf),"stdout":checksum(stream)} == result["native"]
                    native_witness(elf,stream)
                    bodies[phase] = (result["native"],result["members"]["verified_renames"])
            if mode == "check":
                assert len({v for k,v in products.items() if k!="cold-old"}) == 1
            else:
                assert bodies["cold-old"][0]["elf"] != bodies["ordinary-edit"][0]["elf"]
                assert all(v == bodies["empty-new"] for k,v in bodies.items() if k!="cold-old")
                assert len(bodies["empty-new"][1]) == 15
                for label, code, token in (("invalid","overflowing_literals","256"),("invalid-tuple","overflowing_literals","65536"),("invalid-char","E0308","65u32")):
                    err = read(stem+label+"/error.json")
                    assert err == read(stem+label+"-again/error.json") and len(err)==1 and err[0]["code"]["code"]==code
                    span, = [s for s in err[0]["spans"] if s["is_primary"]]
                    assert span["file_name"] == "crates/ruff_unicode_names2/src/lib.rs" and span["byte_end"]-span["byte_start"] == len(token)
                    assert span["text"][0]["text"][span["text"][0]["highlight_start"]-1:span["text"][0]["highlight_end"]-1] == token
                    for suffix in ("","-again"):
                        rows = [json.loads(l) for l in z.read(stem+label+suffix+"/stdout.jsonl").splitlines()]
                        assert rows[-1] == {"reason":"build-finished","success":False} and any(r.get("message")==err[0] for r in rows)
                native[arm] = {k:v[0] for k,v in bodies.items()}
            assert all(v == totals[arm][mode][k] for k,v in fields.items())
            records[arm][mode], stores[arm][mode] = fields,snapshots
    assert len(bootstraps) == 1
    return {"boot":host["boot"],"order":host["order"],"results":records,"storage":stores,"native":native}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=int); parser.add_argument("head"); parser.add_argument("out", type=Path)
    parser.add_argument("--gh-auto",required=True); parser.add_argument("--pilot",type=Path,
        help="Admitted prior pilot receipt, mandatory only for a six-boot run")
    parser.add_argument("--run-native",action="store_true",help="Re-execute each distinct original reader on Linux x86-64")
    args = parser.parse_args()
    assert __debug__
    reg = json.loads((kit/"registration.json").read_bytes()); trans = json.loads((kit/"transports.json").read_bytes())
    assert all(isinstance(trans.get(a),dict) for a in triplet.ARMS)
    assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=kit,text=True).strip() == args.head
    orders = triplet.CONFIRM if args.pilot else triplet.PILOTS; assert reg["orders"]==orders
    assert reg["confirmation_orders"] == triplet.CONFIRM
    official = lambda path: json.loads(subprocess.check_output([args.gh_auto,"api","repos/astral-experiments/ohm/actions/"+path],cwd=kit))
    run = official(f"runs/{args.run}"); assert run["run_attempt"] == 1 and run["head_sha"] == args.head
    assert (run["event"],run["status"],run["conclusion"]) == ("workflow_dispatch","completed","success")
    jobs = official(f"runs/{args.run}/attempts/1/jobs?per_page=100")["jobs"]
    assets = official(f"runs/{args.run}/artifacts?per_page=100")["artifacts"]
    assert len(jobs)==len(assets)==len(orders)
    args.out.mkdir(parents=True,exist_ok=True)
    prior = {b for arr in reg["prior_boots_by_run"].values() for b in arr}
    if args.pilot:
        p = json.loads(args.pilot.read_bytes()); assert p["decision"]["admit_six"] and p["run"]!=args.run
        assert p["compiler_arms"] == reg["compiler_arms"] and p["transports"] == trans
        prior.update(row["boot"] for row in p["rows"].values())
    originals = {}
    for block,order in orders.items():
        j, = [j for j in jobs if j["name"]=="Ruff Unicode rand edit "+block]
        a, = [a for a in assets if a["name"]==f"unicode-price-rand-{block}-{args.run}"]
        assert j["conclusion"]=="success" and j["head_sha"]==args.head and j["run_attempt"]==1
        assert a["workflow_run"]["head_sha"]==args.head and a["workflow_run"]["id"]==args.run and not a["expired"]
        assert 0 < a["size_in_bytes"] < 128*2**20
        filepath = args.out/(block+".zip")
        if not filepath.exists():
            pending=filepath.with_suffix(".pending")
            with pending.open("xb") as stream:
                subprocess.run([args.gh_auto,"api","--allow-escape-sequences",f"repos/astral-experiments/ohm/actions/artifacts/{a['id']}/zip"],cwd=kit,stdout=stream,check=True)
            assert "sha256:"+sha(pending)==a["digest"] and pending.stat().st_size==a["size_in_bytes"]
            pending.rename(filepath)
        assert "sha256:"+sha(filepath)==a["digest"] and filepath.stat().st_size==a["size_in_bytes"]
        originals[block]={"job":j["id"],"artifact":a["id"],"sha256":sha(filepath),"bytes":a["size_in_bytes"]}
    import tempfile
    fixture = reg["cases"]["rand"]
    aliases = (kit/"NameAliases.txt").read_bytes()
    assert checksum(aliases)==fixture["name_aliases_sha"]
    aliases=[(row.split(";")[1],int(row.split(";")[0],16))for row in aliases.decode().splitlines()if row and not row.startswith("#")]
    assert len(aliases)==481
    aliases += [(n,0xffffffff) for n in ("carriage_return","Black_Star","NO SUCH CODE POINT")]
    stdin = ("\n".join(n for n,_ in aliases)+"\n").encode()
    known_elf,known_stream = set(),set()
    def native_witness(elf,stream):
        import struct
        stream_id=checksum(stream)
        if stream_id not in known_stream:
            names,returned={},[]
            pos=0
            while pos<len(stream):
                tag=stream[pos];pos+=1;assert tag in (1,2)
                if tag==1:cp,=struct.unpack_from("<I",stream,pos);pos+=4
                n,=struct.unpack_from("<I",stream,pos);pos+=4
                word=stream[pos:pos+n].decode();pos+=n
                value,=struct.unpack_from("<I",stream,pos);pos+=4
                if tag==1:
                    assert value==cp<=0x10ffff and cp not in names
                    names[cp]=word
                else:returned.append((word,value))
            assert pos==len(stream) and len(names)==len(set(names.values()))==153626 and returned==aliases
            known_stream.add(stream_id)
        elf_id=checksum(elf)
        if args.run_native and elf_id not in known_elf:
            with tempfile.TemporaryDirectory()as folder:
                exe=Path(folder)/"reader";exe.write_bytes(elf);exe.chmod(0o700)
                assert subprocess.check_output([exe],input=stdin)==stream
        known_elf.add(elf_id)
    rows={}
    for block,order in orders.items():
        with ZipFile(args.out/(block+".zip")) as z:
            assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
            host=json.loads(z.read("host.json"));assert host["order"]==order and host["head"]==args.head and host["case"]=="rand"
            assert host["registration_sha256"]==sha(kit/"registration.json") and host["transports_sha256"]==sha(kit/"transports.json")
            assert host["target_case"]==[fixture["old"],fixture["new"]] and host["boot"] not in prior
            prior.add(host["boot"])
            rows[block]=open_job(z,reg,trans,fixture,host,native_witness)
    decision=triplet.judge(rows)
    result={"run":args.run,"head":args.head,"compiler_arms":reg["compiler_arms"],"transports":trans,"originals":originals,
            "rows":rows,"decision":decision,"native_readers":sorted(known_elf),"native_streams":sorted(known_stream)}
    (args.out/"readback.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps({k:v for k,v in decision.items() if k!="contrasts"},indent=2))

if __name__=="__main__":
    main()
