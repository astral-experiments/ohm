"""Read only the closed structural event ledger. Nothing here is placed inside a counter window."""
from functools import cache
import gzip
import json
from pathlib import Path
import re
import stat
import subprocess
import sys

import bindings as b
from bindings import need
import kernel_contact as contact
import processes

GOLD = b.HERE / "kernel-rosters.json"


@cache
def readers(package):
    original = sys.path[:]
    try:
        sys.path[:0] = [str(package), str(package / "kernel")]
        import history
        import images
        import read_events
        need({Path(m.__file__).resolve() for m in (history, images, read_events)} ==
             {package / "history.py", package / "images.py", package / "kernel/read_events.py"}, "foreign structural reader")
        return history, images, read_events
    finally:
        sys.path[:] = original


def package():
    return Path(json.loads((contact.OUT / "binding.json").read_bytes())["source"])


def catalog(arm, registry, where):
    paths = {"cargo": b.SDK / "bin/cargo", "rustc": b.SDK / "bin/rustc", "wild": b.SDK / b.WILD,
             "proxy": b.PROXIES / "rustup", "sysld": Path("/usr/bin/ld")}
    record = {r: {"path": str(p), "resolved": str(p.resolve(strict=True)), "identity": [b.sha(p), *b.numbers(p)]}
              for r, p in paths.items()}
    for r in ("cargo", "rustc", "wild"):
        need(record[r]["identity"] == registry[arm[0]][str(paths[r].relative_to(b.SDK))], ("foreign active tool", arm, r))
    b.save(where / "catalog.json", record)
    manifest = json.loads((b.OUT / "sdk/manifest.json").read_bytes())
    path = b.SDK / manifest["driver"]
    loader = loader_driver(paths["rustc"], path, b.environment(arm), where)
    need(loader["driver_identity"] == registry[arm[0]][manifest["driver"]], "loader did not select the enrolled driver")
    b.save(where / "loader.json", loader)


def loader_driver(rustc, driver, env, where):
    def capture(label, args):
        data = subprocess.check_output(args, env=env, stderr=subprocess.STDOUT)
        with (where / ("loader-" + label + ".txt")).open("xb") as f:
            f.write(data)
        return data.decode()

    headers = capture("interpreter", ["/usr/bin/readelf", "-lW", rustc])
    interp, = re.findall(r"\[Requesting program interpreter: ([^\]]+)\]", headers)
    need(interp == "/lib64/ld-linux-x86-64.so.2", "unexpected enrolled GNU ELF interpreter")
    dyn = capture("needed", ["/usr/bin/readelf", "-dW", rustc])
    drivers = [d for d in re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", dyn) if d.startswith("librustc_driver-")]
    need(drivers == [driver.name], "rustc lacks the exact enrolled DT_NEEDED driver")
    listing = capture("resolved", [interp, "--list", rustc])
    selected, = re.findall(r"^\s*" + re.escape(driver.name) + r" => (\S+) \(0x[0-9a-f]+\)$", listing, re.MULTILINE)
    need(Path(selected).resolve(strict=True) == driver.resolve(strict=True), "alternate loader target")
    return {"interpreter": interp, "interpreter_sha256": b.sha(Path(interp)), "driver": selected,
            "driver_identity": [b.sha(driver), *b.numbers(driver)]}


def check_source(arm, env, enrolled, manifest, driver_id):
    role, sdk = arm[0], str(b.SDK)
    driver = manifest["driver"]
    need(enrolled["arm"] == arm and enrolled["role"] == role and enrolled["sdk"] == sdk
         and manifest["roles"][role]["commit"] == b.HEADS[role] and manifest["roles"][role]["compiler"] == b.COMPARE[role]
         and enrolled["source_manifest"] == b.spec()["manifest"]
         and env == enrolled["env"] == b.environment(arm) and env["LD_LIBRARY_PATH"] == str(b.SDK / "lib"),
         ("wrong phase compiler source, SDK, or dynamic search", arm))
    need(driver_id == enrolled["files"][driver] and driver_id[0] == manifest["files"][role][driver][0],
         ("wrong physical compiler driver", arm, driver))


def source(where, arm, env, stage):
    record = json.loads((where.parent / "arm.json").read_bytes())
    manifest_path = b.OUT / "sdk/manifest.json"
    need(b.sha(manifest_path) == b.spec()["manifest"], "different SDK source manifest")
    manifest = json.loads(manifest_path.read_bytes())
    path = b.SDK / manifest["driver"]
    driver = [b.sha(path), *b.numbers(path)]
    check_source(arm, env, record, manifest, driver)
    need(json.loads((where.parent / "loader.json").read_bytes())["driver_identity"] == driver,
         "active driver no longer matches the structural arm's dynamic loader")
    for row in json.loads((where.parent / "catalog.json").read_bytes()).values():
        p = Path(row["path"])
        need(str(p.resolve(strict=True)) == row["resolved"] and b.numbers(p) == row["identity"][1:],
             ("changed executable during this structural visit", p))
    proof = {"source": b.HEADS[arm[0]], "compiler_tree": b.COMPARE[arm[0]], "driver": str(path),
             "driver_identity": driver, "source_manifest": record["source_manifest"]}
    if stage == "after":
        need(proof == json.loads((where / "source-before.json").read_bytes()), "driver changed across ordinary invocation")
    b.save(where / ("source-" + stage + ".json"), proof)


def wrap(where, arm, env):
    source(where, arm, env, "before")
    return [str(contact.OBSERVER), str(where / "kernel.tsv"), "--"]


def preserve(where):
    path = where / "kernel.tsv"
    if path.is_file():
        processes.compact(path, where / "kernel.tsv.gz")


def timeout(where, error):
    for tag, data in (("stdout", error.stdout), ("stderr", error.stderr)):
        with (where / ("cargo.partial." + tag + ".gz")).open("xb") as out:
            out.write(gzip.compress(data or b"", compresslevel=2, mtime=0))
    preserve(where)


def phase_shape(roles, phase, history):
    if phase == "cold-A":
        shape = history.shapes(roles)
    else:
        shape = {"rustc": sorted([r["crate"], r["mode"], history.values(r["argv"], "--crate-type")] for r in roles["rustcs"]),
                 "wild_outputs": sorted(Path(r["output"]).name for r in roles["wild_processes"]),
                 "system_links": sorted(r["kind"] for r in roles["other_linkers"])}
    return {"sha256": history.digest(shape), "execs": roles["successful_exec_count"], "rustcs": len(roles["rustcs"]),
            "wild": roles["wild"], "system": len(roles["other_linkers"]), "wild_queries": len(roles["wild_queries"]),
            "cargo_queries": len(roles["cargo_queries"])}


def project(ledger, closed, catalog, arm, images, cargo_command):
    before, interrupted = images.predecessors(ledger, closed["sha256"])
    pins = {(r["identity"][1], r["identity"][2]): (name, r) for name, r in catalog.items()}
    need(len(pins) == len(catalog) == 5, "distinct pinned physical executables")
    root = closed["execs"][0]
    proxy = str(b.PROXIES / "cargo")
    need((root["ordinal"], root["lifetime"], root["execfn"], root["exe"], root["cwd"], root["argv"]) ==
         (1, 1, proxy, proxy, str(b.ROOT / "ruff"), cargo_command) and
         (root["image"]["dev"], root["image"]["ino"]) == tuple(catalog["proxy"]["identity"][1:3]) and
         root["ordinal"] not in interrupted, "the root did not successfully execute the enrolled Cargo proxy and arguments")
    rows = []
    for e in closed["execs"]:
        im = e["image"]
        role, enrolled = pins.get((im["dev"], im["ino"]), (None, None))
        args, path, proc = e["argv"], e["execfn"], e["exe"]
        if enrolled:
            need(stat.S_ISREG(im["mode"]) and [im["sha256"], im["dev"], im["ino"], im["mode"] & 0o7777, im["size"], images.ns(im["mtime"]),
                  images.ns(im["ctime"])] == enrolled["identity"], ("changed native image", role, e["ordinal"]))
            if role != "proxy":
                need(Path(e["cwd"]).is_absolute() and path == enrolled["path"] and proc == enrolled["resolved"]
                     and e["ordinal"] not in interrupted,
                     ("interrupted or unexpected native tool", role, path, proc))
            if role == "wild" and "-o" in args:
                need(args.count("-o") == 1, ("ambiguous Wild output", e["ordinal"]))
            if role == "rustc" and "--crate-name" in args and args[args.index("--crate-name") + 1] in {
                    "ruff", "ruff_python_parser", "ruff_python_ast"}:
                flags = [s for s in args if "ohm-branch-cache" in s or "ohm-check-relink-inputs" in s]
                want = ["-Zohm-check-relink-inputs"]
                if arm.endswith("on"):
                    want.append("-Zohm-branch-cache=yes")
                need(sorted(flags) == sorted(want), ("unexpected real rustc branch/native flags", arm, flags))
        names = {Path(s).name for s in (args[0], path, proc)}
        if "--crate-name" in args and "rustc" in names:
            need(role in ("rustc", "proxy"), ("foreign rustc", e["pid"], proc))
        if any(re.fullmatch(r"(?:[\w.]+-)*ld(?:\.bfd|\.lld|\.gold)?|rust-lld|wild|mold", x) for x in names):
            need(role in ("wild", "sysld"), ("foreign native linker", e["pid"], proc))
        rows.append((role, {"pid": e["pid"], "event": e["ordinal"], "lifetime": e["lifetime"], "image": im["id"],
                            "exe": path, "physical_exe": proc, "cwd": e["cwd"], "argv": args}))
    native = processes.classify(rows, arm)
    cargo = native["cargos"][0]["event"]
    compilers = {v["event"]: v for v in native["rustcs"]}
    def ancestor(sequence, allowed):
        initial = sequence
        while sequence:
            sequence = before[sequence]
            if sequence in allowed:
                return sequence
        raise ValueError(("no authenticated native ancestor", initial))
    ancestor(cargo, {root["ordinal"]})
    for row in native["rustcs"] + native["other_linkers"] + native["wild_queries"] + native["cargo_queries"]:
        ancestor(row["event"], {cargo})
    for row in native["wild_processes"]:
        parent = compilers[ancestor(row["event"], compilers)]
        row.update(rustc_event=parent["event"], rustc_crate=parent["crate"])
    return native


def inventory(where, arm, rc, env):
    source(where, arm, env, "after")
    history, images, reader = readers(package())
    path = where / "kernel.tsv"
    closed = reader.read(path, expected_code=rc)
    b.save(where / "lifecycle.json", {k: len(v) if isinstance(v, list) else v for k, v in closed.items()})
    with gzip.open(where / "cargo.json.gz") as f:
        invocation = json.load(f)
    need(invocation["observer_argv"] == [str(contact.OBSERVER), str(path), "--", *invocation["argv"]] and
         invocation["expected"] == invocation["exit"] == rc and invocation["env"] == env,
         "wrapped structural Cargo command or exit changed")
    native = project(path, closed, json.loads((where.parent / "catalog.json").read_bytes()), arm, images, invocation["argv"])
    expected = json.loads(GOLD.read_bytes())["off" if arm.endswith("off") else "on"][where.name]
    actual = phase_shape(native, where.name, history)
    b.save(where / "kernel-roster.json", {"expected": expected, "actual": actual, "raw": closed["sha256"]})
    if actual != expected:
        with gzip.open(where / "unadmitted-native-execs.json.gz", "xt") as f:
            json.dump(native, f, separators=(",", ":"))
    need(actual == expected, ("different real structural role/target roster", where.name, expected, actual))
    return native
