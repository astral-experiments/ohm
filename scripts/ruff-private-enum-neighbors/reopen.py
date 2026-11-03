"""Verify original native bodies, producer rows and kernel rosters from the single unscored worker."""
import argparse
import ast
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ruff-ruf009-derived-enum"))
import metadata
import opaque_bijection

PLAN = json.loads((HERE / "plan.json").read_bytes())
CHECKS = ("old", "old-unchanged", "edit", "edited-unchanged", "reverse", "invalid", "repair", "empty-edited")
NATIVE = ("native-old", "native-edit", "native-reverse", "native-empty-edited")
COMMON = ["--locked", "--offline", "-j4", "--message-format=json"]
FLAG = "-Zohm-checked-private-derives-v2"
ACTIVE = {"run": 41662416586, "head": "efd433061c9ca421f48d8eeb0b70e6b3fa914715"}


def digest(body):
    return hashlib.sha256(body).hexdigest()


def read_kernel(body, sdk, driver):
    typed = {}
    opened = defaultdict(list)
    root = PurePosixPath(sdk).parent
    compiler = {sdk + "/bin/rustc", str(root / "rustup/toolchains/ohm/bin/rustc")}
    accepted_driver = {str(PurePosixPath(sdk) / driver), str(root / "rustup/toolchains/ohm" / driver)}
    for line in gzip.decompress(body).splitlines():
        tid, row = json.loads(line)
        if row.startswith("execve(") and '"--crate-name"' in row:
            exe, args = row[len("execve("):].split(", [", 1)
            exe = ast.literal_eval(exe)
            if exe == str(root / "proxies/rustc"):
                continue
            assert exe in compiler, exe
            raw, end = args.rsplit("], ", 1)
            assert end.endswith(") = 0") and tid not in typed
            typed[tid] = ast.literal_eval("[" + raw + "]")
        elif row.startswith("openat("):
            match = re.search(r'openat\([^,]+, "([^"]+)",.*\)\s+=\s+[0-9]+', row)
            assert match, row
            opened[tid].append(match.group(1))
    for tid in typed:
        assert accepted_driver.intersection(opened[tid]), tid
    return typed


class Evidence:
    def __init__(self, archive):
        self.z = archive
        self.names = set(archive.namelist())
        assert len(self.names) == len(archive.infolist())
        assert all(not PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts for p in self.names)
        self.decoded = {}
        self.sizes = Counter()
        self.decoded_ids = set()

    def js(self, name):
        return json.loads(self.z.read(name))

    def member(self, key, kind):
        assert re.fullmatch("[a-f0-9]{64}", key)
        body = subprocess.check_output(["zstd", "-qdc"], input=self.z.read("members/"+key+"."+kind+".zst"))
        assert digest(body) == key
        if (key,kind) not in self.decoded_ids:
            self.sizes[kind] += len(body)
            self.decoded_ids.add((key,kind))
        return body

    def table(self, info, crate, version, edition):
        key = info["full"]
        if key not in self.decoded:
            actual = metadata.table(self.member(key,"rmeta"), crate, version, edition)
            assert actual == json.loads(self.member(info["rows"], "rows"))
            self.decoded[key] = actual
        actual = self.decoded[key]
        assert info["public"] == actual["header"]["public"] and info["count"] == len(actual["rows"])
        return actual


def summarized_files(rec):
    actual = {k: v["sha256"] for k,v in rec["artifacts"].items() if not v["local"]}
    return actual, {k:v["sha256"] for k,v in rec["generated"].items()}


def diff_files(pre, post):
    keys = set(pre) | set(post)
    different = sorted(k for k in keys if pre.get(k) != post.get(k))
    return {"equal": len(keys)-len(different), "differing": different}


def runtime(case, phase, data, executable, run_native):
    old = phase in ("native-old", "native-reverse")
    if case == "line-index":
        want = ("2" if old else "1") + "\n1\n1\n"
        args = []
    else:
        args = ["LATIN CAPITAL LETTER A", "latinSMALLletterA", "NO SUCH OHM CHARACTER"]
        want = "A\n" + ("a\n" if old else "latinSMALLletterA: no such character\n") + "NO SUCH OHM CHARACTER: no such character\n"
    assert data["args"] == args and data["stdout"] == data["expected"] == want
    assert data["exit"] == 0 and data["stderr"] == "" and data["bytes"] == len(executable) and executable[:4] == b"\x7fELF"
    if run_native:
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / "tested"
            binary.write_bytes(executable)
            binary.chmod(0o700)
            verdict = subprocess.run([binary, *args], capture_output=True, timeout=12)
            assert verdict.returncode == 0 and verdict.stdout == want.encode() and not verdict.stderr


def reopen(root, name, c, role, run_native):
    prefix = name+"-"+role+"/"
    mode = root.js(prefix+"activated.json")
    assert mode["driver"] == PLAN["driver"][role] and mode["cargo"] == PLAN["cargo"]
    assert mode["config"] == root.js("scope-sdks.json")["inline-"+role]
    assert mode["config"]["source"] == PLAN["source_commits"][role]
    files = mode["config"]["files"]
    driver, = [p for p,h in files.items() if p.startswith("lib/librustc_driver-") and h == mode["driver"]]
    assert files["bin/cargo"] == mode["cargo"] and files["bin/rustc"] == mode["rustc"]
    version = mode["rustc_version"].splitlines()[0]+" (Ohm metadata 3)"
    phases, physical, bodies, native = {}, {}, {}, {}
    for phase in CHECKS:
        base = prefix+phase+"/"
        info = root.js(base+"observed.json")
        cmd = root.js(base+"command.json")
        args = ["cargo", "+ohm", "check", *c["selector"], *COMMON]
        assert info["argv"] == args and cmd["argv"][-len(args):] == args and "/usr/bin/strace" == cmd["argv"][0]
        invalid = phase == "invalid"
        assert cmd["exit"] == info["status"] == (101 if invalid else 0)
        stream = [json.loads(line) for line in root.z.read(base+"stdout").splitlines()]
        assert [m["success"] for m in stream if m["reason"]=="build-finished"] == [not invalid]
        errors=[m["message"] for m in stream if m["reason"]=="compiler-message" and m["message"]["level"]=="error"]
        assert errors == info["errors"]
        if invalid:
            assert [err["code"]["code"] for err in errors]==["E0308"]
            assert any(s["is_primary"] and s["file_name"]==c["error_source"] for s in errors[0]["spans"])
        else: assert not errors
        typed = [m for m in stream if m["reason"]=="compiler-artifact"]
        actual = read_kernel(root.z.read(prefix+phase+"-observer/kernel.jsonl.gz"),mode["active"],driver)
        for r in info["actual"]:
            assert actual[r["tid"]] == r["argv"] and r["crate"] == r["argv"][r["argv"].index("--crate-name")+1]
        assert len(info["actual"]) == len(actual) and {v["tid"] for v in info["actual"]} == set(actual)
        selected_args=[argv for argv in actual.values() if argv[argv.index("--crate-name")+1]==c["owner"]]
        assert all((FLAG in argv) == (role=="C") for argv in selected_args)
        owners = [argv[argv.index("--crate-name")+1] for argv in actual.values()]
        physical[phase] = summarized_files(root.js(base+"physical-inputs.json"))
        if not invalid:
            bodies[phase]={}
            for n,entry in info["metadata"].items():
                row,=[m for m in typed if m["target"]["name"]==n and entry["file"] in m["filenames"]]
                bodies[phase][n]=root.table(entry,n,version,row["target"]["edition"])
            pub = info["metadata"][c["owner"]]["public"]
            assert root.js(base+"display.json")["native"]=="Public hash: "+bytes.fromhex(pub)[::-1].hex()
        nominal=[m["target"]["name"] for m in typed if not m["fresh"]]
        assert nominal==info["nominal"]
        phases[phase]=dict(actual=sorted(owners),selector=[v for v in c["selected"] if v in owners and v!=c["owner"]],
                           get_size=info["get_size"],nominal=sorted(nominal),metadata=info["metadata"],
                           v2_flags=[FLAG in a for a in selected_args],exit=cmd["exit"],
                           source=info["source"])
    for phase in NATIVE:
        path=prefix+phase+"/native.json"
        data=root.js(path)
        runtime(name, phase, data, root.member(data["exe"], "elf"), run_native)
        native[phase]=data["exe"]
    comparison={}
    for key, a, b in [("edit","old","edit"),("empty","edit","empty-edited"),("repair","edit","repair"),
                       ("reverse","old","reverse"),("old-settled","old","old-unchanged"),
                       ("edited-settled","edit","edited-unchanged")]:
        if a not in bodies or b not in bodies: continue
        comparison[key]={}
        for crate in sorted(bodies[a].keys()&bodies[b].keys()):
            old, new = bodies[a][crate], bodies[b][crate]
            diff=metadata.compare(old,new)
            comparison[key][crate]=dict(full_equal=phases[a]["metadata"][crate]["full"]==phases[b]["metadata"][crate]["full"],
                public_equal=old["header"]["public"]==new["header"]["public"], rows=[len(old["rows"]),len(new["rows"])],
                changed_rows=len(diff),changed_id_sha256=digest("\n".join(x["id"] for x in diff).encode()),first_12=[dict(id=x["id"],old=x["old"],new=x["new"]) for x in diff[:12]],
                changed_requires=diff_files(old["requires"],new["requires"]))
    drift = {}
    if name == "line-index":
        def ast_meta(phase):
            return root.member(phases[phase]["metadata"]["ruff_python_ast"]["full"],"rmeta")
        for a,b in [("edit","empty-edited"),("old","reverse")]:
            ja,jb=ast_meta(a),ast_meta(b)
            if ja != jb:
                drift[a+"-vs-"+b]=opaque_bijection.compare(ja,jb,role,version,"2024",owner="ruff_python_ast")
    comparables=[("old","edit"),("edit","empty-edited"),("old","reverse"),("edit","repair")]
    external={a+"-vs-"+b:dict(artifacts=diff_files(physical[a][0],physical[b][0]),generated=diff_files(physical[a][1],physical[b][1]))
              for a,b in comparables if a in physical and b in physical}
    return dict(source=mode["config"]["source"],driver=mode["driver"],stages=phases,rows=comparison,
                external_physical=external,native=native,ast_raw_same_source=drift)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",type=Path);p.add_argument("--sha256",required=True)
    p.add_argument("--output",type=Path,required=True);p.add_argument("--execute-native",action="store_true")
    a=p.parse_args()
    with a.archive.open("rb")as f: assert hashlib.file_digest(f,"sha256").hexdigest()==a.sha256
    with zipfile.ZipFile(a.archive)as z:
        evidence=Evidence(z); worker=evidence.js("worker.json")
        assert worker["plan"]==PLAN and all(worker[k]==v for k,v in ACTIVE.items())
        terminal=evidence.js("complete.json")
        assert not terminal["refusals"] and set(terminal["result"]) == set(PLAN["cases"])
        assert terminal["pmu"] is False and terminal["scored_pairs"]==terminal["confirmation_workers"]==0
        previous=HERE.parent/"ruff-ruf009-derived-enum"
        factory=evidence.js("scope-kit-ruf009.json")
        client=evidence.js("client-native.json")
        assert factory["entries"]==json.loads((previous/"factory.json").read_bytes()) and factory["run"]==PLAN["factory"]
        assert client["binding"]==json.loads((previous/"client.json").read_bytes())
        assert client["constructor"]["binary_sha256"]==PLAN["cargo"]
        for role,label in (("P","normal"),("C","defer")):
            source=factory["manifest"]["arms"][label]["files"]
            actual=evidence.js("scope-sdks.json")["inline-"+role]["files"]
            assert len(source)==66 and actual==(source|{"bin/cargo":PLAN["cargo"]})
        results={}; endpoint={}
        for n,c in PLAN["cases"].items():
            results[n]={}
            for role in "PC":
                assert set(terminal["result"][n])=={"P","C"}
                results[n][role]=reopen(evidence,n,c,role,a.execute_native)
            pair=results[n]; owner=c["owner"]; sid=pair["P"]["rows"]["edit"][owner]["changed_id_sha256"]
            assert sid==pair["C"]["rows"]["edit"][owner]["changed_id_sha256"]
            for arm in pair.values():
                assert not arm["stages"]["old-unchanged"]["actual"] and not arm["stages"]["edited-unchanged"]["actual"]
                assert all(not v["get_size"] for v in arm["stages"].values())
                assert arm["native"]["native-old"]==arm["native"]["native-reverse"]!=arm["native"]["native-edit"]
                assert arm["native"]["native-edit"]==arm["native"]["native-empty-edited"]
                assert not arm["rows"]["edit"][owner]["public_equal"] and arm["rows"]["empty"][owner]["full_equal"]
            assert pair["P"]["native"]==pair["C"]["native"]
            endpoint[n] = {"edit_consumers":{role:arm["stages"]["edit"]["selector"] for role,arm in pair.items()},
                          "reverse_consumers":{role:arm["stages"]["reverse"]["selector"] for role,arm in pair.items()},
                          "edited_owner_rows":pair["P"]["rows"]["edit"][owner]["changed_rows"],
                          "changed_stable_ids_sha256":sid}
        assert set(n for n in evidence.names if n.startswith("members/") and n.endswith(".zst"))=={
            f"members/{h}.{suffix}.zst" for h,suffix in evidence.decoded_ids}
        projection=dict(run=worker["run"],job=worker["job"],boot=worker["boot"],head=worker["head"],
            archive_sha256=a.sha256,physical_endpoints=endpoint,refusals=terminal["refusals"],results=results,member_bytes=evidence.sizes,
            unique_members=len(evidence.decoded_ids),reexecuted_native=a.execute_native,scored_pairs=0)
        a.output.write_text(json.dumps(projection,sort_keys=True,indent=2)+"\n")

if __name__=="__main__": main()
