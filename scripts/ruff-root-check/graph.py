"""Describe an exact root Cargo selection without including the installation address."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re

CARGO = ["cargo", "+ohm", "check", "--locked", "--offline", "-j4", "--message-format=json"]
PROVIDERS = ("ruff_linter", "ruff_python_ast", "ruff_python_parser", "ty_project", "ty_python_semantic")


def need(ok, reason):
    if not ok:
        raise ValueError(str(reason))


def encoded(value):
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def package(pkg, tree):
    prefix = "path+" + tree.as_uri() + "/"
    if pkg.startswith(prefix):
        return "path+ruff/" + pkg.removeprefix(prefix)
    need(pkg.startswith("registry+https://github.com/rust-lang/crates.io-index#"), ("unregistered source", pkg))
    return pkg


def target_path(pkg, raw, tree):
    p = Path(raw)
    if pkg.startswith("path+ruff/"):
        return p.relative_to(tree).as_posix()
    name, version = pkg.split("#")[1].split("@")
    indexes = [i for i in range(len(p.parts)-4) if p.parts[i:i+2] == ("registry","src") and
               p.parts[i+3] == name+"-"+version and re.fullmatch(r".+-[0-9a-f]{16}", p.parts[i+2])]
    need(len(indexes)==1, ("wrong registry source", pkg, raw))
    return "/".join(p.parts[indexes[0]+3:])


def key(pkg, target, features, tree):
    origin = package(pkg, tree)
    return (origin, target["name"], tuple(target["kind"]), tuple(target["crate_types"]),
            target_path(origin,target["src_path"],tree), tuple(features))


def selection(graph, metadata, tree):
    members = sorted(package(m,tree) for m in metadata["workspace_members"])
    defaults = sorted(package(m,tree) for m in metadata["workspace_default_members"])
    need(members == defaults and len(members)==len(set(members))==52 and
         Path(metadata["workspace_root"]) == tree, "different workspace/default selection")
    groups=graph["units"]
    need(graph["version"]==1 and len(groups)==564 and len(graph["roots"])==len(set(graph["roots"]))==55,
         "different unit or root total")
    nodes,labels=[],[]
    for u in groups:
        v=copy.deepcopy(u)
        del v["dependencies"]
        v["pkg_id"]=package(v["pkg_id"],tree)
        v["target"]["src_path"]=target_path(v["pkg_id"],v["target"]["src_path"],tree)
        nodes.append(v)
        labels.append(digest(v))
    need(len(set(labels))==len(labels), "ambiguous unit identity")
    rows=[]
    for u,v,label in zip(groups,nodes,labels,strict=True):
        deps=sorted([d|{"index":labels[d["index"]]} for d in u["dependencies"]],key=encoded)
        rows.append({"id":label,"unit":v,"dependencies":deps})
    indices=graph["roots"]
    roots=sorted(labels[i] for i in indices)
    need({nodes[i]["pkg_id"] for i in indices}==set(members) and all(nodes[i]["mode"]=="check" for i in indices),
         "missing default package or non-check root")
    dev,=[i for i in indices if nodes[i]["target"]["src_path"]=="crates/ruff_dev/src/main.rs"]
    pairs={d["extern_crate_name"]:groups[d["index"]] for d in groups[dev]["dependencies"]}
    need(all(pairs[n]["mode"]=="check" and pairs[n]["target"]["name"]==n for n in PROVIDERS),"reader selection")
    return {"members":members,"roots":roots,"units":sorted(rows,key=lambda r:r["id"])}


def census(projected):
    rows=projected["units"]
    return {"units":len(rows),"packages":len(set(r["unit"]["pkg_id"] for r in rows)),
            "roots":len(projected["roots"]),"members":len(projected["members"]),
            "edges":sum(len(r["dependencies"]) for r in rows),
            "modes":dict(Counter(r["unit"]["mode"] for r in rows)),"sha256":digest(projected)}


def typed_graph(rows, projected, tree):
    planned=Counter()
    for r in projected["units"]:
        v=r["unit"]
        if v["mode"]!="run-custom-build":
            t=v["target"]
            planned[(v["pkg_id"],t["name"],tuple(t["kind"]),tuple(t["crate_types"]),t["src_path"],tuple(v["features"]))]+=1
    actual=Counter(key(m["package_id"],m["target"],m["features"],tree) for m in rows if m["reason"]=="compiler-artifact")
    need(actual==planned,("typed output did not equal exact non-run graph",list((planned-actual).items())[:10],list((actual-planned).items())[:10]))
    return sum(actual.values())
