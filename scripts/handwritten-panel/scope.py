"""Portable unit-graph identity and off-clock compiler-opening checks for uv #20988."""
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, unquote
import copy
import hashlib
import json
import re
import sys

RAW = "882dbf3687d11d9d72c13ff70c66b66170993eb9e6156424290e13c1d380ab1b"
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index#"


def require(test, message):
    if not test:
        raise ValueError(message)


def pack(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(pack(value)).hexdigest()


def absolute(value):
    p = PurePosixPath(str(value))
    require(p.is_absolute() and str(p) == str(value) and ".." not in p.parts and not str(p).startswith("//"), "noncanonical absolute path")
    return p


def relative(value):
    p = PurePosixPath(value)
    require(not p.is_absolute() and p.parts and ".." not in p.parts and str(p) == value, "noncanonical relative path")
    return p


def below(value, root):
    try:
        return relative(str(absolute(value).relative_to(root)))
    except ValueError as exc:
        raise ValueError("source outside the declared prefix: " + str(value)) from exc


def registry_relative(source, registry_src):
    path = below(source, registry_src)
    require(len(path.parts) >= 3 and re.fullmatch(r"[A-Za-z0-9_.-]+-[0-9a-f]{16}", path.parts[0]), "registry cache namespace")
    return path.parts[0], str(relative("/".join(path.parts[1:])))


def unit_attrs(row, workspace, registry_src, namespaces):
    require(set(row) == {"pkg_id", "target", "profile", "platform", "mode", "features", "dependencies"}, "unexpected unit schema")
    attrs = copy.deepcopy({k: v for k, v in row.items() if k != "dependencies"})
    target = attrs["target"]
    pkg = attrs["pkg_id"]
    source = target["src_path"]
    if pkg.startswith("path+file://"):
        uri = pkg.removeprefix("path+")
        parsed = urlsplit(uri)
        require(parsed.scheme == "file" and not parsed.netloc and not parsed.query and parsed.fragment, "workspace package URI")
        package = absolute(unquote(parsed.path, errors="strict"))
        require(package.as_uri() + "#" + parsed.fragment == uri, "noncanonical workspace package URI")
        folder = below(package, workspace)
        require(len(folder.parts) == 2 and folder.parts[0] == "crates", "unexpected workspace package directory")
        local = below(source, package)
        attrs["pkg_id"] = ["path+file", str(folder), parsed.fragment]
        target["src_path"] = ["workspace", str(folder / local)]
    else:
        require(pkg.startswith(REGISTRY), "unregistered package source")
        name, sep, version = pkg.removeprefix(REGISTRY).partition("@")
        require(sep and re.fullmatch(r"[A-Za-z0-9_-]+", name) and re.fullmatch(r"[0-9][0-9A-Za-z.+-]*", version), "registry package identity")
        namespace, local = registry_relative(source, registry_src)
        namespaces.add(namespace)
        require(PurePosixPath(local).parts[0] == name + "-" + version, "registry target belongs to another crate")
        target["src_path"] = ["registry", local]
    return attrs


def structural(graph, workspace, registry_src):
    """Normalize exactly two explicit source roots. Use complete non-edge unit attributes as node identities."""
    workspace, registry_src = absolute(workspace), absolute(registry_src)
    require(registry_src.parts[-2:] == ("registry", "src"), "expected a Cargo registry/src path")
    require(set(graph) == {"version", "units", "roots"} and graph["version"] == 1, "unit graph format")
    rows = graph["units"]
    namespaces = set()
    attrs = [unit_attrs(row, workspace, registry_src, namespaces) for row in rows]
    ids = [digest(unit) for unit in attrs]
    require(len(namespaces) == 1 and len(ids) == len(set(ids)), "ambiguous cache namespace or unit identity")

    def key(i):
        require(type(i) is int and 0 <= i < len(ids), "invalid unit index")
        return ids[i]

    result = {}
    for i, row in enumerate(rows):
        edges = []
        for dep in row["dependencies"]:
            require(set(dep) == {"index","extern_crate_name","public","noprelude","nounused"}, "dependency schema")
            require(type(dep["extern_crate_name"]) is str and all(type(dep[k]) is bool for k in ("public","noprelude","nounused")), "dependency fields")
            edges.append({k: v for k, v in dep.items() if k != "index"} | {"unit": key(dep["index"])})
        # Sorting preserves multiplicity. All authentic edge fields remain attached to the destination.
        result[ids[i]] = {"attributes": attrs[i], "dependencies": sorted(edges, key=pack)}
    return {"version": graph["version"], "roots": [key(i) for i in graph["roots"]], "units": result}


def reachable(start, edges):
    todo, seen = [start], set()
    while todo:
        node = todo.pop()
        if node not in seen:
            seen.add(node)
            todo.extend(edges[node])
    return seen


def extern_names(g, key):
    return sorted(edge["extern_crate_name"] for edge in g["units"][key]["dependencies"]
                  if g["units"][edge["unit"]]["attributes"]["mode"] != "run-custom-build")


def package_scope(g):
    units = g["units"]
    require(len(units) == 642 and len(g["roots"]) == 1, "registered single-root 642-unit plan")
    root = g["roots"][0]
    unit = units[root]["attributes"]
    target = unit["target"]
    require(unit["pkg_id"] == ["path+file","crates/uv","0.12.2"] and target["name"] == "uv" and
            target["src_path"] == ["workspace","crates/uv/src/lib.rs"] and target["kind"] == target["crate_types"] == ["lib"]
            and unit["mode"] == "check", "uv production lib root")
    forward = {k: [d["unit"] for d in v["dependencies"]] for k, v in units.items()}
    require(reachable(root, forward) == set(units), "unreachable unit")
    reverse = {k: set() for k in units}
    for k, parents in forward.items():
        v = units[k]["attributes"]
        require(v["target"]["kind"] in (["lib"], ["proc-macro"], ["custom-build"]) and
                v["mode"] in ("check","build","run-custom-build"), "test, bench, or other target")
        for parent in parents:
            reverse[parent].add(k)
    edited, = [k for k, v in units.items() if v["attributes"]["target"]["src_path"] == ["workspace","crates/uv-workspace/src/lib.rs"]
               and v["attributes"]["mode"] == "check"]
    affected = reachable(edited, reverse)
    require(len(affected) == 13 and all(units[k]["attributes"]["mode"] == "check" and
            units[k]["attributes"]["target"]["kind"] == ["lib"] for k in affected), "source-predicted closure")
    require(len(forward[root]) == len(set(forward[root])) == 98 and len(set(extern_names(g, root))) == 97, "direct root dependencies")
    return {"graph_sha256": digest(g), "root": root, "units": len(units), "edges": sum(map(len, forward.values())),
            "root_features": unit["features"], "direct_root_dependencies": len(forward[root]), "root_rustc_externs": extern_names(g, root),
            "kinds": dict(Counter(v["attributes"]["target"]["kind"][0] for v in units.values())),
            "modes": dict(Counter(v["attributes"]["mode"] for v in units.values())),
            "source_predicted_libraries_including_edited": sorted(units[k]["attributes"]["target"]["name"] for k in affected),
            "observed_edited_package_dirty_set": None}

EXPECTED = "e9a38b9d29a5c7db48b9cdd36f46445d9cc7d3a4abcb2360e5ce3725714e24d5"


def option(argv, key):
    items = []
    for i, arg in enumerate(argv):
        if arg == key:
            require(i + 1 < len(argv), "missing " + key)
            items.append(argv[i + 1])
        elif arg.startswith(key + "="):
            items.append(arg[len(key) + 1:])
    return items


def form(argv, workspace, registry_src, namespace):
    require(type(argv) is list and all(type(s) is str for s in argv) and PurePosixPath(argv[0]).name == "rustc", "need complete actual rustc argv")
    require("--test" not in argv and not option(argv, "--target"), "test or explicit cross target")
    source, = [s for s in argv[1:] if s.endswith(".rs") and not s.startswith("-")]
    if source.startswith("/"):
        absolute_source = absolute(source)
        if absolute_source.is_relative_to(workspace):
            source_id = ["workspace", str(below(source, workspace))]
        else:
            cache, local = registry_relative(source, registry_src)
            require(cache == namespace, "native rustc registry namespace differs from its plan")
            source_id = ["registry", local]
    else:
        source_id = ["workspace", str(relative(source))]
    name, = option(argv, "--crate-name")
    edition, = option(argv, "--edition")
    emit, = option(argv, "--emit")
    types = sorted(t for value in option(argv,"--crate-type") for t in value.split(","))
    require(types and emit and not set(emit.split(",")) - {"dep-info","metadata","link"}, "unexpected native compile form")
    mode = "build" if "link" in emit.split(",") else "check"
    if mode == "check":
        require("metadata" in emit.split(","), "native check missing metadata")
    features = []
    for cfg in option(argv, "--cfg"):
        if cfg.startswith("feature"):
            match = re.fullmatch(r'feature="([^"]+)"', cfg)
            require(match, "unrecognized feature cfg")
            features.append(match[1])
    externs = []
    for value in option(argv, "--extern"):
        name_and_flags, equals, path = value.partition("=")
        require(equals and path and ":" not in name_and_flags, "unrecognized extern form")
        externs.append(name_and_flags)
    return {"source": source_id, "name": name, "edition": edition, "crate_types": types,
            "mode": mode, "features": sorted(features), "externs": sorted(externs)}


def match_form(g, v):
    return [k for k, node in g["units"].items()
            if (u := node["attributes"])["target"]["src_path"] == v["source"]
            and u["target"]["name"].replace("-", "_") == v["name"]
            and sorted(u["target"]["crate_types"]) == v["crate_types"]
            and u["target"]["edition"] == v["edition"] and u["mode"] == v["mode"]
            and u["platform"] is None]


def native_opening(graph, workspace, registry_src, argv_rows, require_root=True):
    """Admit an unmeasured complete compilation trace. Actual dirty units are observations, not a fixed list."""
    workspace, registry_src = absolute(workspace), absolute(registry_src)
    g = structural(graph, workspace, registry_src)
    require(digest(g) == EXPECTED, "unregistered full scope")
    namespace, = {registry_relative(row["target"]["src_path"], registry_src)[0] for row in graph["units"]
                  if row["pkg_id"].startswith(REGISTRY)}
    observations = []
    for argv in argv_rows:
        v = form(argv, workspace, registry_src, namespace)
        matching = [k for k in match_form(g, v) if sorted(g["units"][k]["attributes"]["features"]) == v["features"]
                    and extern_names(g, k) == v["externs"]]
        require(len(matching) == 1, "unmatched/ambiguous native unit, features or externs for " + str(v["source"]))
        observations.append({"unit": matching[0], "source": v["source"], "name": v["name"], "complete_argv_sha256": digest(argv)})
    counts = Counter(row["unit"] for row in observations)
    require(observations and max(counts.values()) == 1, "missing or repeated native unit")
    if require_root:
        require(counts[g["roots"][0]] == 1, "package lib root not observed as an edited rustc process")
    return {"graph_sha256": EXPECTED, "observations": observations, "dirty_unit_ids": sorted(counts)}


def compare_dirty(control, candidate):
    require(control["graph_sha256"] == candidate["graph_sha256"] == EXPECTED, "different scope")
    left, right = set(control["dirty_unit_ids"]), set(candidate["dirty_unit_ids"])
    return {"matched": left == right, "control_only": sorted(left - right), "candidate_only": sorted(right - left),
            "requires_adjudication_before_any_claim": left != right}


if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser()
    cli.add_argument("action", choices=("digest","opening"))
    cli.add_argument("graph", type=Path)
    cli.add_argument("--workspace", required=True)
    cli.add_argument("--registry-src", required=True)
    cli.add_argument("--argv", type=Path)
    args = cli.parse_args()
    data = json.loads(args.graph.read_bytes())
    if args.action == "opening":
        require(args.argv is not None, "supply the actual unmeasured native argv JSON")
        result = native_opening(data, args.workspace, args.registry_src, json.loads(args.argv.read_bytes()))
    else:
        result = package_scope(structural(data, args.workspace, args.registry_src))
        require(result["graph_sha256"] == EXPECTED, "package plan differs from reference")
    print(json.dumps(result, indent=2, sort_keys=True))
