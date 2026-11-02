"""Reopen the original action artifacts, including their kernel traces and PMU counters."""
import argparse
import ast
import gzip
from hashlib import sha256
import io
import itertools
import json
import math
import re
from pathlib import Path
import statistics
import tarfile
from zipfile import ZipFile

EXAMPLE = "struct_name_as_context"
WILD = "/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"


def need(condition, what):
    if not condition:
        raise ValueError(what)


def read(archive, path):
    return json.loads(archive.read(path))


def physical(archive, phase):
    result = read(archive, phase + "/result.json")
    original = []
    with tarfile.open(fileobj=io.BytesIO(archive.read(phase + "/kernel-execs.tar.gz")), mode="r:gz") as t:
        for member in t:
            if not member.isfile():
                continue
            for raw in t.extractfile(member).read().splitlines():
                if not raw.startswith(b'execve("') or not raw.endswith(b" = 0"):
                    continue
                raw_path = raw.split(b'", [',1)[0][8:].decode()
                kind = ("rustc" if raw_path.endswith("/bin/rustc") else
                        "wild" if raw_path.endswith(WILD) else "other")
                if kind == "other":
                    continue
                line = raw.decode()
                argv = ast.literal_eval(line[line.index("["):line.rindex("], ") + 1])
                original.append((kind, raw_path, argv, sha256(raw).hexdigest()))
    by_sha = {row["exec_sha256"]:row for row in result["execs"]}
    # Rustup can perform additional executable searches. Identify the original
    # physical events that created this specific example's own native output.
    compilers = [row for row in original if row[0] == "rustc" and "--crate-name" in row[2]
                 and row[2][row[2].index("--crate-name")+1] == EXAMPLE]
    links = [row for row in original if row[0] == "wild" and "-o" in row[2] and
             Path(row[2][row[2].index("-o")+1]).name == EXAMPLE]
    for kind, path, argv, digest in compilers + links:
        data = by_sha[digest]
        need(data["kind"] == kind and data["path"] == path and data["args"] == argv, "actual exec arguments")
    return compilers, links, original


def pilot(path):
    with ZipFile(path) as z:
        term = read(z, "terminal.json")
        identity = read(z, "signed-inventory.json")
        result = read(z, "qualified.json")
        need(term["sdk_wild"] == identity[WILD[1:]][0] ==
             "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5", "signed Wild")
        for arm in ("parent","candidate"):
            rebuilt = read(z, arm+"-binary.json")
            need(term["binaries"][arm] == rebuilt["binary"] and rebuilt["source_commit"] ==
                 "ed0ae15d22da9a0af9afb3d0fdeb4ceb8a71b770" and rebuilt["fingerprint_blob"] ==
                 {"parent":"744fe4399312463c19d418ef29ece87db9d67549",
                  "candidate":"2dfadab461c089ccda7dcf6108d07d6de521f511"}[arm], "physical inputs")
            for phase in ("cold-old","unchanged","first-provider","replace-provider","malformed",
                          "independent-full-owner-malformed","clean-OHM_NATIVE_A","clean-OHM_NATIVE_B","clean-absent"):
                unit, links, _ = physical(z, arm + "/" + phase)
                need(len(unit) == len(links) == 1, (arm,phase,"actual compiler and linker",len(unit),len(links)))
                args = unit[0][2]
                replay = "link-only" in args and any(a.endswith(".rlink") for a in args)
                expected = arm=="candidate" and phase in {"unchanged","first-provider","replace-provider","malformed"}
                need(replay == expected and "-lutil" in links[0][2], (arm,phase,"actual relink and native resolution"))
            for phase, code in (("rust-error","E0308"),("malformed","libutil.so"),
                                ("independent-full-owner-malformed","libutil.so"),("clean-bad","libutil.so")):
                rows = [json.loads(line) for line in gzip.decompress(z.read(arm+"/"+phase+"/stdout.gz")).splitlines()]
                raw = gzip.decompress(z.read(arm+"/"+phase+"/stderr.gz"))
                need(rows[-1] == {"reason":"build-finished","success":False} and
                     (code.encode() in raw or code in json.dumps(rows)), (arm,phase,"actual failure"))
            for tag in ("OHM_NATIVE_A","OHM_NATIVE_B","absent"):
                digest = result[arm]["providers"][tag][-1]
                expected = b"" if tag == "absent" else (tag+"\n").encode()
                need(digest == sha256(expected).hexdigest(), ("runtime bytes",arm,tag))
                prefix = arm + "/clean-" + tag
                need(gzip.decompress(z.read(prefix+"/program-stderr.gz")) == expected, "physical runtime stream")
                proof = read(z,prefix+"/program.json")
                if tag != "absent":
                    ctor = proof["constructor"]
                    need(ctor["symbol"] == "ohm_example_constructor_"+tag and ctor["address"] > 0 and
                         (ctor["direct"] or ctor["relocated"]), "native ELF .init_array membership")
                    opens = read(z,prefix+"/result.json")["native_opens"][EXAMPLE]
                    need(any(r[1].endswith("/libutil.so") for r in opens) and
                         any(r[1].endswith("/"+tag+".o") for r in opens),"physically opened native providers")
            for state in ("old","corrected"):
                raw = gzip.decompress(z.read(arm+"/"+state+"-behavior/case/stderr.gz"))
                need((b"panicked" in raw) == (state == "old"), ("upstream renderer semantics",arm,state))
        need(result["parent"]["providers"] == result["candidate"]["providers"], "cross-arm full image equality")
        return {"run":term["run"],"head":term["sha"],"binaries":term["binaries"],"boot":term["boot"]}


def effect(pairs):
    logs = [math.log(c/p) for p,c in pairs]
    mean = statistics.mean(logs)
    n = len(logs)
    extreme = sum(abs(statistics.mean(v*s for v,s in zip(logs,signs))) >= abs(mean)-1e-12
                  for signs in itertools.product((-1,1),repeat=n))
    # Six independent boots yield exactly 46,656 bootstrap draws and 64 sign flips.
    boot = sorted(1-math.exp(sum(sample)/n) for sample in itertools.product(logs,repeat=n))
    return {"reduction":1-math.exp(mean),"interval":[boot[int(.025*len(boot))],boot[int(.975*len(boot))]],
            "sign_randomization_p":extreme/2**n, "per_boot":[1-math.exp(v) for v in logs]}


def signed_images(z, path, state, rows, bank):
    refs=bank["families"][state]
    need(set(rows)==set(refs) and len(refs)==17 and all(v[0]in refs[k] and
         v[1]==bank["terminal"]["objects"][v[0]]["size"] for k,v in rows.items()),
         ("each entire executable matches signed input state",path,state))
    proof=read(z,path+"/"+state+"-validated.json")
    need(proof["images"]=={k:v[:2]for k,v in rows.items()} and proof["verdicts"]==bank["cases"][state],
         "authenticated exact state and behavior inventory")
    prefix=path+"/"+state+"-real-tests/"
    for name,expected in bank["cases"][state].items():
        raw=gzip.decompress(z.read(prefix+name+"/stdout.gz"))
        observed=sorted([a.decode(),b.decode()]for a,b in re.findall(
            rb"^test (.*?) \.\.\. (ok|FAILED|ignored)(?:[^\n]*)$",raw,re.M))
        need(expected["exit"]==0 and observed==expected["cases"] and b"test result: ok." in raw,
             ("original physical test case result",name,path,state))
    stdout=gzip.decompress(z.read(prefix+"renderer-stdout.gz"))
    stderr=gzip.decompress(z.read(prefix+"renderer-stderr.gz"))
    need(b"1 passed; 0 failed" in stdout and (b"panicked"in stderr)==(state=="old") and
         (state!="old" or b"index out of bounds"in stderr),"actual original caught panic / fixed render")


def prices(paths, confirmation=False, test_confirmation=False):
    need(not test_confirmation or confirmation,"test confirmation requires registered boot identity")
    scope="confirm-tests" if test_confirmation else "confirm-examples"
    workflows = (("tests",) if test_confirmation else ("examples",)) if confirmation else ("examples","tests")
    workers = []
    hosts = {}
    common = []
    for path in paths:
        with ZipFile(path) as z:
            term = read(z,"terminal.json")
            pos = term["position"]
            need(pos not in hosts and term["boot"] not in [v["boot"] for v in hosts.values()], "distinct boots")
            if confirmation:
                admission = read(z,"admission.json")
                job = read(z,"authenticated-worker.json")
                need(term["scope"]==scope and term["workflows"]==list(workflows) and
                     term["runner"]==admission["runner"]==job["runner_name"] and
                     term["boot"]==admission["boot"] and term["head"]==admission["head"]==job["head_sha"] and
                     int(term["run"])==admission["run"]==job["run_id"] and
                     pos==admission["position"] and term["cpus"]==admission["affinity"][:4] and
                     term["ordering"]==(["parent","candidate"] if pos%2 else ["candidate","parent"]) and
                     job["name"]==f"Matched Cargo {scope} ({pos})", "registration and physical assignment")
                workers.append({k:job[k] for k in ("id","runner_name","runner_id")})
            common.append([term[k] for k in ("head","run","signed","wild","cargo")])
            groups = {}
            if test_confirmation:
                bank=read(z,"signed-reference.json")
                need(bank["record"]==term["reference"] and len(bank["families"]["old"])==len(bank["families"]["new"])==17
                     and all(len(v)==(2 if k in ("test/formatter/True","test/ruff/True","test/rustc_tests/True") else 1)
                             for m in bank["families"].values()for k,v in m.items()),"preexisting complete signed family")
                common[-1].append(bank["record"])
                for arm in ("parent","candidate"):
                    for phase,state in (("old","old"),("edit","new"),("first-unchanged","new")):
                        name="immediate-"+arm+"-"+phase
                        raw=read(z,name+"/result.json")
                        refs=bank["families"][state]
                        values={k:v for k,v in raw["executables"].items()if k.startswith(("test/","example/"))}
                        lines=gzip.decompress(z.read(name+"/stdout.gz")).splitlines()
                        need(raw["returncode"]==0 and json.loads(lines[-1])=={"reason":"build-finished","success":True}
                             and set(values)==set(refs) and all(v[1] in refs[k] and v[2]==bank["terminal"]["objects"][v[1]]["size"]
                             for k,v in values.items()),"physical immediate OLD/NEW verdict before a later build")
            for workflow in workflows:
                for arm in ("candidate","parent"):
                    rows = []
                    trace = workflow + "-0-" + arm + "/traced-settled"
                    _, _, actual = physical(z, trace)
                    if workflow == "examples" or test_confirmation:
                        examples = []
                        for kind,_,args,_ in actual:
                            if kind == "wild" and "-o" in args:
                                examples.append(Path(args[args.index("-o")+1]).name)
                        images = read(z, workflow+"-0-"+arm+".json")["new_images"]
                        names = {k.split("/")[1] for k in images if k.startswith("example/")}
                        need(len(names)==12 and all(examples.count(name)==1 for name in names), "independent twelve native Wild links")
                        for name in names:
                            rustc, = [row[2] for row in actual if row[0]=="rustc" and "--crate-name" in row[2]
                                      and row[2][row[2].index("--crate-name")+1] == name]
                            need(("link-only" in rustc and any(v.endswith(".rlink") for v in rustc)) ==
                                 (arm=="candidate"), ("physical compile mode",workflow,arm,name))
                    for repeat in range(2):
                        label=workflow+"-"+str(repeat)+"-"+arm
                        r = read(z,label+".json")
                        need(r["arm"]==arm and r["workflow"]==workflow, "worker assignment")
                        if test_confirmation:
                            for state in ("old","new"):
                                signed_images(z,label,state,r[state+"_images"],bank)
                        phases = {}
                        for phase in ("cold","edit","first-unchanged","settled"):
                            count = read(z,label+"/"+phase+"-clock.json")
                            need(count["code"]==count["event_errno"]==0 and count["enabled"]==count["running"]>0
                                 and count["instructions"]==r["phases"][phase]["instructions"]>0, "raw PMU")
                            raw=gzip.decompress(z.read(label+"/"+phase+"-stdout.gz")).splitlines()
                            need(json.loads(raw[-1])=={"reason":"build-finished","success":True},"Cargo verdict")
                            phases[phase]=count["instructions"]
                        phases["edit+first"]=phases["edit"]+phases["first-unchanged"]
                        rows.append({"phases":phases,"new_storage":r["new_storage"],"cold_storage":r["cold_storage"],
                                     "images":r["new_images"]})
                    groups[(workflow,arm)] = rows
                clean = read(z,workflow+"-independent-new/result.json")["executables"]
                clean = {k:v[1:] for k,v in clean.items() if k.startswith("example/") or k.endswith("/True")}
                histories = groups[workflow,"parent"] + groups[workflow,"candidate"]
                if test_confirmation:
                    signed_images(z,workflow+"-independent-new","new",clean,bank)
                    need(all(all(h["images"][k][:2]==v and h["images"][k]==histories[0]["images"][k]
                                 for k,v in clean.items()if k.startswith("example/"))for h in histories),
                         "strict twelve real clean examples and natural outputs")
                else:
                    need(all({k:v[:2] for k,v in h["images"].items()}==clean for h in histories) and
                         all(h["images"]==histories[0]["images"] for h in histories), "clean matched bytes and behaviors")
            hosts[pos] = {"boot":term["boot"],"groups":groups}
    need(set(hosts)==set(range(1,7)) and all(x==common[0] for x in common), "six matched independent workers")
    if confirmation:
        need(all(len({v[k] for v in workers})==6 for k in ("id","runner_name","runner_id")),
             "six distinct authenticated VM assignments")
    answer = {}
    for workflow in workflows:
        measures = {}
        for phase in ("cold","edit","first-unchanged","settled","edit+first"):
            pairs = []
            for n in sorted(hosts):
                groups=hosts[n]["groups"]
                pairs.append([math.prod(item["phases"][phase] for item in groups[workflow,arm])**.5
                              for arm in ("parent","candidate")])
            measures[phase]=effect(pairs)
        storage = {}
        for snapshot in ("cold_storage","new_storage"):
            storage[snapshot] = {}
            for arm in ("parent","candidate"):
                values = [r[snapshot] for host in hosts.values() for r in host["groups"][workflow,arm]]
                name_map = dict(values[0], total=None)
                per_kind = {}
                for kind in name_map:
                    samples = ([v[kind] for v in values] if kind!="total" else
                               [[sum(row[i] for row in v.values()) for i in range(3)] for v in values])
                    per_kind[kind] = [[min(col),statistics.median(col),max(col)] for col in zip(*samples)]
                storage[snapshot][arm] = per_kind
        measures["storage_count_apparent_allocated_min_median_max"] = storage
        answer[workflow] = measures
    return answer


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("pilot","price","confirm-examples","confirm-tests"))
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps(pilot(args.files[0]) if args.mode=="pilot" else prices(args.files, args.mode.startswith("confirm-"), args.mode=="confirm-tests"), indent=2))
