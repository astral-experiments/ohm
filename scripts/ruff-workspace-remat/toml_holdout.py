"""Ruff #27924 changed its public TOML parser. Use one downstream source on both revisions."""

import hashlib
import json
from pathlib import Path
import tomllib

OLD = "564fb737a826010f7c3c2c2e28533e407563e3a9"
NEW = "e0eb7b07632fce04d24d128c0e10a2d31c9e8282"
TREES = {OLD: "fe83eba853ad44f707c2d44a266b6136d4044c74", NEW: "f030df9f77a9dae0ce25bbec76a92dae5455f4ff"}
LOCK = "fe9f16e3ed255d0c382e1c3e24f1c8eef9619bd95e126f668515c0de712b933a"
OPTIONS = "crates/ruff_workspace/src/options.rs"
PATHS = (
    "crates/ruff/src/args.rs",
    "crates/ruff_server/src/session/settings.rs",
    OPTIONS,
    "crates/ruff_workspace/src/pyproject.rs",
)
METHOD = b"pub fn from_toml_table(table: toml::Table) -> Result<Self, toml::de::Error>"
CASES = (
    ("valid", "line-length = 100\n", 0, b"line-length=100\n"),
    ("syntax", "line-length = [\n", 2, b"invalid TOML syntax\n"),
    ("range", "line-length = 0\n", 3, b"line-length must be between 1 and 65535 (got 0)\n"),
)


def hash_bytes(data):
    return hashlib.sha256(data).hexdigest()


def enroll(r, source, registry):
    r.need(
        r.git(source, "rev-parse", NEW + "^").decode().strip() == OLD
        and r.git(source, "diff-tree", "--no-commit-id", "--name-only", "-r", OLD, NEW).decode().splitlines()
        == list(PATHS),
        "wrong historical pair",
    )
    blobs = {}
    for rev, tree in TREES.items():
        r.need(r.git(source, "rev-parse", rev + "^{tree}").decode().strip() == tree, "wrong Ruff tree")
        lock = r.git(source, "show", rev + ":Cargo.lock")
        packages = [p for p in tomllib.loads(lock.decode())["package"] if "checksum" in p]
        entries = {p["name"] + "-" + p["version"] + ".crate": p["checksum"] for p in packages}
        r.need(
            hash_bytes(lock) == LOCK and len(packages) == len(entries) == 505 and entries == registry,
            "wrong locked registry",
        )
        blobs[rev] = {p: r.git(source, "show", rev + ":" + p) for p in PATHS}
    r.need(
        METHOD not in blobs[OLD][OPTIONS] and blobs[NEW][OPTIONS].count(METHOD) == 1,
        "wrong public method edit",
    )
    guard = b"let _guard = ValueSourceGuard::new(ValueSource::Cli, false);"
    caller = Path(__file__).with_name("toml-reader.rs").read_bytes()
    r.need(
        all(blobs[rev][PATHS[0]].count(guard) == 1 for rev in TREES)
        and caller.count(guard) == 1 and caller.index(guard) < caller.index(b"Options::from_toml_table("),
        "downstream caller must establish the historical CLI value source before deserializing",
    )
    return blobs


def source_state(r, repo, blobs, rev, invalid, invalid_line, *, write=False):
    expected = {p: b + (invalid_line if invalid and p == OPTIONS else b"") for p, b in blobs[rev].items()}
    for name, body in expected.items():
        path = repo / name
        r.need(path.is_file() and path.resolve() == path, ("unexpected fixture file", path))
        if write and path.read_bytes() != body:
            path.write_bytes(body)
        r.need(path.read_bytes() == body, ("wrong Ruff input", rev, name))
    dirty = sorted(p for p, body in expected.items() if body != blobs[OLD][p])
    r.need(
        r.git(repo, "rev-parse", "HEAD").decode().strip() == OLD
        and not r.git(repo, "diff", "--cached", "--name-only")
        and r.git(repo, "diff", "--name-only", "HEAD").decode().splitlines() == dirty
        and not r.git(repo, "ls-files", "--others", "--exclude-standard")
        and r.sha(repo / "Cargo.lock") == LOCK,
        "unregistered Ruff source",
    )
    return {
        "revision": rev,
        "invalid": invalid,
        "dirty": dirty,
        "files": {p: hash_bytes(b) for p, b in expected.items()},
        "physical": {
            p: [(repo / p).stat().st_ino, (repo / p).stat().st_mtime_ns, (repo / p).stat().st_ctime_ns]
            for p in PATHS
        },
    }


def client(r, w, dest, rows, products, graph, root, work, env, rev, bodies):
    folder = dest / "client"
    folder.mkdir()
    source, binary = root / "toml-reader.rs", root / "toml-reader"
    binary.unlink(missing_ok=True)
    original = hash_bytes(Path(__file__).with_name("toml-reader.rs").read_bytes())
    r.need(r.sha(source) == original, "downstream source changed")
    unit = graph["units"][graph["roots"][0]]
    libs = {"ruff_workspace": w.p.artifact(products, "ruff_workspace")}
    for name, suffix in (("toml", "#toml@1.1.4+spec-1.1.0"), ("ruff_ranged_value", "/ruff_ranged_value#0.0.9")):
        (edge,) = [d for d in unit["dependencies"] if d["extern_crate_name"] == name]
        dep = graph["units"][edge["index"]]
        r.need(dep["pkg_id"].endswith(suffix) and dep["target"]["kind"] == ["lib"], ("wrong dependency", name))
        products_for_dep = [
            p for p in products
            if w.graph_key(p["package_id"], p["target"], p["features"])
            == w.graph_key(dep["pkg_id"], dep["target"], dep["features"])
        ]
        archive = w.p.artifact(products_for_dep, name)
        (meta,) = [Path(f) for p in products_for_dep for f in p["filenames"] if f.endswith(".rmeta")]
        r.need(meta.is_file() and meta == archive.with_suffix(".rmeta"), ("incorrect paired metadata", name))
        libs[name] = archive if name == "ruff_ranged_value" else meta
    dirs = sorted(
        {Path(f).parent for p in products for f in p["filenames"] if f.endswith((".rlib", ".rmeta", ".so"))}
        | {p for p in (work / "target/debug/deps", work / "build/debug/deps") if p.is_dir()}
    )
    flags = ["--edition=2024", "--crate-name", "ohm_ruff_toml_probe", "--error-format=json"]
    for name, lib in libs.items():
        flags.extend(["--extern", f"{name}={lib}"])
    for path in dirs:
        flags.extend(["-L", "dependency=" + str(path)])
    native = dict.fromkeys(
        q for p in rows if p["reason"] == "build-script-executed" for q in p["linked_paths"]
    )
    for path in native:
        flags.extend(["-L", path])
    status = 1 if rev == OLD else 0
    process = w.native.read_command(
        folder, "compile", ["rustc", "+ohm", source, *flags, "-o", binary], root, env, status
    )
    record = {"source": original, "libraries": {k: str(v) for k, v in libs.items()}, "compile_status": status}
    if rev == OLD:
        errors = [
            e
            for line in process.stderr.splitlines()
            if (e := json.loads(line)).get("level") == "error" and e.get("code")
        ]
        r.need(
            len(errors) == 1
            and errors[0]["code"]["code"] == "E0599"
            and "from_toml_table" in errors[0]["message"]
            and any(
                s["is_primary"]
                and Path(s["file_name"]) == source
                and any("Options::from_toml_table" in t["text"] for t in s["text"])
                for s in errors[0]["spans"]
            )
            and not binary.exists(),
            "OLD did not reject precisely the missing public method",
        )
        record["error"] = "E0599"
    else:
        record["elf"] = w.physical.keep(binary, bodies, b"\x7fELF\x02\x01")
        for name, doc, code, expected in CASES:
            q = w.native.read_command(folder, name, [binary, doc], root, env, code)
            r.need(q.stdout == expected and not q.stderr, ("wrong parsed result", name, q.stdout, q.stderr))
    r.put(folder / "result.json", record)
    return record


def qualify(r, observations, out):
    arms = ("signed", "stock", "strict")
    phases = ("old", "new", "unchanged", "invalid", "repair", "clean-new", "inspect-old", "inspect-new")
    by_arm = {arm: {q["phase"]: q for q in observations if q["arm"] == arm} for arm in arms}
    r.need(
        len(observations) == len(arms) * len(phases)
        and all(set(group) == set(phases) for group in by_arm.values()),
        "missing history",
    )
    clean = {}
    equal = {}
    programs = set()
    for arm, group in by_arm.items():
        reference = group["clean-new"]
        clean[arm] = {}
        equal[arm] = {}
        for phase in phases:
            q = group[phase]
            if phase == "invalid":
                r.need(q["error"] == "E0308", "invalid source passed")
                continue
            baseline = by_arm["signed"][phase]
            equal[arm][phase] = {k: q[k] == baseline[k] for k in ("objects", "metadata")}
            if phase in ("old", "inspect-old"):
                r.need(q["consumer"]["error"] == "E0599" and "elf" not in q["consumer"], "stale OLD method")
            else:
                v = q["consumer"]["elf"]["sha256"]
                programs.add(v)
                clean[arm][phase] = {
                    "program": v == reference["consumer"]["elf"]["sha256"],
                    "objects": q["objects"] == reference["objects"],
                    "metadata": q["metadata"] == reference["metadata"],
                }
    r.need(
        len(programs) == 1 and all(v["program"] for g in clean.values() for v in g.values()),
        "changed or nonreproducible typed NEW program",
    )
    return {
        "schema": "ohm-ruff-27924-toml-source-pass-v1",
        "observation_sha256": r.sha(out / "observations.json"),
        "elf_sha256": next(iter(programs)),
        "same_phase_matches_signed": equal,
        "matches_independent_clean": clean,
        "all_same_phase_native_objects": all(v["objects"] for g in equal.values() for v in g.values()),
        "old_error": "E0599",
        "invalid_error": "E0308",
        "typed_cases": [[name, code, value.decode()] for name, _, code, value in CASES],
    }
