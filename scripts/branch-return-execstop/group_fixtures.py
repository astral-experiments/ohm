"""Acquire or independently reopen schema-2 kernel fixtures, with no hardware counter."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fixtures
import group_checks as checks

CASES = (("racing-1", "group", 4), ("racing-2", "group", 4),
         ("active", "group", 1), ("wild", "wild", 0), ("pending", "pending", 0))
CODES = dict(family=23, thread=37, duplicate=19, abort=13, signals=14, long=0)
HISTORY = HERE / "group-v2/history"
need = checks.need
sha = fixtures.digest

def encoded(result):
    return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()

def save(path, value):
    with path.open("xb") as stream:
        stream.write(encoded(value))

def read(path):
    return json.loads(path.read_bytes())

def source_files():
    return sorted([p for p in (HERE / "kernel").iterdir() if p.is_file()] +
                  [HERE / s for s in ("fixtures.py", "group_checks.py", "group_fixtures.py", "test_projection.py",
                                      "group-v2/group.c", "group-v2/pending.c", "group-v2/start.s",
                                      "group-v2/history/v1_reader.py")])

def identity(path):
    path = Path(path)
    before = path.stat()
    digest = sha(path)
    after = path.stat()
    def fields(st):
        return (st.st_dev, st.st_ino, st.st_size, st.st_mode, st.st_mtime_ns, st.st_ctime_ns)
    need(fields(before) == fields(after), "physical file changed during enrollment")
    def timestamp(ns):
        sec, frac = divmod(ns, 10**9)
        return f"{sec}.{frac:09}"
    return dict(resolved=str(path.resolve(strict=True)), dev=after.st_dev, ino=after.st_ino,
                size=after.st_size, mode=after.st_mode, sha256=digest,
                mtime=timestamp(after.st_mtime_ns), ctime=timestamp(after.st_ctime_ns))

def capture(stem, argv, expected, env=None):
    argv = list(map(str, argv))
    save(stem.with_suffix(".command.json"), {"argv":argv, "cwd":os.getcwd()})
    with stem.with_suffix(".stdout").open("xb") as out, stem.with_suffix(".stderr").open("xb") as err:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=env, timeout=60)
    save(stem.with_suffix(".terminal.json"), {"status":p.returncode})
    need(p.returncode == expected, (stem.name, expected, p.returncode))

def check_command(stem, argv, returncode):
    need(read(stem.with_suffix(".command.json"))["argv"] == list(map(str, argv)) and
         read(stem.with_suffix(".terminal.json")) == {"status":returncode}, ("wrong command/status", stem.name))

def helper_builds(cc, tools, source):
    return [(name, [cc, "-O2", "-Wall", "-Wextra", "-Werror", "-pthread", str(source / (name + ".c")),
                    "-o", str(tools / name)]) for name in ("group", "pending")] + [
        ("start", [cc, "-c", str(source / "start.s"), "-o", str(tools / "start.o")])]

def args(name, program, cycles, root, tools, wild):
    if program == "wild":
        return [str(wild), str(tools / "start.o"), "-o", str(root / "linked.elf")]
    if program == "group":
        return [str(tools / "group"), str(cycles)]
    return [str(tools / "pending")]

def acquire(tools, out, wild):
    tools, out, wild = map(lambda p:p.absolute(), (tools, out, wild))
    need(platform.system() == "Linux" and platform.machine() == "x86_64" and wild.is_absolute()
         and sha(wild) == checks.WILD, "requires native Linux x86-64 and authenticated stock Wild")
    affinity = sorted(os.sched_getaffinity(0))
    need(len(affinity) >= 2 and not tools.exists() and not out.exists(), "requires two CPUs and fresh fixture paths")
    # Restrict only this unscored fixture process and its private children.
    os.sched_setaffinity(0, affinity[:2])
    # The inherited suite creates OUT itself. Preserve the exact binaries and
    # source even if it stops early and cannot produce its successful receipt.
    try:
        fixtures.main(tools, out)
    finally:
        if out.is_dir():
            root = out / "group-v2"
            root.mkdir()
            source = root / "source"
            for f in source_files():
                dest = source / f.relative_to(HERE)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
            hist = root / "history"
            hist.mkdir()
            for pos in checks.HISTORY:
                shutil.copyfile(HISTORY / (pos + ".tsv.gz"), hist / (pos + ".tsv.gz"))
            for name in ("observe", "fixture"):
                if (tools/name).is_file() and not (out/(name+".elf")).exists():
                    shutil.copy2(tools/name, out/(name+".elf"))
    cc = Path(shutil.which("cc")).resolve(strict=True)
    for name, argv in helper_builds(str(cc), tools, source / "group-v2"):
        capture(root / ("build-" + name), argv, 0)
    for name in ("group", "pending", "start.o"):
        shutil.copy2(tools / name, root / name)
    idents = {name:identity(path) for name, path in (("cc", cc), ("true", Path("/usr/bin/true")),
              ("observe", tools/"observe"), ("fixture", tools/"fixture"), ("group", tools/"group"),
              ("pending", tools/"pending"), ("wild", wild))}
    facts = dict(boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(), kernel=platform.release(),
                 machine=platform.machine(), uid=os.getuid(), cpus=sorted(os.sched_getaffinity(0)),
                 out=str(out), tools=str(tools), wild=str(wild), identities=idents)
    save(root / "host.json", facts)
    capture(root / "compiler-version", [cc, "--version"], 0)
    for name, program, cycles in CASES:
        stem = root / name
        env = os.environ.copy()
        env.pop("FIXTURE_RACING_THREAD_EXIT", None)
        if name.startswith("racing"):
            env["FIXTURE_RACING_THREAD_EXIT"] = "1"
        command = args(name, program, cycles, root, tools, wild)
        capture(stem, [tools/"observe", stem.with_suffix(".tsv"), "--", *command], 125 if program == "pending" else 0, env)
        if program == "wild":
            capture(root/"run-linked", [root/"linked.elf"], 37)
    for name, historic in idents.items():
        need(identity(Path(historic["resolved"])) == historic, ("changed during actual run", name))
    save(root/"qualified.json", replay(out))

def replay(out):
    root = out / "group-v2"
    sources = {}
    for f in source_files():
        rel = f.relative_to(HERE)
        sources[str(rel)] = sha(f)
        need(sha(root/"source"/rel) == sources[str(rel)], ("wrong retained source", rel))
    facts = read(root/"host.json")
    ident = facts["identities"]
    need(str(uuid.UUID(facts["boot"])) == facts["boot"] and facts["uid"] != 0 and facts["machine"] == "x86_64"
         and len(set(facts["cpus"])) == 2 and facts["kernel"] and ident["wild"]["sha256"] == checks.WILD,
         "wrong native host or stock linker")
    original = read(out/"qualified.json")
    need(original["qualified"] is True and original["cc_sha256"] == ident["cc"]["sha256"]
         and original["cc"] == ident["cc"]["resolved"] and original["observer_sha256"] == ident["observe"]["sha256"]
         and original["sources"] == {Path(k).name:v for k,v in sources.items() if k.startswith("kernel/")},
         "inherited observer, C compiler or source mismatch")
    need(all(sha(p) == ident[role]["sha256"] for p,role in ((out/"observe.elf","observe"),(out/"fixture.elf","fixture"),
                                                              (root/"group","group"),(root/"pending","pending"))),
         "retained native bodies differ")
    oldraw = out / "original"
    need({p.name:sha(p) for p in sorted(oldraw.iterdir())} == original["originals"], "inherited originals changed")
    result = json.loads(subprocess.check_output([sys.executable, "-IB", HERE/"kernel/qualify.py", "cases", oldraw]))
    need(result.pop("live_physical_reopen") is False and original["native"] == result | {"live_physical_reopen":True}
         and len(result["mutations_rejected"]) == 16 and len(result["negative"]) == 2 and set(result["positive"]) == set(CODES),
         "inherited native controls or mutation refusal changed")
    for name, code in CODES.items():
        positive = checks.reader.read(oldraw/(name+".tsv"), expected_code=code, expected_schema=2)
        need(positive["sha256"] == result["positive"][name]["sha256"], "legacy schema or wrong inherited ledger")
    projection = json.loads(subprocess.check_output([sys.executable, "-IB", HERE/"test_projection.py"]))
    need(projection == original["ruff_projection"] and len(projection["refusals"]) == 12, "native projection mismatch")
    past = checks.prior(root/"history")
    root_path = Path(facts["out"]) / "group-v2"
    tools = Path(facts["tools"])
    need(root_path.is_absolute() and tools.is_absolute() and ident["observe"]["resolved"] == str(tools/"observe"),
         "observer path differs from registered tools")
    for name, cmd in helper_builds(ident["cc"]["resolved"], tools, root_path/"source/group-v2"):
        check_command(root/("build-"+name), cmd, 0)
    check_command(root/"compiler-version", [ident["cc"]["resolved"], "--version"], 0)
    version = (root/"compiler-version.stdout").read_text().strip()
    need(bool(version) and not (root/"compiler-version.stderr").read_bytes(), "missing native C compiler version")
    raw_status = read(oldraw/"run.json")
    need({k:v["status"] for k,v in raw_status.items()} == CODES | {"escape":125, "escape3":125}, "inherited child statuses")
    native = {}
    for name, program, cycles in CASES:
        stem=root/name
        command = args(name, program, cycles, root_path, tools, facts["wild"])
        check_command(stem, [tools/"observe", (root_path/name).with_suffix(".tsv"), "--", *command], 125 if program == "pending" else 0)
        raw, stdout, stderr = [stem.with_suffix(s).read_bytes() for s in (".tsv",".stdout",".stderr")]
        if program == "pending":
            negative = checks.pending(raw, stdout, stderr, command, ident["pending"])
        else:
            need(not stderr, "unexpected successful fixture diagnostic")
            native[name] = checks.positive(raw, stdout, program, command, ident)
    check_command(root/"run-linked", [root_path/"linked.elf"], 37)
    need(sha(root/"linked.elf") == checks.OUTPUT and not (root/"run-linked.stdout").read_bytes()
         and not (root/"run-linked.stderr").read_bytes(), "wrong linked native output or verdict")
    mutations = checks.mutations((root/"active.tsv").read_bytes())
    # Bind every acquired source, executable, command, stream and partial event byte.
    originals = {str(p.relative_to(out)):sha(p) for p in sorted(out.rglob("*"))
                 if p.is_file() and p != root/"qualified.json"}
    return dict(schema=2, qualified=True, boot=facts["boot"], kernel=facts["kernel"], cpus=facts["cpus"],
                cc_sha256=ident["cc"]["sha256"], cc_version=version, observer_sha256=ident["observe"]["sha256"],
                stock_wild_sha256=checks.WILD, linked_elf_sha256=checks.OUTPUT, sources=sources, native=native,
                inherited_sha256=sha(out/"qualified.json"), pending_exec_refused=negative, historical_refusals=past,
                mutations_rejected=mutations, originals=originals)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="cmd", required=True)
    run = subs.add_parser("run")
    for k in ("tools","out","wild"):
        run.add_argument(k, type=Path)
    subs.add_parser("reopen").add_argument("out", type=Path)
    a=parser.parse_args()
    if a.cmd == "run":
        acquire(a.tools, a.out, a.wild)
    else:
        answer=encoded(replay(a.out))
        need(answer == (a.out/"group-v2/qualified.json").read_bytes(), "retained qualified receipt differs from raw replay")
        sys.stdout.buffer.write(answer)
