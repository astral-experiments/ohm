"""Exercise real generic providers with the supplied Linux Rust SDK and ordinary offline Cargo."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
CRATES = ("mono_api", "mono_left", "mono_right", "mono_consumer")
PROVIDERS = CRATES[1:3]
CARGO = ["cargo", "+ohm", "build", "--locked", "--offline", "-p", "mono_consumer", "--bin", "mono_client", "-j2", "--message-format=json"]
SIGNED_CARGO = "3ce4e300d4463dfc769b6c18e138d1c951b02dfb15416a39cb5301303d168871"
NAMES = {
    "target": "mono_api::fold_value::<u32>",
    "unrelated": "mono_api::fold_value::<u64>",
    "drop": "core::ptr::drop_glue::<mono_api::Envelope<mono_api::Record>>",
    "unrelated_drop": "core::ptr::drop_glue::<mono_api::Envelope<(mono_api::Record,u16)>>",
}
LABELS = {}
GIB = 1 << 30

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def store(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")

def filled(path):
    if path.exists():
        require(path.is_dir() and not path.is_symlink() and not any(path.iterdir()), f"need a fresh empty directory: {path}")
    else:
        path.mkdir(parents=True)

def mem_remaining():
    lines = Path("/proc/meminfo").read_text().splitlines()
    available = int(next(line for line in lines if line.startswith("MemAvailable:")).split()[1]) * 1024
    # The cgroup-v2 root can be a delegated namespace. Check our cgroup and its visible ancestors.
    mount = Path("/sys/fs/cgroup")
    memberships = Path("/proc/self/cgroup").read_text().splitlines()
    for row in memberships:
        ident, ctrls, rel = row.split(":", 2)
        if ident == "0" and not ctrls:
            base = mount
            names = ("memory.max", "memory.current")
        elif "memory" in ctrls.split(","):
            base = mount / "memory"
            names = ("memory.limit_in_bytes", "memory.usage_in_bytes")
        else:
            continue
        here = (base / rel.lstrip("/")).resolve()
        for directory in (here, *here.parents):
            if directory != base and base not in directory.parents:
                continue
            limit, usage = (directory / n for n in names)
            if limit.is_file() and usage.is_file():
                cap = limit.read_text().strip()
                if cap != "max":
                    available = min(available, int(cap) - int(usage.read_text().strip()))
    return available

def command(argv, env, work, out, prefix, timeout=180):
    deadline = time.monotonic() + 120
    while mem_remaining() < 8.5 * GIB:
        require(time.monotonic() < deadline, "less than 8.5 GiB available at admission")
        time.sleep(2)
    require(min(shutil.disk_usage(work).free, shutil.disk_usage(out).free) >= GIB, "less than 1 GiB spare disk")
    lowest = mem_remaining()
    with (out / (prefix + ".stdout")).open("wb") as stdout, (out / (prefix + ".stderr")).open("wb") as stderr:
        p = subprocess.Popen(argv, cwd=work, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        start = time.monotonic()
        try:
            while p.poll() is None:
                lowest = min(lowest, mem_remaining())
                require(lowest >= 8 * GIB, "8 GiB runtime floor reached")
                require(time.monotonic() - start < timeout, f"process exceeded {timeout}s")
                time.sleep(0.12)
        finally:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
    return {"returncode": p.returncode, "min_available_bytes": lowest, "argv": argv}

def native_members(archive):
    require(archive.stat().st_size < 32 << 20, f"unexpected local rlib size: {archive}")
    names = subprocess.check_output(["ar", "t", archive]).decode().splitlines()
    require(len(names) == len(set(names)) and "lib.rmeta" in names, "unexpected rlib contents")
    require(all("/" not in n and n not in ("", ".", "..") for n in names), "nonlocal archive member")
    return {n: subprocess.check_output(["ar", "p", archive, n]) for n in names}

def object_id(crate, name):
    match = re.fullmatch(re.escape(crate) + r"-[0-9a-f]{16}\.([a-z0-9]{25})\.(?:[a-z0-9]{7}\.)?rcgu\.o", name)
    require(match, f"unregistered Cargo codegen member: {name}")
    return match[1]

def tool_names(names):
    missing = sorted(set(names) - LABELS.keys())
    if missing:
        raw = subprocess.check_output(["c++filt", "-s", "rust"], input=("".join(n + "\n" for n in missing)).encode())
        results = raw.decode().splitlines()
        require(len(missing) == len(results), "incomplete Rust demangling")
        LABELS.update(zip(missing, results))
    return {n: LABELS[n] for n in names}

def normal(label):
    return "".join(re.sub(r"\[[0-9a-f]+\]", "", label).split())

def object_evidence(path):
    require(path.read_bytes()[:6] == b"\x7fELF\x02\x01", f"need little-endian ELF64: {path}")
    symbols = []
    for line in subprocess.check_output(["nm", "-P", path]).decode().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("_R") and "mono_" in parts[0]:
            symbols.append((parts[0], parts[1]))
    relocs = []
    section = None
    for line in subprocess.check_output(["readelf", "-Wr", path]).decode().splitlines():
        if line.startswith("Relocation section '"):
            section = line.split("'", 2)[1].removeprefix(".rela")
            continue
        if not section or not section.startswith((".text", ".data.rel.ro", ".rodata")):
            continue
        parts = line.split()
        if len(parts) < 5 or not re.fullmatch("[0-9a-f]+", parts[0]) or not parts[2].startswith("R_"):
            continue
        symbol = parts[4].removeprefix(".text.")
        if not symbol.startswith("_R") or "mono_" not in symbol:
            continue
        addend = 0
        if len(parts) > 5:
            require(len(parts) == 7 and parts[5] in ("+", "-"), f"unrecognized readelf addend: {line}")
            addend = int(parts[6], 16) * (-1 if parts[5] == "-" else 1)
        relocs.append((symbol, {"section": section, "offset": int(parts[0], 16), "type": parts[2], "addend": addend}))
    labels = tool_names([name for name, _ in symbols + relocs])
    kinds = {label: key for key, label in NAMES.items()}
    def selected(raw):
        return kinds.get(normal(labels[raw]))
    definitions = [{"kind": selected(n), "symbol": n, "binding": b} for n, b in symbols if selected(n) and b in ("T", "W", "t")]
    references = [{"kind": selected(n), "symbol": n, **r} for n, r in relocs if selected(n)]
    ids = {}
    for n, b in symbols:
        if b not in ("T", "W"):
            continue
        m = re.fullmatch(r"(mono_left|mono_right)\[([0-9a-f]+)\]::anchor", labels[n])
        if m:
            ids[m[1]] = m[2]
    return {"sha256": file_sha(path), "bytes": path.stat().st_size, "definitions": definitions, "references": references, "provider_ids": ids}

def source_state(src, state):
    template = HERE / "source"
    body = (template / "mono_api/src/lib.rs").read_text()
    needle = "x.wrapping_mul(3).wrapping_add(std::mem::size_of::<T>() as u32).wrapping_add(7)"
    require(body.count(needle) == 1, "changed generic body fixture")
    replacement = '"wrong result type"' if state["body"] == "error" else needle.replace("wrapping_add(7)", f"wrapping_add({state['body']})")
    files = {"mono_api/src/lib.rs": body.replace(needle, replacement)}
    for provider in PROVIDERS:
        name = provider + "/src/lib.rs"
        contents = (template / name).read_text()
        if provider in state["owners"]:
            contents += (HERE / "offer-target.rs").read_text()
        if state["unrelated"] and provider == "mono_right":
            contents += (HERE / "offer-unrelated.rs").read_text()
        files[name] = contents
    for name, text in files.items():
        path = src / name
        if path.read_text() != text:
            path.write_text(text)
    return {str(p.relative_to(src)): file_sha(p) for p in sorted(src.rglob("*")) if p.is_file()}

def state(name, owners=(), unrelated=False, body=7):
    return {"name": name, "owners": list(owners), "unrelated": unrelated, "body": body}

def analyze(src, env, out, spec, work):
    result = {"state": spec, "source": source_state(src, spec)}
    execution = command(CARGO, env, src, out, "cargo")
    messages = [json.loads(line) for line in (out / "cargo.stdout").read_bytes().splitlines() if line]
    artifacts = {m["target"]["name"]: m for m in messages if m.get("reason") == "compiler-artifact"}
    finished = [m["success"] for m in messages if m.get("reason") == "build-finished"]
    errors = [(m["target"]["name"], m["message"].get("code", {}).get("code")) for m in messages if m.get("reason") == "compiler-message" and m["message"]["level"] == "error" and m["message"].get("code")]
    result.update(cargo=execution, errors=errors, fresh={k: a["fresh"] for k, a in artifacts.items()})
    if spec["body"] == "error":
        require(execution["returncode"] == 101 and finished == [False] and errors == [("mono_api", "E0308")] and "mono_client" not in artifacts, "unexpected failed build verdict")
        return result, {}
    require(execution["returncode"] == 0 and finished == [True] and not errors and set(artifacts) == {*CRATES, "mono_client"}, f"unexpected successful build verdict: {finished}, {errors}, {set(artifacts)}")
    binary = Path(artifacts["mono_client"]["executable"]).resolve(strict=True)
    require(binary.is_relative_to(work), "linked binary escaped the private workspace")
    output = {}
    for x in (2, 17):
        value = subprocess.check_output([binary, str(x)], env=env, timeout=10).decode().strip()
        require(value == f"{5*x + 7 + spec['body']} {x+1}", f"incorrect linked behavior: {x}, {value}")
        output[x] = value
    units = {}
    archives = {}
    provider_ids = {}
    for crate in CRATES:
        found = [Path(p).resolve(strict=True) for p in artifacts[crate]["filenames"] if p.endswith(".rlib")]
        require(len(found) == 1 and found[0].is_relative_to(work), f"invalid private rlib for {crate}")
        archives[crate] = found[0]
        objdir = out / "objects" / crate
        objdir.mkdir(parents=True)
        units[crate] = {}
        for member, data in native_members(found[0]).items():
            if not member.endswith(".o"):
                continue
            key = object_id(crate, member)
            require(key not in units[crate], f"duplicate CGU: {key}")
            p = objdir / (key + ".o")
            p.write_bytes(data)
            unit = object_evidence(p)
            units[crate][key] = unit
            for k, v in unit["provider_ids"].items():
                require(k == crate and k not in provider_ids, "ambiguous stable crate ID")
                provider_ids[k] = v
        require(units[crate], f"no physical native code for {crate}")
    require(set(provider_ids) == set(PROVIDERS) and len(set(provider_ids.values())) == 2, "could not distinguish the two signed provider identities")
    owners = spec["owners"]
    winner = min(owners, key=lambda n: int(provider_ids[n], 16)) if owners else "mono_consumer"
    selected = {}
    for kind in ("target", "drop", "unrelated", "unrelated_drop"):
        available = collections.defaultdict(list)
        uses = []
        for crate, group in units.items():
            for cgu, unit in group.items():
                for item in unit["definitions"]:
                    if item["kind"] == kind and item["binding"] in ("T", "W"):
                        available[crate].append(item["symbol"])
                if crate == "mono_consumer":
                    uses.extend({"cgu": cgu, **r} for r in unit["references"] if r["kind"] == kind)
        if kind.startswith("unrelated"):
            wanted = {"mono_right"} if spec["unrelated"] else set()
            require(set(available) == wanted and not uses, f"unrelated {kind} leaked or disappeared: {available}, {uses}")
            continue
        require(set(available) == (set(owners) if owners else {"mono_consumer"}), f"wrong physical {kind} definitions: {available}")
        require(all(len(v) == 1 for v in available.values()) and len({v[0] for v in available.values()}) == len(available), f"ambiguous owner-qualified {kind}")
        use = available[winner][0]
        require(bool(uses) and all(r["symbol"] == use for r in uses), f"consumer did not use minimum stable {kind} provider: {uses}, {available}")
        require(use.encode() in binary.read_bytes(), f"final linked binary lacks selected {kind}")
        selected[kind] = {"winner": winner, "available": dict(available), "raw": use, "consumer_relocations": uses}
    result.update(cli_sha256=file_sha(binary), cli_bytes=binary.stat().st_size, output=output, provider_ids=provider_ids, selected=selected, objects=units)
    return result, archives

def stale_link(src, env, out, work, current, archives, previous, previous_path):
    """Keep all current Rust metadata, changing only the old consumer native members."""
    staging = work / "native-link"
    staging.mkdir()
    history = {}
    for variant in ("current", "previous-consumer"):
        arm = out / variant
        arm.mkdir()
        deps = staging / "deps"
        deps.mkdir()
        changed = []
        for crate, archive in archives.items():
            dest = deps / archive.name
            if crate != "mono_consumer":
                shutil.copyfile(archive, dest)
                require(file_sha(dest) == file_sha(archive), "provider copy changed")
                continue
            members = native_members(archive)
            native_ids = {object_id(crate, n) for n in members if n.endswith(".o")}
            require(native_ids == set(previous["objects"][crate]), "different native membership across two actual providers")
            materialized = staging / "members"
            materialized.mkdir()
            for name, data in members.items():
                if variant == "previous-consumer" and name.endswith(".o"):
                    cgu = object_id(crate, name)
                    older = (previous_path / "objects" / crate / (cgu + ".o")).read_bytes()
                    require(digest(older) == previous["objects"][crate][cgu]["sha256"], "lost earlier consumer object")
                    if older != data:
                        changed.append(cgu)
                    data = older
                (materialized / name).write_bytes(data)
            subprocess.run(["ar", "rcsD", dest, *members], cwd=materialized, check=True)
            rebuilt = native_members(dest)
            require(set(rebuilt) == set(members) and all(rebuilt[n] == (materialized / n).read_bytes() for n in rebuilt), "archive reconstruction failed")
            require(all(rebuilt[n] == data for n, data in members.items() if not n.endswith(".o")), "changed Rust metadata during the native test")
            shutil.rmtree(materialized)
        require(bool(changed) == (variant == "previous-consumer"), "stale-object test changed no consumer bytes")
        binary = staging / "mono_client"
        args = ["rustc", "+ohm", "--crate-name", "mono_client", "--edition=2021", str(src / "mono_consumer/src/main.rs"), "--crate-type=bin", "-Copt-level=1", "-Cdebuginfo=line-tables-only", "-Clink-arg=-Wl,--no-demangle", "--extern=mono_consumer=" + str(deps / archives["mono_consumer"].name), "-Ldependency=" + str(deps), "-o", str(binary)]
        run = command(args, env, src, arm, "rustc")
        if variant == "current":
            require(run["returncode"] == 0 and binary.is_file(), "current source/metadata/native link failed")
            require(subprocess.check_output([binary, "17"], env=env, timeout=10).decode().strip() == current["output"][17], "current direct link behavior differs")
            history[variant] = {"run": run, "exe": file_sha(binary)}
            binary.unlink()
        else:
            require(run["returncode"] == 1 and not binary.exists(), "previous consumer should not link against the remaining provider")
            stderr = (arm / "rustc.stderr").read_text()
            disappeared = {k: v["raw"] for k, v in previous["selected"].items()}
            for k, sym in disappeared.items():
                require(sym != current["selected"][k]["raw"] and re.search(r"(?:undefined symbol:\s*|undefined reference to [`‘'])" + re.escape(sym), stderr), f"link did not reject the withdrawn {k} symbol")
            history[variant] = {"run": run, "changed_cgus": changed, "undefined": disappeared}
        shutil.rmtree(deps)
    leftovers = {}
    for path in staging.iterdir():
        require(path.is_file() and not path.is_symlink() and path.name.endswith(".rcgu.o") and path.stat().st_size < 16 << 20, "unrecognized file left by the expected failed link")
        (out / "failed-link-objects").mkdir(exist_ok=True)
        shutil.copyfile(path, out / "failed-link-objects" / path.name)
        leftovers[path.name] = file_sha(path)
        path.unlink()
    staging.rmdir()
    history["previous-consumer"]["retained_linker_objects"] = leftovers
    store(out / "result.json", history)
    return history

def comparable(item):
    if item["state"]["body"] == "error":
        return {"state": item["state"], "source": item["source"], "errors": item["errors"]}
    return {
        "state": item["state"], "source": item["source"], "cli": item["cli_sha256"], "runtime": item["output"],
        "selected": item["selected"], "provider_ids": item["provider_ids"],
        "native": {c: {k: v["sha256"] for k, v in group.items()} for c, group in item["objects"].items()},
    }

def new_cache(work, env):
    for key in ("CARGO_HOME", "CARGO_TARGET_DIR", "CARGO_BUILD_BUILD_DIR", "TMPDIR", "HOME"):
        p = Path(env[key])
        require(p.parent == work and not p.is_symlink(), "private cache ownership mismatch")
        if p.exists():
            shutil.rmtree(p)
        p.mkdir()


FACTORY_ZIP = "5d237e932f6a1e4e6a25eda991d07005ae182c73af241e4916a8e9a55b6e488b"
FACTORY_COMMON = {
    "rustcs.json": "7a046a3009da7cd465d172ac096e723501cd514aae09a1e37ced435a0053d24b",
    "registration.json": "c2a92eed2b5b7543c2b589411ce54a7f543afc3ba7f4af4836a920335cdf995c"
}
FACTORY_ROLES = {
    "a3fc6da13921586bc374586dee00883e9210aecd": ("P", "normal", "d40b2b774df8ca19bc96bc933ffac5bed38178bc3940de144f199efa1cb8f713"),
    "259ad7069e47eaf08cf106f187b2b6393f7fd7c2": ("C", "defer", "a3277d441942adc988583f6608b8000d3526f70a04b3f8b6aa3112f71a28d826"),
}

def factory_identity(receipts, commit, inputs, driver_name, driver_bytes, rustc_version):
    require(receipts is not None and commit in FACTORY_ROLES, "unknown compiler requires the registered factory source and manifests")
    role, arm, expected = FACTORY_ROLES[commit]
    wanted = {**FACTORY_COMMON, role + ".json": expected}
    if receipts.is_dir():
        raw = {}
        for name in wanted:
            path = receipts / name
            require(path.is_file() and path.stat().st_size < 1 << 20, "missing or oversized factory receipt")
            raw[name] = path.read_bytes()
    else:
        require(receipts.is_file() and receipts.stat().st_size < 1 << 20 and file_sha(receipts) == FACTORY_ZIP, "unregistered factory ZIP")
        with zipfile.ZipFile(receipts) as archive:
            require(all(archive.namelist().count(n) == 1 and archive.getinfo(n).file_size < 1 << 20 for n in wanted), "missing or ambiguous factory ZIP members")
            raw = {n: archive.read(n) for n in wanted}
    require({n: digest(b) for n, b in raw.items()} == wanted, "altered or swapped factory manifest bytes")
    manifest = json.loads(raw[role + ".json"])
    registration = json.loads(raw["registration.json"])
    rebuilt = json.loads(raw["rustcs.json"])
    require(manifest["role"] == role and registration["roles"][role]["revision"] == manifest["commit"] == commit, "factory source revision mismatch")
    require(registration["roles"][role]["compiler"] == manifest["compiler_tree"], "factory compiler tree mismatch")
    require(registration["bootstrap_flags"].count("rust.omit-git-hash=true") == 1, "factory did not register deliberate hash omission")
    require("host: " + registration["target"] in rustc_version.splitlines() and "LLVM version: 23.1.1" in rustc_version.splitlines(), "unregistered matched compiler target or LLVM")
    files = rebuilt["arms"][arm]["files"]
    require(set(inputs) == {"bin/cargo", "bin/rustc", driver_name} and all(files[n] == value for n, value in inputs.items()), "installed compiler does not match factory role")
    other = "defer" if arm == "normal" else "normal"
    require(rebuilt["arms"][other]["files"][driver_name] != inputs[driver_name], "indistinguishable factory drivers")
    require(registration["signed_cargo"]["members"]["bin/cargo"][3] == inputs["bin/cargo"], "factory Cargo mismatch")
    require(manifest["files"]["bin/rustc"][0] == inputs["bin/rustc"] and manifest["files"][driver_name][:2] == [inputs[driver_name], driver_bytes], "installed compiler or driver differs from source role manifest")
    return {"role": role, "arm": arm, "commit": commit, "compiler_tree": manifest["compiler_tree"], "receipt_sha256": wanted}

def run(args):
    sdk = args.sdk_root.resolve(strict=True)
    work = args.work.resolve()
    out = args.out.resolve()
    for a, b in ((work, out), (work, sdk), (out, sdk), (work, HERE), (out, HERE)):
        require(a != b and a not in b.parents and b not in a.parents, "overlapping source/SDK/scratch/output paths")
    filled(work)
    filled(out)
    nonce = os.urandom(16).hex()
    marker = work / ".mono-owner-qa"
    marker.write_text(nonce)
    rustup = Path(shutil.which("rustup") or "")
    require(rustup.is_file(), "rustup not found")
    rustup_home = work / "rustup"
    (rustup_home / "toolchains").mkdir(parents=True)
    (rustup_home / "toolchains/ohm").symlink_to(sdk)
    src = work / "src"
    shutil.copytree(HERE / "source", src)
    env = dict(HOME=str(work / "home"), CARGO_HOME=str(work / "cargo"), CARGO_TARGET_DIR=str(work / "target"), CARGO_BUILD_BUILD_DIR=str(work / "build"), TMPDIR=str(work / "tmp"), RUSTUP_HOME=str(rustup_home), RUSTUP_AUTO_INSTALL="0", CARGO_NET_OFFLINE="true", CARGO_TERM_COLOR="never", LC_ALL="C", PATH=str(rustup.parent) + ":/usr/local/bin:/usr/bin:/bin")
    new_cache(work, env)
    toolchain = {}
    for name in ("cargo", "rustc"):
        resolved = Path(subprocess.check_output(["rustup", "which", "--toolchain", "ohm", name], env=env, text=True).strip()).resolve(strict=True)
        require(resolved == (sdk / "bin" / name).resolve(strict=True), f"rustup resolved a different {name}")
        toolchain[name] = {"path": str(resolved), "sha256": file_sha(resolved), "version": subprocess.check_output([name, "+ohm", "-vV"], env=env, text=True)}
    require(toolchain["cargo"]["sha256"] == args.expect_cargo_sha256, "Cargo binary does not match registration")
    drivers = sorted((sdk / "lib").glob("librustc_driver*.so"))
    require(len(drivers) == 1, "expected one private host rustc driver")
    driver = drivers[0].resolve(strict=True)
    toolchain["driver"] = {"path": str(driver), "sha256": file_sha(driver)}
    if args.expect_driver_sha256:
        require(toolchain["driver"]["sha256"] == args.expect_driver_sha256, "rustc driver mismatch")
    embedded = re.findall(r"^commit-hash: (\S+)$", toolchain["rustc"]["version"], re.M)
    require(len(embedded) == 1, "missing or ambiguous embedded compiler revision")
    if embedded[0] == "unknown":
        name = drivers[0].relative_to(sdk).as_posix()
        actual = {"bin/cargo": toolchain["cargo"]["sha256"], "bin/rustc": toolchain["rustc"]["sha256"], name: toolchain["driver"]["sha256"]}
        toolchain["factory_identity"] = factory_identity(args.factory_receipts, args.expect_commit, actual, name, driver.stat().st_size, toolchain["rustc"]["version"])
    else:
        require(embedded[0] == args.expect_commit and args.factory_receipts is None, "embedded compiler source does not match registration")
    store(out / "registration.json", {"schema": 1, "sdk": toolchain, "primary_argv": CARGO, "source": {str(p.relative_to(HERE)): file_sha(p) for p in sorted(HERE.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}, "host": os.uname().machine, "runtime_floor_bytes": 8 * GIB})
    histories = {}
    enrollment = [state("none"), state("left", ["mono_left"]), state("unrelated-added", ["mono_left"], True), state("unrelated-removed", ["mono_left"]), state("both", PROVIDERS)]
    try:
        for history in ("warm", "clean"):
            h = out / history
            h.mkdir()
            histories[history] = {}
            for spec in enrollment:
                if history == "clean":
                    new_cache(work, env)
                case = spec["name"]
                arm = h / case
                arm.mkdir()
                result, archives = analyze(src, env, arm, spec, work)
                store(arm / "result.json", result)
                histories[history][case] = result
                print(f"{history} {case}: {result.get('selected', {}).get('target', {}).get('winner', 'E0308')}", flush=True)
                if history == "warm" and case == "both":
                    winner = result["selected"]["target"]["winner"]
                    remaining = [n for n in PROVIDERS if n != winner]
                    require(len(remaining) == 1, "unknown selected winner")
                    enrollment.extend([state("winner-withdrawn", remaining), state("winner-restored", PROVIDERS), state("body-changed", PROVIDERS, body=11), state("type-error", PROVIDERS, body="error"), state("repaired", PROVIDERS, body=17), state("all-withdrawn", body=17)])
                    store(out / "enrolled-states.json", enrollment)
                elif history == "warm" and case == "winner-withdrawn":
                    link = out / "native-link-control"
                    link.mkdir()
                    stale_link(src, env, link, work, result, archives, histories[history]["both"], h / "both")
                if history == "clean":
                    require(comparable(result) == comparable(histories["warm"][case]), f"incremental/independent clean mismatch at {case}")
        warm = histories["warm"]
        for case in ("unrelated-added", "unrelated-removed"):
            require(warm[case]["selected"] == warm["left"]["selected"] and comparable(warm[case])["native"]["mono_consumer"] == comparable(warm["left"])["native"]["mono_consumer"], "unrelated type changed the stable target consumer")
        require(warm["both"]["selected"] == warm["winner-restored"]["selected"], "same provider set produced a different selection")
        require(warm["both"]["output"] != warm["body-changed"]["output"] != warm["repaired"]["output"], "missing genuine body/repair verdict changes")
        store(out / "terminal.json", {"success": True, "state_count": len(enrollment), "independent_histories": 2, "commit": args.expect_commit, "rustc_driver": toolchain["driver"]["sha256"], "cargo": toolchain["cargo"]["sha256"], "native_link_control": file_sha(out / "native-link-control/result.json"), "states": {c: {"warm": file_sha(out / "warm" / c / "result.json"), "clean": file_sha(out / "clean" / c / "result.json"), "selected_owner": r.get("selected", {}).get("target", {}).get("winner"), "runtime": r.get("output"), "errors": r["errors"]} for c,r in warm.items()}})
        require(marker.read_text() == nonce, "private run marker changed")
        shutil.rmtree(work)
    except Exception as error:
        store(out / "failure.json", {"error": str(error), "work": str(work)})
        raise

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sdk-root", type=Path, required=True)
    p.add_argument("--expect-commit", required=True)
    p.add_argument("--expect-cargo-sha256", default=SIGNED_CARGO)
    p.add_argument("--expect-driver-sha256")
    p.add_argument("--factory-receipts", type=Path, help="registered matched-factory receipt ZIP or extracted directory for source-built roles")
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    require(re.fullmatch("[0-9a-f]{40}", a.expect_commit) and re.fullmatch("[0-9a-f]{64}", a.expect_cargo_sha256), "need literal registered SHA values")
    run(a)
