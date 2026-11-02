"""Off-clock correctness witness for a frozen historical workspace edit."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

STATE, SOURCE, TARGET, SDK = sys.argv[1:]
assert STATE in {"A", "B"}
SOURCE, TARGET, SDK = map(lambda s: Path(s).resolve(strict=True), (SOURCE, TARGET, SDK))
CARGO, RUSTC = SDK / "bin/cargo", SDK / "bin/rustc"


def check_blob(relative, before, after):
    data = (SOURCE / relative).read_bytes()
    actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    assert actual == (before if STATE == "A" else after), (relative, STATE, actual)


def run(argv, *, env=None, timeout=300):
    result = subprocess.run(list(map(str, argv)), cwd=SOURCE, env=env, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} exited {result.returncode}: {result.stderr[-6000:]} {result.stdout[-2000:]}")
    return result


def options(argv, name):
    """Return the option values in rustc's original order, including joined spellings."""
    for i, arg in enumerate(argv):
        if arg == name:
            yield argv[i + 1]
        elif arg.startswith(name + "="):
            yield arg[len(name) + 1:]
        elif name == "-L" and arg.startswith("-L"):
            yield arg[2:]


def products(events, package, source, target, check_files=True):
    name = package.replace("-", "_")
    result = set()
    for row in events:
        if row.get("reason") != "compiler-artifact":
            continue
        t = row["target"]
        if t["name"] != name or "lib" not in t["kind"] or Path(t["src_path"]) != source / "crates" / package / "src/lib.rs":
            continue
        for filename in row["filenames"]:
            p = Path(filename)
            if p.suffix != ".rmeta":
                continue
            assert p.is_relative_to(target) and ".." not in p.parts, p
            if p.name == "lib" + name + ".rmeta":
                # Consumers use the hashed artifact when a primary top-level alias is present.
                continue
            assert p.name.startswith("lib" + name + "-"), p
            if check_files:
                assert p.resolve(strict=True).is_relative_to(target) and p.stat().st_size > 0, p
            result.add(p)
    assert result, (source, target, package)
    return sorted(result)


def artifact_roster(events, target):
    """Compare the Cargo owners, effective features, profile and real output for both trees."""
    result = []
    for row in events:
        if row["reason"] != "compiler-artifact":
            continue
        t = row["target"]
        files = sorted(str(Path(p).relative_to(target)) for p in row["filenames"])
        key = [row["package_id"], t["name"], t["kind"], t["src_path"], sorted(row["features"]), row["profile"], files]
        result.append(json.dumps(key, sort_keys=True, separators=(",", ":")))
    return sorted(result)


def read_flags(argv, recorded, actual, needed, meta, *, check_files=True):
    """Translate only the private target root, preserving every observed -L and --extern."""
    selected = False
    result = []
    # The compiler permits interleaved and repeated search/extern arguments.
    # Keep their original order, including two paths for a split-metadata crate.
    i = 1
    while i < len(argv):
        arg = argv[i]
        i += 1
        if arg in ("--extern", "-L"):
            flag, value = arg, argv[i]
            i += 1
        elif arg.startswith("--extern="):
            flag, value = "--extern", arg[len("--extern="):]
        elif arg.startswith("-L") and len(arg) > 2:
            flag, value = "-L", arg[2:].removeprefix("=")
        else:
            continue
        head, sep, path = value.partition("=")
        if not sep:
            if flag == "--extern":
                result.extend([flag, value])
                continue
            head, path = "", head
        p = Path(path)
        assert p.is_absolute() and ".." not in p.parts, p
        if p.is_relative_to(recorded):
            p = actual / p.relative_to(recorded)
        if check_files:
            valid = p.is_dir() if flag == "-L" else p.is_file()
            assert valid, p
        if flag == "--extern" and head.rsplit(":", 1)[-1] == needed and p == meta:
            selected = True
        result.extend([flag, (head + "=" if sep else "") + str(p)])
    assert selected and "-L" in result, (needed, meta)
    if "-Zunstable-options" in argv or any(a == "-Z" and b == "unstable-options" for a,b in zip(argv, argv[1:])):
        result.insert(0, "-Zunstable-options")
    return result


def compiler_commands(stderr, rustc):
    """Read Cargo's verbose, shell-quoted Linux command stream without changing its graph."""
    import shlex
    commands = []
    for raw in stderr.splitlines():
        line = raw.strip()
        if not (line.startswith("Running `") and line.endswith("`")):
            continue
        tokens = shlex.split(line[len("Running `"):-1])
        if str(rustc) in tokens:
            i = tokens.index(str(rustc))
            argv = tokens[i:]
            if "--crate-name" in argv and "--out-dir" in argv:
                commands.append(argv)
    assert commands, "Cargo produced no full compiler command lines at -vv"
    return commands


def verbose_events(proc, lane):
    import gzip
    import re
    from urllib.parse import unquote
    qa = Path(os.environ["OHM_WITNESS_CARGO_JSONL"]).resolve(strict=True)
    label = qa.name.removesuffix("-cargo.jsonl.gz")
    for suffix, text in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        with gzip.open(qa.with_name(label+"-"+lane+"."+suffix+".gz"), "xb", compresslevel=2) as f:
            f.write(text.encode())
    parsed, owners = [], []
    for line in proc.stdout.splitlines():
        if line.startswith("{"):
            parsed.append(json.loads(line))
        else:
            match = re.fullmatch(r"\[([^\s\]]+) ([^\s\]]+)\](?: .*)?", line)
            assert match, line[:400]
            owners.append(match.groups())
    assert parsed[-1] == {"reason":"build-finished", "success":True}
    executed = set()
    for event in parsed:
        if event["reason"] != "build-script-executed":
            continue
        source, fragment = event["package_id"].rsplit("#", 1)
        if "@" in fragment:
            name, version = fragment.rsplit("@", 1)
        else:
            name, version = unquote(source.rsplit("/", 1)[1]), fragment
        executed.add((name, version))
    assert set(owners) <= executed, sorted(set(owners) - executed)
    return parsed


def actual_metadata(package):
    import gzip

    name = package.replace("-", "_")
    env = {**os.environ, "CARGO_TARGET_DIR": str(TARGET)}
    qa_source = Path(env.pop("OHM_WITNESS_CARGO_JSONL")).resolve(strict=True)
    assert qa_source.name in ({"parent-cargo.jsonl.gz"} if STATE == "A" else
                              {"edited-cargo.jsonl.gz", "clean-child-cargo.jsonl.gz"}), qa_source
    assert not env.get("RUSTC_WRAPPER") and not env.get("RUSTC_WORKSPACE_WRAPPER")
    command = [CARGO, "check", "--offline", "--locked", "-j8", "--message-format=json-render-diagnostics"]

    # The released compiler may intentionally retrigger a native-link prerequisite.
    # Reissuing check on this target could change the very artifact under test.
    with gzip.open(qa_source, "rt") as file:
        events = [json.loads(line) for line in file]
    assert events[-1] == {"reason": "build-finished", "success": True}
    paths = products(events, package, SOURCE, TARGET)
    roster = artifact_roster(events, TARGET)
    # The executable witness below always opens this arm's measured artifacts.
    # No path within the measured target is changed to capture the compiler.
    # B and independently clean B may share commands only if all Cargo choices match.
    with SDK.joinpath("bin/cargo").open("rb") as f:
        cargo_digest = hashlib.file_digest(f, "sha256").hexdigest()
    with next(SDK.glob("lib/librustc_driver-*.so")).open("rb") as f:
        driver_digest = hashlib.file_digest(f, "sha256").hexdigest()
    capture_key = hashlib.sha256(json.dumps([STATE, name, str(SOURCE), str(TARGET), cargo_digest, driver_digest, roster]).encode()).hexdigest()
    memo = TARGET.parent / ("witness-compiler-inputs-" + capture_key + ".json")
    if memo.is_file():
        record = json.loads(memo.read_text())
    else:
        with tempfile.TemporaryDirectory(prefix="qa-argv-", dir=TARGET.parent) as loc:
            tmp = Path(loc)
            shadow = tmp / "target"
            proc = run([*command, "-vv"], env={**env, "CARGO_TARGET_DIR": str(shadow)}, timeout=1800)
            observed = verbose_events(proc, "shadow-check")
            assert observed[-1] == {"reason": "build-finished", "success": True}
            choices = compiler_commands(proc.stderr, RUSTC)
            assert roster == artifact_roster(observed, shadow), "independent Cargo artifact selection differs"
            assert [p.relative_to(shadow) for p in products(observed, package, SOURCE, shadow)] == [p.relative_to(TARGET) for p in paths]
            record = {"source_target": str(shadow), "commands": {}}
            for meta in paths:
                relative = str(meta.relative_to(TARGET))
                matching = [a for a in choices if Path(a[0]).resolve() == RUSTC.resolve() and
                            any(value.rpartition("=")[0].rsplit(":",1)[-1] == name and
                                value.rpartition("=")[2] == str(shadow / relative) for value in options(a, "--extern"))]
                assert matching, (name, relative)
                record["commands"][relative] = min(matching, key=lambda a: (len(a), a))
        with tempfile.NamedTemporaryFile(mode="w", dir=memo.parent, prefix=".witness-inputs-", delete=False) as f:
            json.dump(record, f)
            fresh_memo = f.name
        os.replace(fresh_memo, memo)
    return [(p, read_flags(record["commands"][str(p.relative_to(TARGET))], Path(record["source_target"]),
                           TARGET, name, p)) for p in paths]


def check_client(tmp, rust, package, item, *, expected_error=None):
    meta, flags = item
    assert meta.is_file() and "--extern" in flags
    source, output = tmp / "client.rs", tmp / "client.rmeta"
    source.write_text(rust)
    output.unlink(missing_ok=True)
    argv = [RUSTC, "--edition=2024", "--crate-type=lib", "--crate-name=ohm_check_client", "--emit=metadata",
            "--error-format=json", *flags, source, "-o", output]
    proc = subprocess.run(list(map(str, argv)), cwd=SOURCE, capture_output=True, text=True, timeout=90)
    if expected_error is None:
        assert proc.returncode == 0 and output.is_file() and output.stat().st_size, proc.stderr[-6000:]
    else:
        code, needle = expected_error
        errors = [x for x in map(json.loads, proc.stderr.splitlines()) if x.get("level") == "error" and x.get("code")]
        assert proc.returncode == 1 and not output.exists(), (proc.returncode, proc.stderr[-6000:])
        assert [x["code"]["code"] for x in errors] == [code] and needle in errors[0]["message"], errors


NATIVE_CLIENT = '// Compile against uv_workspace, uv_cache and tokio from one measured compiler and revision.\nuse std::path::PathBuf;\nuse uv_cache::Cache;\nuse uv_workspace::{DiscoveryOptions, VirtualProject, Workspace, WorkspaceCache};\n\nfn main() -> Result<(), Box<dyn std::error::Error>> {\n    let mut args = std::env::args().skip(1);\n    let revision = args.next().expect("expected A or B");\n    let root = PathBuf::from(args.next().expect("expected an empty temp directory")).canonicalize()?;\n    assert!(root.read_dir()?.next().is_none());\n    let member = root.join("packages/seeds");\n    std::fs::create_dir_all(&member)?;\n    std::fs::write(root.join("pyproject.toml"), "[tool.uv.workspace]\\nmembers = [\'packages/*\']\\n")?;\n    std::fs::write(member.join("pyproject.toml"), "[project]\\nname = \'seeds\'\\nversion = \'1.0.0\'\\nrequires-python = \'>=3.12\'\\n")?;\n    let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;\n    runtime.block_on(async {\n        let cache = Cache::from_path(root.join(".cache"));\n        let workspaces = WorkspaceCache::default();\n        let options = DiscoveryOptions::default();\n        let discovered = Workspace::discover(&root, &options, &cache, &workspaces).await?;\n        // A successful second lookup after corruption must use the populated discovery cache.\n        std::fs::write(root.join("pyproject.toml"), "not valid toml >.<")?;\n        let cached_root = VirtualProject::discover(&root, &options, &cache, &workspaces).await?;\n        let cached_member = VirtualProject::discover(&member, &options, &cache, &workspaces).await?;\n        assert!(cached_root.is_non_project());\n        assert_eq!(cached_member.project_name().unwrap().to_string(), "seeds");\n        assert!(std::ptr::eq(discovered.as_ref(), cached_root.workspace()));\n        assert!(std::ptr::eq(discovered.as_ref(), cached_member.workspace()));\n        // Both revisions implement Debug by printing the populated OnceMap\'s actual values.\n        // The matching is independent of arbitrary path and map iteration order.\n        let contents = format!("{workspaces:?}");\n        let new_value = contents.contains("CachedWorkspace { workspace:");\n        assert_eq!(new_value, match revision.as_str() { "A" => false, "B" => true, _ => panic!("expected A or B") });\n        println!("member identity, virtual root and populated cache value verified on {revision}");\n        Ok(())\n    })\n}\n'


def native_workspace(tmp):
    # A dedicated Cargo target keeps native artifacts out of the measured check target.
    native = tmp / "native"
    env = {**os.environ, "CARGO_TARGET_DIR": str(native), "CARGO_INCREMENTAL": "0", "CARGO_PROFILE_DEV_DEBUG": "0"}
    proc = run([CARGO, "build", "-vv", "--locked", "--offline", "-j4", "--lib", "-p", "uv-workspace",
                "--message-format=json-render-diagnostics"], env=env, timeout=1200)
    events = verbose_events(proc, "native-build")
    assert events[-1] == {"reason": "build-finished", "success": True}
    commands = compiler_commands(proc.stderr, RUSTC)

    def native_owner(name):
        rows = []
        for command in commands:
            if list(options(command, "--crate-name")) != [name]:
                continue
            assert Path(command[0]).resolve() == RUSTC.resolve()
            emit = list(options(command, "--emit"))
            if emit and not any("link" in value.split(",") for value in emit):
                continue
            out_dir, = (Path(v).resolve(strict=True) for v in options(command, "--out-dir"))
            assert out_dir.is_relative_to(native.resolve()) and out_dir.is_dir()
            suffix, = [v.split("=", 1)[1] for v in command if v.startswith("extra-filename=")]
            rows.append((out_dir / ("lib" + name + suffix + ".rlib"), command))
        assert rows, name
        return rows

    (root_rlib, argv), = native_owner("uv_workspace")
    out_dir = root_rlib.parent

    def add_inputs(name, archive):
        assert archive.resolve(strict=True).is_relative_to(native.resolve()) and archive.stat().st_size
        producers = [cmd for path, cmd in native_owner(name) if path == archive]
        assert producers, (name, archive)
        # A library consumer can receive only metadata in both layouts. The
        # producer determines whether the archive carries a metadata stub.
        split_modes = {any(v in ("embed-metadata=no", "-Zembed-metadata=no") for v in cmd) for cmd in producers}
        split, = split_modes
        reported = [Path(p) for r in events if r["reason"] == "compiler-artifact" and
                    r["target"]["name"] == name and "lib" in r["target"]["kind"] for p in r["filenames"] if p.endswith(".rlib")]
        if not any(path.samefile(archive) for path in reported):
            # Cargo may copy its primary target's public alias on another filesystem.
            with archive.open("rb") as file:
                digest = hashlib.file_digest(file, "sha256").hexdigest()
            same = False
            for path in reported:
                if path.stat().st_size == archive.stat().st_size:
                    with path.open("rb") as file:
                        same |= hashlib.file_digest(file, "sha256").hexdigest() == digest
            assert same, (name, archive, reported)
        for path in [archive, archive.with_suffix(".rmeta")] if split else [archive]:
            assert path.is_file() and path.stat().st_size
            extern.extend(["--extern", name + "=" + str(path)])

    extern = []
    for name in ("uv_cache", "tokio"):
        linked = [Path(v.split("=", 1)[1]) for v in options(argv, "--extern")
                  if v.partition("=")[0].rsplit(":", 1)[-1] == name and "=" in v]
        assert linked and all(path.is_file() for path in linked)
        archive, = {p.with_suffix(".rlib") for p in linked}
        add_inputs(name, archive)
    add_inputs("uv_workspace", root_rlib)


    search = []
    for i, arg in enumerate(argv):
        if arg == "-L":
            search.extend(["-L", argv[i+1]])
        elif arg.startswith("-L") and len(arg) > 2:
            search.append(arg)
        elif arg.startswith(("linker=", "link-arg=")) and i and argv[i-1] == "-C":
            search.extend(["-C", arg])
    assert search
    for directory in options(search, "-L"):
        p = Path(directory.split("=", 1)[-1])
        assert p.is_dir(), p
    # Cargo includes dependency archives' ancestors in its owner's search paths.
    # Add the produced crate's directory for its split metadata and for its aliases.
    if str(out_dir) not in [v.split("=", 1)[-1] for v in options(search, "-L")]:
        search.extend(["-L", "dependency=" + str(out_dir)])
    for r in events:
        if r["reason"] == "build-script-executed":
            for path in r["linked_paths"]:
                if path not in search:
                    search.extend(["-L", path])
    rust, exe = tmp / "workspace_probe.rs", tmp / "workspace-probe"
    rust.write_text(NATIVE_CLIENT)
    run([RUSTC, "--edition=2024", "--crate-name=ohm_workspace_probe", *search, *extern, rust, "-o", exe], timeout=240)
    fixture = tmp / "fixture"
    fixture.mkdir()
    proc = run([exe, STATE, fixture])
    assert proc.stdout.strip() == f"member identity, virtual root and populated cache value verified on {STATE}", proc.stdout


check_blob("crates/uv-workspace/src/workspace.rs", "085690cddf69f07f9b864fafff5e18fc2bc5d239", "7dcaba60aac32dd361ef548a0b8603acbaa65262")
with tempfile.TemporaryDirectory(prefix="qa-workspace-", dir=TARGET.parent) as location:
    tmp = Path(location)
    client = """
use uv_workspace::{WorkspaceCache, VirtualProject};
pub fn inspect(c: &WorkspaceCache, p: &VirtualProject) -> bool {
    let _: WorkspaceCache = c.clone();
    let _ = p.workspace();
    p.is_non_project() && p.project_name().is_none()
}
"""
    for path in actual_metadata("uv-workspace"):
        check_client(tmp, client, "uv_workspace", path)
    native_workspace(tmp)
print(json.dumps({"edit": 22635, "virtual_root_reuses_cache": True, "member": "seeds",
                  "member_reuses_cache": True, "cache_value_stores_project_name": STATE == "B"}, sort_keys=True))
