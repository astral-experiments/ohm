"""Read the frozen profile only against its own current graph. Join histories by full kind and key."""
import collections
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import resolve

DEFS = re.compile(r"DefId\((\d+):(\d+) ~ ([^()]+)\)")
INSTANCE = re.compile(r"^Instance \{ def: ([A-Za-z0-9_]+)\((.*)\), args: (\[.*\]) \}$", re.S)
ABI = re.compile(r"^PseudoCanonicalInput \{ typing_env: (TypingEnv \{.*\}), value: \((Instance \{.*\}), (\[.*\])\) \}$", re.S)
NEUTRAL = "TypingEnv { typing_mode: TypingModeEqWrapper(Codegen), param_env: ParamEnv { caller_bounds: [] } }"


def classify(query, name):
    if name is None:
        return {"class":"unresolved"}
    if query not in ("fn_abi_of_instance_no_deduced_attrs", "symbol_name"):
        return {"class":{"layout_of":"layout", "upstream_monomorphizations_for":"definition", "codegen_unit":"codegen-unit"}.get(query,"other")}
    content = name
    extras = None
    if query == "fn_abi_of_instance_no_deduced_attrs":
        match = ABI.fullmatch(content)
        if not match:
            return {"class":"unrecognized ABI key"}
        env, content, extras = match.groups()
    match = INSTANCE.fullmatch(content)
    if not match:
        return {"class":"unrecognized instance"}
    variant, arguments, substitutions = match.groups()
    desc = {"instance_kind":variant, "generic_args":substitutions}
    if extras is not None:
        desc.update(typing_env=env, extra_args=extras)
    if variant != "Item":
        return dict(desc, **{"class":"non-Item " + variant})
    m = DEFS.fullmatch(arguments)
    if not m:
        return dict(desc, **{"class":"unrecognized item DefId"})
    path = m[3]
    desc.update(crate_number=int(m[1]), definition_index=int(m[2]), definition_path=path)
    if re.search(r"::\{+(closure|coroutine)([#@}]|$)",path):
        kind = "closure or coroutine"
    elif substitutions != "[]":
        kind = "instantiated generic item"
    elif extras is not None and (extras != "[]" or env != NEUTRAL):
        kind = "empty item substitutions with additional ABI context"
    else:
        kind = "ordinary Item with no substitutions"
    return dict(desc, **{"class":kind})


def inspect(root):
    spec = json.loads((HERE / "keys.json").read_bytes())
    keys = {tuple(k) for k in spec["context"]}
    first = {(r["node"]["kind"],r["node"]["key"]) for r in spec["primary"]}
    resolve.need(first <= keys and len(first) == 30 and len(keys) == 1426, "registered exact groups")
    per_key = collections.defaultdict(list)
    states = {}
    for branch in ("A","B"):
        d = root / branch
        complete = json.loads((d/"complete.json").read_bytes())
        native = json.loads(__import__("gzip").decompress((d/"native.json.gz").read_bytes()))
        p = json.loads((d/"process.json").read_bytes())
        resolve.need(complete["source"] == native["source"] and native["typed"] == ("Expr=64 valid=1 rejected" if branch=="A" else "Expr=56 valid=1 rejected"), "checked native source or branch discriminator")
        state = resolve.read(d, keys=keys, strict_keys=first)
        states[branch] = dict(source=complete, graph=p["graph"], profile=p["profile"], summary=state["summary"], pid=p["pid"], rustc=p["signed_rustc"], native={"typed":native["typed"],"cli":native["cli"]["whole"],"reader":native["reader"]["whole"]})
        for row in state["rows"]:
            per_key[row["kind"],row["key"]].append(dict(branch=branch,**row))
    rejected = []
    for branch, other in (("A","B"),("B","A")):
        for label in ("graph","profile"):
            try:
                resolve.paired(root/branch, **{label+"_file":root/other/(label+".gz")})
            except ValueError as e:
                resolve.need("wrong process-bound "+label+" archive" in str(e), ("unexpected swapped refusal",e))
                rejected.append([branch,other,label,str(e)])
            else:
                raise ValueError(("accepted mismatched inputs",branch,other,label))
    primary = []
    for k,key in sorted(first):
        rows = per_key[k,key]
        query = resolve.graph.NAMES[k]
        names = sorted({r["item"] for r in rows if r["item"] is not None})
        selected = [r for r in spec["primary"] if (r["node"]["kind"],r["node"]["key"]) == (k,key)]
        contexts = []
        for name in names:
            contexts.append({"raw":name, "classification":classify(query,name)})
        equivalent_text = {re.sub(r"DefId\(\d+:\d+ ~ ", "DefId(~ ", n) for n in names}
        primary.append(dict(kind=k,query=query,key=key,selection=selected,rows=rows,names=contexts,
                            status="absent" if not rows else "unresolved" if not names else "unique" if len(names)==1 else "same shape after stripping ephemeral DefId numbers" if len(equivalent_text)==1 else "ambiguous"))
    auxiliary = [dict(kind=k,key=key,query=resolve.graph.NAMES[k],rows=per_key[k,key]) for k,key in sorted(keys-first)]
    return {"status":"independent signed cold dictionary", "selection":spec["provenance"], "selection_sha256":spec["trace_sha256"],"states":states,"negative_cross_inputs":rejected,"primary":primary,"context":auxiliary}


if __name__ == "__main__":
    result = inspect(Path(sys.argv[1]).resolve())
    output = Path(sys.argv[2])
    with output.open("x") as f:
        json.dump(result,f,sort_keys=True,separators=(",",":"))
        f.write("\n")
    print(json.dumps({k:v for k,v in result.items() if k in ("status","states")},sort_keys=True))
    print("primary keys by disposition",dict(collections.Counter(r["status"] for r in result["primary"])))
