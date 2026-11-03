"""Price the normal compiler's native object writes from stopped, task-bound PMU fds."""
import ast
from collections import Counter, defaultdict
import csv
import hashlib
import os
from pathlib import Path
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
OBS = HERE / "observer.c"
H = lambda b: hashlib.sha256(b).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def ordinary_execs(trace, pattern):
    """Read actual executed files and argument bytes from the previous ordinary strace."""
    result = []
    for path in sorted(trace.glob("exec.*")):
        with path.open() as file:
            for line in file:
                line = line.rstrip()
                if not line.startswith(("execve(", "execveat(")) or not line.endswith("= 0"):
                    continue
                match = pattern.fullmatch(line)
                require(match, ("invalid successful strace exec", line[:150]))
                exe, args, _ = (ast.literal_eval(v) for v in match.groups())
                # The kernel exposes the executable identity after resolving the cargo symlink.
                st = Path(exe).stat()
                result.append((st.st_dev, st.st_ino, tuple(args)))
    require(result, "no original successful kernel executions")
    return result


def observed_execs(custody, *, read_counters=True):
    result = []
    totals = Counter()
    unusable = set()
    images = {}
    for line in (custody / "epochs.tsv").read_text().splitlines():
        v = line.split()
        if v[0] == "I":
            _, ident, group, tid, at, role = v
            raw = (custody / f"{int(ident):05}.nul").read_bytes().split(b"\0")
            require(raw[-1] == b"" and int(raw[0]) == int(group), "wrong kernel argv image")
            args = tuple(os.fsdecode(s) for s in raw[4:-1])
            images[int(ident)] = (int(group), int(raw[1]), int(raw[2]), os.fsdecode(raw[3]), args)
            if role == "exec":
                result.append((int(raw[1]), int(raw[2]), args))
        elif v[0] == "C":
            if not read_counters:
                continue
            _, ident, group, tid, value, enabled, running = map_record(v)
            if value or enabled or running:
                if not (enabled == running and running > 0):
                    unusable.add((ident, group, tid))
                totals[ident, group, tid] += value
        else:
            raise ValueError(("unknown custody record", v[0]))
    return result, totals, images, unusable


def map_record(row):
    return row[0], *map(int, row[1:])


def table(path):
    with path.open(newline="") as file:
        return list(csv.DictReader(file, delimiter="\t"))


def path_value(row, name):
    return os.fsdecode(bytes.fromhex(row[name]))


def prices(custody, expected, owner_identity, library_refs):
    """Pair stopped object-open and close counters, then bind every extent to the emitted ELF."""
    owners = table(custody / "owners.tsv")
    require(len(owners) == 1, ("expected one enrolled rustc", len(owners)))
    root, = owners
    image, pid = int(root["image"]), int(root["tgid"])
    require(tuple(int(root[k]) for k in ("dev","ino")) == owner_identity, "different owner image")
    events = table(custody / "windows.tsv")
    by = defaultdict(dict)
    for event in events:
        require(int(event["tgid"]) == pid, "window from another process")
        key = int(event["id"])
        require(event["event"] not in by[key], "duplicate window transition")
        by[key][event["event"]] = event
    digests = table(custody / "window-digests.tsv")
    digests_by_id = {int(x["id"]): x for x in digests}
    require(len(digests) == len(digests_by_id), "duplicate object digest")
    _, task_totals, _, unusable = observed_execs(custody)
    out, refs = {}, set()
    for key, phases in sorted(by.items()):
        enter = phases["open-enter"]
        opened = phases["open-exit"]
        if int(opened["result"]) < 0:
            require(set(phases) == {"open-enter","open-exit"} and key not in digests_by_id, "failed open produced an object")
            continue
        if enter["kind"] in {"llvm","driver"}:
            file = Path(path_value(opened, "resolved_hex"))
            want = library_refs[enter["kind"]]
            if (int(opened["dev"]),int(opened["ino"])) == tuple(want["id"][:2]):
                require(str(file) == want["opened"], "different library path from the qualified run")
                refs.add(enter["kind"])
            continue
        require(enter["kind"] == "object", "unknown traced opening")
        require(set(phases) == {"open-enter","open-exit","close-enter","close-exit"}, "incomplete object interval")
        closing, closed = phases["close-enter"], phases["close-exit"]
        transitions = [enter, opened, closing, closed]
        tid = int(enter["tid"])
        require(all(int(x["tid"]) == tid and int(x["image"]) == image for x in transitions), "object crosses tasks or images")
        require(all(int(b["monotonic_ns"]) >= int(a["monotonic_ns"]) for a,b in zip(transitions,transitions[1:])), "nonmonotonic transitions")
        require(int(opened["result"]) == int(closing["fd"]) and int(closed["result"]) == 0, "unsuccessful object close")
        raw_path = Path(path_value(opened,"resolved_hex"))
        ds = digests_by_id.pop(key)
        require((int(ds["dev"]),int(ds["ino"])) == (int(opened["dev"]),int(opened["ino"])) and int(ds["bytes"]) > 0, "file changed during object interval")
        same = [u for u,digest in expected.items() if digest == ds["sha256"]]
        require(len(same) == 1, ("object does not match a unique genuine compiled unit", str(raw_path), ds["sha256"]))
        name, = same
        require(name in raw_path.name and name not in out, ("ambiguous native unit name",name,str(raw_path)))
        require(int(enter["flags"]) & (os.O_WRONLY | os.O_RDWR) and int(enter["flags"]) & os.O_CREAT, "not actual output creation")
        vals = [int(closing[k])-int(opened[k]) for k in ("value","enabled","running")]
        require(vals[0] > 0 and vals[1] == vals[2] > 0, "unscheduled or multiplexed object interval")
        require((image,pid,tid) not in unusable, "invalid worker PMU schedule")
        total = task_totals[image, pid, tid]
        require(total >= vals[0], "object cost exceeds its worker's valid instructions")
        out[name] = {"native_instructions": vals[0], "worker_instructions": total, "tid":tid,
                     "output":str(raw_path), "object":ds["sha256"], "bytes":int(ds["bytes"]),
                     "enabled_ns":vals[1], "window":key}
    require(not digests_by_id and set(out) == set(expected) and refs == set(library_refs).intersection({"driver","llvm"}),
            ("incomplete genuine windows",sorted(set(expected)-set(out)), sorted(set(out)-set(expected)), sorted(refs)))
    require(len({v["tid"] for v in out.values()}) == len(out), "two modules share one backend worker")
    return out


def archive_custody(directory, dest):
    with tarfile.open(dest, "w:gz") as tar:
        for path in sorted(directory.iterdir()):
            if path.is_file() and (path.name.endswith((".nul",".tsv",".json"))):
                require(path.stat().st_size < 16 << 20, "oversized evidence")
                tar.add(path, arcname=path.name, recursive=False)


def calibrate(binary, out, save):
    """Check two real worker fds, distinct object identities, and a failed open before the Ruff edit."""
    root = out / "window-calibration"
    root.mkdir()
    logs = root / "epochs"
    logs.mkdir()
    exe = root / "calibration"
    subprocess.run(["/usr/bin/cc","-std=gnu11","-O2","-Wall","-Wextra","-Werror","-pthread",
                    HERE/"calibrate-windows.c","-o",exe], check=True)
    subprocess.run([binary,logs,"--owner-exe",exe,"--crate-name","window_calibration","--",exe,
                    "--crate-name","window_calibration",root], check=True, timeout=45)
    st = exe.stat()
    expected = {k:H((root/(k+".o")).read_bytes()) for k in ("window_short","window_long")}
    rows = prices(logs,expected,(st.st_dev,st.st_ino),{})
    ratio = rows["window_long"]["native_instructions"] / rows["window_short"]["native_instructions"]
    require(3.90 < ratio < 4.10 and rows["window_short"]["tid"] != rows["window_long"]["tid"],
            ("calibration counted the wrong worker or interval",ratio))
    require(any(r["event"] == "open-exit" and int(r["result"]) < 0 and
                path_value(r,"path_hex").endswith("nonexistent/refused.o") for r in table(logs/"windows.tsv")),
            "failed calibration write was lost")
    save(out/"calibration.json",{"rows":rows,"ratio":ratio,"observer":H(binary.read_bytes()),
                                "observer_source":H(OBS.read_bytes()),"calibration":H(exe.read_bytes())})
    archive_custody(logs,out/"calibration-custody.tar.gz")


def prepare(out, save):
    """Compile the frozen observer and exercise both hardware tasks before building Ruff."""
    binary = out / "observe-native"
    subprocess.run(["/usr/bin/cc","-std=gnu11","-O2","-Wall","-Wextra","-Werror",OBS,"-lcrypto","-o",binary],check=True)
    calibrate(binary, out, save)


def observe(prior, kit, loc, work, repo, env, cmd, suite, graph, which, extras, gold, baseline, reference, out, expected, elf_members, save):
    exe = Path(env["CARGO_TARGET_DIR"]).parent
    require(exe == work and not {"RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER","RUSTFLAGS"}.intersection(env), "nonordinary compiler environment")
    loc.mkdir()
    (loc / "native").mkdir()
    custody = loc / "custody"
    custody.mkdir()
    native = kit.sdk / "bin/rustc"
    binary = out / "observe-native"
    try:
        argv = [str(binary),str(custody),"--owner-exe",str(native),"--crate-name","ruff_workspace","--",*cmd]
        code = prior.guards.run(argv,repo,env,loc,work,loc,timeout=3000)
        require(code == 0, ("ordinary instrument-free Cargo command failed",code,(loc/"outer.stderr").read_bytes()[-700:]))
        plain = ordinary_execs(loc.parent/"new"/"trace", prior.support.EXEC)
        observed, _, _, _ = observed_execs(custody, read_counters=False)
        require(Counter(plain) == Counter(observed),
                ("different genuine execs/argv",[(r[2][:4],n) for r,n in (Counter(plain)-Counter(observed)).items()],[(r[2][:4],n) for r,n in (Counter(observed)-Counter(plain)).items()]))
        root_args = tuple(baseline["root_argv"][0][1])
        st = native.stat()
        require(observed.count((st.st_dev,st.st_ino,root_args)) == 1 and len(baseline["root_argv"])==1, "different genuine root compiler")
        cargo = prior.replay.cargo_rows((loc / "outer.stdout").read_bytes())
        ar = prior.study.artifact(prior.study.results(cargo,True),prior.study.OWNER)
        physical = elf_members(ar, reference)
        probe = prior.pilot.phase_checks(suite,cargo,graph,work,repo,env,which,loc,extras,kit.evidence/"native-bodies",gold)
        for k in ("elf","verdict","owner_archive","inventory","dirty"):
            require(probe[k]==baseline[k], ("changed normal compiler/consumer result",k))
        save(out/"record.json",{"sources":expected["source"],"ordinary_argv":baseline["root_argv"],"execs":len(observed),
             "native":len(physical),"verdict":probe["verdict"],"elf":probe["elf"],"archive":probe["owner_archive"]})
        libs = {}
        for row in table(custody/"windows.tsv"):
            kind = row["kind"]
            if kind not in ("driver","llvm") or row["event"] != "open-exit" or int(row["result"]) < 0:
                continue
            target = kit.refs[kit.active][kind]
            if (int(row["dev"]), int(row["ino"])) != tuple(target["id"][:2]):
                continue
            path = Path(path_value(row,"resolved_hex"))
            state = path.stat()
            require((state.st_dev,state.st_ino)==tuple(target["id"][:2]) and H(path.read_bytes())==target["sha"], "different signed library body")
            require(kind not in libs or libs[kind]["opened"]==str(path), "conflicting opened library names")
            libs[kind] = dict(target,opened=str(path))
        require(set(libs)=={"llvm","driver"}, "both real libraries must be opened by the enrolled rustc")
        save(out/"native-inputs.json",{"custody":str(custody),"libraries":libs,
             "owner":[st.st_dev,st.st_ino],"expected":{u:reference[u] for u in expected["dirty"]},
             "files":{p.name:H(p.read_bytes()) for p in sorted(custody.iterdir()) if p.is_file()}})
    finally:
        archive_custody(custody,out/"native-window-custody.tar.gz")


def finalize(out, save):
    """Open the hardware prices only after ordinary cold, edit, unchanged and repair controls."""
    import json
    state = json.loads((out/"native-inputs.json").read_bytes())
    custody = Path(state["custody"])
    require(state["files"] == {p.name:H(p.read_bytes()) for p in sorted(custody.iterdir()) if p.is_file()},
            "per-task evidence changed during the remaining Cargo history")
    rows = prices(custody,state["expected"],tuple(state["owner"]),state["libraries"])
    save(out/"counts.json",{"scope":"retired user instructions between successful creation and close of the matching native ELF",
         "units":rows,"native_total":sum(x["native_instructions"] for x in rows.values()),
         "worker_total":sum(x["worker_instructions"] for x in rows.values()),
         "original_evidence":H((out/"native-window-custody.tar.gz").read_bytes())})
