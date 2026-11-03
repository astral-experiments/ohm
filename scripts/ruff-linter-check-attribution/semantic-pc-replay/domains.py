"""Report disjoint native leaf sets, preserving the kernel and symbol evidence tiers."""
from collections import Counter,defaultdict
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
import pc_raw
import semantic_pcs


def check(condition, message):
    if not condition:
        raise ValueError(message)


def driver_group(symbol):
    # This is a partition of function *names*. Generic instantiations mentioning multiple
    # namespaces use the first matching rule; no inlined call attribution is inferred.
    if "::dep_graph::" in symbol or "SerializedDepNodeIndex" in symbol:
        return "dependency graph, including index-specific generics"
    if "::public_api_hasher::" in symbol:
        return "public API hashing and reachability"
    if "::stable_hash" in symbol or "StableHash" in symbol:
        return "other named stable hashing"
    if any(k in symbol for k in ("rustc_expand::","rustc_proc_macro::","proc_macro::","rustc_builtin_macros::")):
        return "macro expansion and bridge"
    if "rustc_parse::" in symbol or "rustc_lexer::" in symbol:
        return "parsing and lexing"
    if "rustc_resolve::" in symbol:
        return "name resolution"
    if "rustc_ast_lowering::" in symbol:
        return "AST lowering"
    if "rustc_metadata::" in symbol:
        return "other metadata"
    if "rustc_incremental::" in symbol:
        return "other incremental"
    if any(k in symbol for k in ("rustc_query_system::","rustc_query_impl::","rustc_middle::query::","rustc_middle::queries::")):
        return "other named query infrastructure"
    if symbol.startswith("["):
        return "unresolved or ambiguous driver symbol"
    return "other driver"


def buildid_records(raw):
    """Decode the on-disk PERF_HEADER_BUILD_ID feature, including its recorded width."""
    header=struct.unpack_from("<13Q",raw)
    off=header[5]+header[6]
    features=[n for n in range(256) if header[9+n//64] & (1<<(n%64))]
    check(2 in features,"missing original build-ID feature")
    begin,size=struct.unpack_from("<QQ",raw,off+features.index(2)*16)
    pos=begin;end=begin+size
    out={}
    while pos<end:
        code,flags,n=struct.unpack_from("<IHH",raw,pos)
        check(pos+n<=end and n>=37 and flags & (1<<15), "unexpected build-ID event")
        ident=raw[pos+12:pos+32]
        width=raw[pos+32]
        check(0<width<=20,"unrecognized build-ID wire width")
        name=raw[pos+36:pos+n].split(b"\0",1)[0].decode()
        check(name not in out,"ambiguous build-ID filename")
        out[name]=ident[:width].hex()
        pos+=n
    check(pos==end,"partial build-ID feature")
    return out


def run(z,verified):
    score=verified["pc"];owner=verified["target"]
    raw=subprocess.run(["zstd","-q","-dc"],input=z.read("profile/perf.data.zst"),stdout=subprocess.PIPE,check=True).stdout
    period,ips,_,_,_,skid=pc_raw.raw_records(raw)
    frames,records=pc_raw.symbol_rows(io.BytesIO(z.read("profile/samples.ndjson.gz")))
    maps=semantic_pcs.mappings(raw,owner["pid"])
    ids=buildid_records(raw)
    saved={line.split()[1]:line.split()[0] for line in z.read("profile/buildids.txt").decode().splitlines() if len(line.split())==2}
    check(all(ids.get(n)==v for n,v in saved.items()) and set(ids)-set(saved)=={"[kernel.kallsyms]"},
          "original user DSO build-ID feature vs perf --with-hits")
    by_map=Counter(); by_symbol=defaultdict(Counter)
    for datum,leaf,_ in records:
        pid,tid,at,weight,ip=datum
        if pid!=owner["pid"] or at<owner["start_ns"]:continue
        if datum in skid:
            by_map["[kernel skid]"]+=1
            continue
        choices={r["name"] for r in maps if r["base"]<=ip<r["base"]+r["length"]}
        name=choices.pop() if len(choices)==1 else "[no unique kernel mapping]"
        by_map[name]+=1
        dso,symbol=frames[leaf[0]]
        if name.startswith("/") and Path(name).name.startswith("libsalsa_macros-"):
            check(dso==name,"Salsa has different decoded DSO and native MMAP2")
            by_symbol[name][symbol]+=1
    check(by_map.total()==score["owner_samples"],"disjoint mapping population")
    directory,=by_symbol.keys()
    initial=maps[[r["name"] for r in maps].index(directory)]
    summary=json.loads(z.read("profile/semantic.json"));obj=summary["binaries"][directory]
    check(len(ids[directory])==40 and len(obj["gnu_build_id"])==64 and obj["gnu_build_id"].startswith(ids[directory]),"Salsa build-ID prefix")
    check(initial["inode"]!=obj["inode"] and obj["sha256"]=="95ea8231d1af6b737c629d97761bb23a33e582478779f856f4e1af1e4d4f63b3","independent replacement classification")
    package=None
    for line in z.read("release23/edited/stdout").splitlines():
        row=json.loads(line)
        if directory in row.get("filenames",()):
            check(package is None and row["fresh"] and row["target"]["kind"]==["proc-macro"],"original typed macro")
            package=row["package_id"]
    check(package=="registry+https://github.com/rust-lang/crates.io-index#salsa-macros@0.28.2","original Cargo package")
    weights=by_symbol[directory]
    names=sorted(weights)
    dem=subprocess.run(["llvm-cxxfilt-18","-n"],input="\n".join(names)+"\n",text=True,capture_output=True,check=True).stdout.splitlines()
    check(len(dem)==len(names),"omitted symbol body")
    groups=Counter(); symbols=[];known={"core","syn","alloc","proc_macro","proc_macro2","__rustc","hashbrown","salsa_macros","std","quote"}
    for name,resolved in zip(names,dem):
        m=re.search(r"\b([a-zA-Z_][a-zA-Z_0-9]*)::",resolved)
        family=m.group(1) if m and m.group(1) in known else "other or unknown"
        groups[family]+=weights[name]
        symbols.append((weights[name],family,resolved,name))
    driver_name,=[k for k in score["dsos"] if k.startswith("librustc_driver-")]
    driver=Counter()
    for so,name,n in score["top_exclusive_functions"]:
        if so==driver_name:driver[driver_group(name)]+=n
    check(driver.total()==score["dsos"][driver_name],"disjoint driver functions")
    inventory=[]
    for name,n in by_map.most_common():
        image=summary["binaries"].get(name,{})
        last=image.get("gnu_build_id")
        recorded=ids.get(name)
        inventory.append(dict(dso=Path(name).name,samples=n,independent_buildid=last,perf_buildid=recorded,
                              original_id_prefix_matches=bool(recorded and last and last.startswith(recorded)),
                              post_clean_sha256=image.get("sha256")))
    return {"driver_function_name_groups":dict(driver.most_common()),"kernel_mapping_groups":inventory,
            "salsa":{"typed_package":package, "original_perf_buildid_20b":ids[directory], "independent_buildid_32b":obj["gnu_build_id"],
                     "independent_file_sha256":obj["sha256"],"original_inode":initial["inode"],"independent_replacement_inode":obj["inode"],
                     "original_full_elf_sha256":None,"original_full_symbol_ranges_reopened":False,
                     "mapping_samples":by_map[directory],"first_named_crate":dict(groups.most_common()),
                     "perf_reported_symbols":[list(s) for s in sorted(symbols,reverse=True)]}}
