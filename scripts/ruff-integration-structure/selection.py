"""Bind typed artifacts to the physical rustcs and stock Wild outputs for this selector."""
import json
from pathlib import Path

from suite import require

LIBS = ("ruff_python_ast", "ruff_python_parser")


def artifacts(stream):
    return [m for m in stream if m.get("reason") == "compiler-artifact"]


def roster(stream, tree):
    all_rows, dirty = [], []
    for m in artifacts(stream):
        origin = m["package_id"]
        prefix = tree.as_uri()
        if origin.startswith("path+"):
            require(origin.startswith("path+" + prefix + "/"), ("non-workspace source", origin))
        t = m["target"]
        row = dict(id=origin.replace(prefix, "file:///__ruff__"), name=t["name"], kind=t["kind"],
                   crate_types=t["crate_types"], features=m["features"], profile=m["profile"])
        all_rows.append(row)
        if not m["fresh"]:
            dirty.append(row)
    key = lambda row: json.dumps(row, sort_keys=True)
    return sorted(all_rows, key=key), sorted(dirty, key=key)


def selected_paths(stream, tree, work):
    rows = [(r["target"], Path(r["executable"])) for r in artifacts(stream) if r["executable"]]
    result = {}
    for role, name, kind, source in (("cli", "ruff", "bin", "src/main.rs"),
                                     ("harness", "integration_test", "test", "tests/integration_test.rs")):
        matches = [p for t, p in rows if t["name"] == name and t["kind"] == [kind] and
                   Path(t["src_path"]) == tree / "crates/ruff" / source]
        require(len(matches) == 1, ("wrong executable for selector", role, rows))
        path = matches[0]
        require(path.is_absolute() and path.is_file() and path.resolve().is_relative_to(work),
                ("external ELF", role, path))
        result[role] = path
    require(len(rows) == 2 and result["cli"].samefile(work / "target/debug/ruff"), "other executable or BIN")
    return result


def selected_externs(argv):
    values = [argv[i+1] for i, arg in enumerate(argv) if arg == "--extern"]
    result = {}
    for name in LIBS:
        matches = [Path(a.split("=", 1)[1]) for a in values if a.startswith(name + "=")]
        bodies = [p for p in matches if p.suffix == ".rlib"]
        metadata = [p for p in matches if p.suffix == ".rmeta"]
        require(len(bodies) == 1 and len(matches) == len(bodies) + len(metadata) and
                (not metadata or metadata == [bodies[0].with_suffix(".rmeta")]),
                ("ambiguous or unmatched real --extern rlib/rmeta", name, matches))
        result[name] = {"rlib": str(bodies[0]), "rmeta": str(metadata[0]) if metadata else None}
    return result


def join_native(physical, paths, cold, previous, sha, enabled):
    policy = {}
    for role, name, src in (("cli", "ruff", "crates/ruff/src/main.rs"),
                            ("harness", "integration_test", "crates/ruff/tests/integration_test.rs")):
        full = [r for r in physical["rustcs"] if r["mode"] == "full" and r["crate"] == name and
                any(a == src or a.endswith("/" + src) for a in r["argv"]) and ("--test" in r["argv"]) == (role == "harness")]
        require(len(full) == 1 if cold else len(full) <= 1, ("cold or duplicate owner rustc", role, full))
        if full:
            row = full[0]
            externs = selected_externs(row["argv"])
            require(any(v in ("ohm-branch-cache=yes", "-Zohm-branch-cache=yes") for v in row["argv"]) == enabled and
                    "-Zohm-check-relink-inputs" in row["argv"] and
                    sum(v.startswith(("incremental=", "-Cincremental=")) for v in row["argv"]) == 1,
                    ("wrong full native compiler options", role))
            policy[role] = dict(pid=row["pid"], externs=externs)
        else:
            require(role in previous, ("no earlier true rustc mapping", role))
            policy[role] = dict(pid=None, externs=previous[role]["externs"])
        matching = []
        for ld in physical["wild_processes"]:
            f = Path(ld["output"])
            # Cargo promotes final artifacts from its dependency directory. Compare raw bytes
            # to that original stock linker's output when the two names are separate files.
            prefix = "ruff" if role == "cli" else "integration_test"
            if not (f.name == prefix or f.name.startswith(prefix + "-")) or not f.is_file():
                continue
            if paths[role].samefile(f) or (f.stat().st_size == paths[role].stat().st_size and sha(f) == sha(paths[role])):
                matching.append({"pid": ld["pid"], "path": str(f)})
        require(len(matching) == 1 if cold else len(matching) <= 1, ("wrong stock link", role, matching))
        policy[role]["linked_by"] = matching
    for name in LIBS:
        require(policy["cli"]["externs"][name]["rlib"] == policy["harness"]["externs"][name]["rlib"],
                ("BIN and test used different native rlibs", name))
    return policy


def reader_stream(stream, mapping, sha):
    found = {}
    output = []
    for row in stream:
        t = row.get("target", {})
        name = t.get("name")
        if name in LIBS and "lib" in t.get("kind", []) and row.get("reason") == "compiler-artifact":
            providers = [Path(v) for v in row["filenames"] if v.endswith(".rlib")]
            if not any(p.samefile(mapping["cli"]["externs"][name]["rlib"]) for p in providers):
                continue
            require(name not in found and len(providers) == 1, ("ambiguous --extern", name))
            f = providers[0]
            sidecars = {mapping[role]["externs"][name]["rmeta"] for role in ("cli","harness")} - {None}
            require(all(sum(Path(v).samefile(s) for v in row["filenames"]) == 1 for s in sidecars),
                    ("actual rustc rmeta missing from selected Cargo row", name, sidecars))
            found[name] = {"path": str(f), "sha256": sha(f), "bytes": f.stat().st_size,
                           "actual_rmeta": {s: sha(s) for s in sorted(sidecars)},
                           "features": row["features"], "profile": row["profile"]}
        output.append(row)
    require(set(found) == set(LIBS), ("actual reader providers missing", found))
    return output, found
