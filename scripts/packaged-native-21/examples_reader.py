"""Verify the typed Cargo result, signed compiler/link events, and actual example programs."""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from packages import ASSETS, CARGO, HEAD, RUN, need
from fixture import allocated_sections, digest
from readback import Corpus

RUFF = "aa9a1ff88aa83b3f01360ef5b3cb04b2be187206"
TREE = "b9e3804adebb8385962701bbb100eff2d6e42743"
LOCK = "583d2c16902903b32c016859c12131cb80fd8bdc4121440f359ef743675fc1c5"
FOCAL = "crates/ruff_annotate_snippets/examples/format.rs"
FOCAL_BLOB = "7b5123d41c9750a5512605d702250217ebfe7d58"
ORIGINAL = b"mismatched types"
UPDATED = b"ohm physical example changed"
INVALID = b"missing_ohm_ruff_example_value"
NAMES = ("custom_error", "custom_level", "elide_header", "expected_type", "footer", "format",
         "highlight_message", "highlight_source", "id_hyperlink", "multi_suggestion", "multislice",
         "struct_name_as_context")
PHASES = (("cold", "old"), ("repeat-1", "old"), ("repeat-2", "old"),
          ("edit", "new"), ("repeat-edited", "new"), ("invalid", "invalid"),
          ("repair", "old"), ("clean-old", "old"), ("clean-new", "new"))
CMD = ["cargo", "+ohm", "build", "-p", "ruff_annotate_snippets", "--examples",
       "--locked", "--offline", "--message-format=json"]
SDK_RUST = {"20": "7e71d3150938ff8ed82aca03416439d7e5b87ef3", "21": "c79998a5cd143c445a4b2528f20953b176a65c5d"}


def checked_example_artifacts(stdout, success):
    rows = [json.loads(line) for line in stdout.splitlines()]
    need(rows and rows[-1] == {"reason":"build-finished","success":success}, "typed build exit")
    out = {}
    for row in rows:
        if row["reason"] != "compiler-artifact" or row["target"]["kind"] != ["example"]:
            continue
        target = row["target"]
        name = target["name"]
        need(name in NAMES and name not in out and row["executable"] and
             Path(target["src_path"]).as_posix().endswith("/crates/ruff_annotate_snippets/examples/"+name+".rs") and
             "/crates/ruff_annotate_snippets#" in row["package_id"], "foreign or duplicate Cargo example")
        out[name] = row
    if success:
        need(set(out) == set(NAMES), "missing returned example")
    else:
        errors = [r["message"] for r in rows if r["reason"]=="compiler-message" and r["message"]["level"]=="error"]
        need(any((e.get("code") or {}).get("code")=="E0425" and INVALID.decode() in e.get("message","") and
                 any(a.get("is_primary") and str(a.get("file_name","")).endswith(FOCAL)
                     for a in e.get("spans", [])) for e in errors), "missing expected real compiler diagnostic")
    return out


def flag(argv, name):
    values = [v for k,v in zip(argv, argv[1:]) if k == name]
    need(len(values) == 1, "unexpected operand count for "+name)
    return values[0]


def incremental(argv):
    opts = [v for k,v in zip(argv, argv[1:]) if k == "-C"]
    opts.extend(a[2:] for a in argv if a.startswith("-C") and len(a)>2)
    return [o.removeprefix("incremental=") for o in opts if o.startswith("incremental=")]


def typed_rustc(row, tools):
    if row["path"] != tools["rustc"]["physical"] or "--crate-name" not in row["argv"]:
        return None
    argv = row["argv"]
    name = flag(argv, "--crate-name")
    is_link = "link-only" in argv or "-Zlink-only" in argv
    example_source = [a for a in argv if a.endswith("/examples/"+name+".rs") and
                      ("crates/ruff_annotate_snippets/examples/"+name+".rs") in a]
    if not is_link:
        is_example = bool(example_source)
        if is_example:
            need(name in NAMES and len(example_source)==1 and len(incremental(argv))==1, "non-developer example compile")
    else:
        is_example = name in NAMES and any(a.endswith("/"+name+".rlink") or
                                           re.search(r"/"+re.escape(name)+r"-[0-9a-f]+\.rlink$",a) for a in argv)
    return {"crate":name, "mode":"link-only" if is_link else "full","example":is_example,
            "incremental":incremental(argv) if is_example and not is_link else []}


def events_census(rows, tools, subcommand="build"):
    need(len(rows) == len({r["seq"] for r in rows}) and
         [r["seq"] for r in rows] == sorted(r["seq"] for r in rows), "nonunique or nonmonotonic kernel execs")
    hist = {}
    rustcs = []
    inks = []
    cargos = []
    linker_queries = []
    for event in rows:
        path, args = event["path"], event["argv"]
        if path == tools["cargo"]["physical"]:
            need(event["cdhash"] and event["cdhash"].lower()==tools["cargo"]["cdhash"],"foreign real Cargo exec")
            if subcommand in args: cargos.append(event)
        if path == tools["rustc"]["physical"]:
            need((event.get("cdhash") or "").lower() == tools["rustc"]["cdhash"],"foreign packaged rustc")
            unit = typed_rustc(event, tools)
            if unit is not None: rustcs.append(dict(unit,seq=event["seq"],pid=event["pid"]))
        if Path(path).name in ("ld","ld64","ld-classic","ld-prime"):
            need(path == tools["ld"]["physical"] and (event.get("cdhash") or "").lower()==tools["ld"]["cdhash"],
                 "foreign ld or Xcode signature")
            if args[1:] in (["-v"],["--version"],["-version_details"]):
                linker_queries.append(event["seq"])
                hist[event["pid"]]=event
                continue
            parent = hist.get(event["ppid"])
            need(parent and parent["path"]==tools["clang"]["physical"] and
                 (parent.get("cdhash") or "").lower()==tools["clang"]["cdhash"],"missing actual Xcode clang parent")
            chain = [event]
            while parent and len(chain) < 18:
                chain.append(parent)
                if (unit := typed_rustc(parent,tools)) is not None:
                    break
                parent = hist.get(parent["ppid"])
            else:
                raise RuntimeError("native ld has no matching packaged rustc parent")
            need(not any(a.startswith("@") for a in args),"indirect ld operands require a separately authenticated response")
            path = flag(args,"-o")
            inks.append(dict(unit,seq=event["seq"],pid=event["pid"],issuer=event["cdhash"],output=path,
                             parent_rustc=chain[-1]["seq"],parent_clang=chain[1]["seq"]))
        hist[event["pid"]] = event
    need(len(cargos)==1,"missing ordinary physical Cargo build")
    return {"all_typed_rustcs":dict(Counter(r["mode"] for r in rustcs)),
            "rustcs":rustcs,"true_xcode_ld":inks,"linker_version_queries":linker_queries}


def blob_id(data):
    import hashlib
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()


def source_variant(old, state):
    needle = b'.primary_title("'+ORIGINAL+b'")'
    need(blob_id(old)==FOCAL_BLOB and old.count(needle)==1,"different pinned Ruff fixture")
    if state=="old": return old
    if state=="new": return old.replace(needle,b'.primary_title("'+UPDATED+b'")')
    need(state=="invalid","unknown source state")
    return old.replace(needle,b".primary_title("+INVALID+b")")


def verify(c):
    src=c.json("ruff.json")
    need((src["head"],src["tree"],src["cargo_lock"])==(RUFF,TREE,LOCK) and src["registry_checksums"]>20,
         "wrong enrolled source/registry")
    old=c.raw("source-old.gz")
    states={s:source_variant(old,s) for _,s in PHASES}
    result={}
    behavior_across={}
    for role in ("20","21"):
        sdk=c.json(role+"/custody.json")
        need(sdk["provenance"]["sources"]["rust"]["revision"]==SDK_RUST[role] and
             sdk["provenance"]["sources"]["cargo"]["revision"]==CARGO,"wrong physical SDK")
        if role=="20": need(sdk["archive_sha256"]==ASSETS["aarch64-apple-darwin"][2],"wrong -20 archive")
        else: need(sdk["source"]["run_id"]==RUN and sdk["source"]["head_sha"]==HEAD and
                   sdk["source"]["artifact"]["name"]=="ohm-1.99.0-21-aarch64-apple-darwin","wrong -21 archive")
        tools=c.json(role+"/examples-tools.json")
        installed=c.json(role+"/installed.json")
        env=c.json(role+"/env.json")
        need(not ({"CI","TF_BUILD","RUSTFLAGS","CARGO_INCREMENTAL","GH_TOKEN","GITHUB_TOKEN"} & env.keys()) and
             env["CARGO_TARGET_DIR"].endswith("/ordinary-"+role+"/target") and
             env["CARGO_BUILD_BUILD_DIR"].endswith("/ordinary-"+role+"/shared"),"mixed developer storage")
        for k in ("rustc","cargo","clang","ld"):
            t=tools[k]
            need(re.fullmatch(r"[a-f0-9]{40}",t["cdhash"]) and re.fullmatch(r"[a-f0-9]{64}",t["sha256"]) and
                 re.search(r"(?im)^CDHash="+t["cdhash"]+r"$",t["codesign"]),
                 "missing signer or physical tool")
            if k in ("rustc","cargo"): need(t["sha256"]==installed["bin/"+k],"different installed product")
        observed={}
        summaries={}
        for phase,state in PHASES:
            base=f"{role}/examples/{phase}"
            q=c.json(base+"/observed.json")
            need(q["argv"]==CMD and c.raw(base+"/source.gz")==states[state] and
                 (q["exit"]==0)==(state!="invalid"), "source state/exit/command differs")
            stdout=c.raw(base+"/cargo.stdout.gz")
            artifacts=checked_example_artifacts(stdout,state!="invalid")
            rows=json.loads(c.raw(base+"/kernel.json.gz"))
            counts=events_census(rows,tools)
            need(q["counts"]==counts and c.raw(base+"/cargo.stderr.gz") is not None,"native count projection differs")
            expected_cold=phase in ("cold","clean-old","clean-new")
            if expected_cold:
                need(q["initial_counts"]==[0,0] and
                     {r["crate"] for r in counts["rustcs"] if r["example"] and r["mode"]=="full"}==set(NAMES) and
                     {r["crate"] for r in counts["true_xcode_ld"] if r["example"]}==set(NAMES),"empty reference missed a real emit/link")
            need(set(q["native_programs"])==(set(NAMES) if state!="invalid" else set()),"wrong observed program inventory")
            if state!="invalid":
                need(set(q["cache"])==set(NAMES),"missing crate-specific incremental state")
                for n,files in q["cache"].items():
                    sc=(n+"-")
                    need(files and all(v[0].startswith(env["CARGO_TARGET_DIR"]+"/") or
                                       v[0].startswith(env["CARGO_BUILD_BUILD_DIR"]+"/") for v in files) and
                         all(any(s.startswith(sc) for s in Path(v[0]).parts) and v[1]>0 and
                             re.fullmatch(r"[0-9a-f]{64}",v[2]) and
                             (len(raw:=c.raw("cache/"+v[2]+".gz")),digest(raw))==(v[1],v[2]) for v in files) and
                         {Path(v[0]).name for v in files}=={"work-products.bin","dep-graph.bin"},"missing actual rustc session files")
                modes={r["crate"]:r for r in counts["true_xcode_ld"] if r["example"]}
                for n,p in q["native_programs"].items():
                    exe=c.raw("binaries/"+p["raw"]+".gz")
                    sections=allocated_sections(exe)
                    streams=[c.raw(base+"/"+n+"."+s+".gz") for s in ("stdout","stderr")]
                    need(digest(exe)==p["raw"] and sections==p["sections"] and p["exit"]==0 and
                         [digest(i) for i in streams]==[p["stdout"],p["stderr"]] and
                         p["path"]==artifacts[n]["executable"], "wrong returned Mach-O or native behavior")
                    bounds=p["kernel_output"]
                    if n in modes:
                        need(bounds and bounds["path"]==modes[n]["output"] and bounds["sha256"]==digest(exe),
                             "owned native ld output does not match returned executable")
                    else: need(bounds is None,"unobserved example linker claimed")
                    observed[phase,n]=(p["raw"],sections,streams)
                f=b"".join(observed[phase,"format"][2])
                need((UPDATED in f)==(state=="new") and (ORIGINAL in f)==(state=="old"),"stale or foreign example formatter verdict")
                if phase in ("edit","repair"):
                    need("format" in modes,"changed diagnostic did not physically relink")
            summaries[phase]={"all_rustcs":counts["all_typed_rustcs"],
                "example_rustcs":dict(Counter(r["mode"] for r in counts["rustcs"] if r["example"])),
                "all_xcode_ld":len(counts["true_xcode_ld"]),
                "example_xcode_ld":sorted(r["crate"] for r in counts["true_xcode_ld"] if r["example"]),
                "example_names_returned":len(artifacts),"successful_native_executions":len(q["native_programs"])}
        diffs={}
        for phase,state in PHASES:
            if state=="invalid": continue
            clean="clean-"+state
            diffs[phase]=[]
            for n in NAMES:
                raw,sections,out=observed[phase,n]
                ref,ref_sections,ref_out=observed[clean,n]
                need(out==ref_out,"native example differs from independent clean state")
                need(sections==ref_sections,"file-backed example section differs from independent clean state")
                if raw!=ref: diffs[phase].append(n)
                key=(state,n)
                if role=="20": behavior_across[key]=out
                else: need(behavior_across[key]==out,"published versions return different example behavior")
        result[role]={"phases":summaries,"same_role_raw_differences_vs_clean":diffs}
    return result
