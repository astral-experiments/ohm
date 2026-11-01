"""Project complete x86-64 kernel exec events onto the original workspace census."""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_common import CMD, RELEVANT, digest, need
from packages import save, sha
import rc22_kernel_events as events

SOURCE = "d4e1c4bac917a2de3218c13c50875b5c2d301a23"
OBSERVER = "9a7df0422b9cba724b612fe2e0a07e218cd6ae26be9171f5cdd9755d3db54054"
READER = "6303e38aad48eec1924a4015aa9a8f7387009fdd269d4e0bed189345a11f4238"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
PREFIX = "shared/kernel-fixtures/"
LEDGER = "kernel-exec-v2.tsv.gz"
OLD_BOOT = "16abddd9-bd9e-4cec-abb2-de8048ac50b0"
CASES = {"family":23,"thread":37,"duplicate":19,"abort":13,"signals":14,"long":0}

def qualify(root, checkout):
    checkout = checkout.resolve(strict=True)
    kit = checkout / "scripts/branch-return-execstop"
    need(subprocess.check_output(["git","-C",checkout,"rev-parse","HEAD"],text=True).strip() == SOURCE and
         sha(kit/"kernel/observe.c") == OBSERVER and sha(kit/"kernel/read_events.py") == READER ==
         sha(Path(events.__file__)), "foreign kernel observer or source reader")
    out = root/"receipts/shared/kernel-fixtures"
    tools = root/"kernel-tools"
    wild = root/"sdk-22/lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    need(sha(wild) == WILD, "different installed stock Wild")
    script = kit/"group_fixtures.py"
    subprocess.run([sys.executable,"-IB",script,"run",tools,out,wild], check=True, timeout=240)
    reopened = subprocess.check_output([sys.executable,"-IB",script,"reopen",out],timeout=120)
    need(reopened == (out/"group-v2/qualified.json").read_bytes(), "host fixture readback disagrees")
    host = json.loads((out/"group-v2/host.json").read_bytes())
    bind = {"source":SOURCE, "source_sha256":OBSERVER, "reader_sha256":READER,
            "observer":str(tools/"observe"), "observer_sha256":sha(tools/"observe"),
            "boot":host["boot"], "kernel":host["kernel"], "fixtures_sha256":digest(reopened)}
    save(root/"receipts/shared/kernel-binding.json", bind)
    return bind

def verify_fixtures(c, enrollment):
    binding = c.json("shared/kernel-binding.json")
    get = lambda name: c.get(PREFIX + name)
    q = json.loads(get("group-v2/qualified.json"))
    original = json.loads(get("qualified.json"))
    host = json.loads(get("group-v2/host.json"))
    need(binding == {"source":SOURCE, "source_sha256":OBSERVER, "reader_sha256":READER,
                     "observer":str(Path(enrollment["work_root"])/"kernel-tools/observe"),
                     "observer_sha256":digest(get("observe.elf")), "boot":enrollment["boot"],
                     "kernel":enrollment["kernel"], "fixtures_sha256":digest(get("group-v2/qualified.json"))},
         "kernel source, binary, host or qualification changed")
    need(q["qualified"] is True and q["schema"]==2 and binding["boot"]==host["boot"]==q["boot"]!=OLD_BOOT
         and q["kernel"]==binding["kernel"]==host["kernel"] and q["observer_sha256"]==binding["observer_sha256"]
         ==host["identities"]["observe"]["sha256"] and host["identities"]["observe"]["resolved"]==binding["observer"]
         and q["stock_wild_sha256"]==host["identities"]["wild"]["sha256"]==WILD
         and q["sources"]["kernel/observe.c"]==OBSERVER and q["sources"]["kernel/read_events.py"]==READER
         and sha(Path(events.__file__))==READER, "foreign packaged observer")
    need(digest(get("qualified.json")) == q["inherited_sha256"] and original["qualified"] is True and
         set(original["native"]["positive"])==set(CASES) and len(original["native"]["negative"])==2 and
         len(original["native"]["mutations_rejected"])==16 and len(original["ruff_projection"]["refusals"])==12 and
         len(q["mutations_rejected"])==30 and set(q["historical_refusals"])=={"01","02"},
         "missing native or adversarial fixture gates")
    for subset, items in (("original/",original["originals"]),("",q["originals"])):
        for name, h in items.items():
            need(Path(name).as_posix()==name and not Path(name).is_absolute() and ".." not in Path(name).parts and
                 digest(get(subset+name))==h, "changed kernel fixture member "+name)
    need({p for p in c.names if p.startswith(PREFIX)} ==
         {PREFIX+p for p in q["originals"]}|{PREFIX+"group-v2/qualified.json"},
         "missing or additional kernel qualification original")
    for name in ("group-v2/pending.tsv","group-v2/history/01.tsv.gz","group-v2/history/02.tsv.gz"):
        raw=get(name)
        if name.endswith(".gz"): raw=gzip.decompress(raw)
        expected=(q["pending_exec_refused"]["raw_sha256"] if name=="group-v2/pending.tsv"
                  else q["historical_refusals"][Path(name).name[:2]]["raw_sha256"])
        need(digest(raw)==expected,"wrong negative or historical kernel ledger")
        try: events.parse(raw,expected_schema=2)
        except events.Refused: pass
        else: raise ValueError("accepted a known incomplete or unresolved native ledger")
    for case, code in CASES.items():
        data = get("original/"+case+".tsv")
        events.parse(data,expected_code=code,expected_sha=original["native"]["positive"][case]["sha256"],expected_schema=2)
    for case in ("racing-1","racing-2","active","wild"):
        data = get("group-v2/"+case+".tsv")
        closed = events.parse(data,expected_code=0,expected_schema=2)
        need(closed["sha256"]==q["native"][case]["raw_sha256"], "different group or Wild ledger")
    return binding

def command(root, folder, binding):
    observer=root/"kernel-tools/observe"
    need(binding["source"]==SOURCE and binding["source_sha256"]==OBSERVER and
         binding["boot"]==Path("/proc/sys/kernel/random/boot_id").read_text().strip() and
         str(observer)==binding["observer"] and sha(observer)==binding["observer_sha256"] and
         sha(Path(events.__file__))==binding["reader_sha256"]==READER, "wrong physical recorder")
    return [str(observer),str(folder/"positive.tsv"),"--",*CMD]

def retain(folder, out):
    ledger = folder/"positive.tsv"
    if ledger.exists():
        with ledger.open("rb") as data, (out/LEDGER).open("xb") as dest:
            with gzip.GzipFile(fileobj=dest,mode="wb",compresslevel=1,mtime=0) as z:
                while block:=data.read(1<<20):
                    z.write(block)

def projection(raw, tools):
    closed = events.parse(raw,expected_code=0,expected_schema=2)
    # This census uses the original numeric PIDs for linker ownership, so refuse a
    # reused PID or a displaced leader. Both cases remain represented in the raw ledger.
    need(closed["displaced"]==0 and closed["reaped"]==closed["lifetimes"], "unsupported PID takeover")
    parents, exits, post = {}, {}, set()
    root=None
    for line in raw.splitlines():
        tag, *fields = line.split(b"\t")
        if tag==b"R":
            root=int(fields[1])
        elif tag==b"N":
            parent, child=int(fields[1]),int(fields[4])
            need(child!=root and child not in parents, "reused PID")
            parents[child]=parent
        elif tag==b"T":
            pid,code=int(fields[1]),os.waitstatus_to_exitcode(int(fields[2]))
            need(pid not in exits, "reused terminal PID")
            exits[pid]=str(code) if code>=0 else signal.Signals(-code).name
        elif tag==b"P":
            post.add(int(fields[2]))
    need(root is not None and set(exits)==set(parents)|{root} and exits[root]=="0",
         "incomplete kernel family projection")
    rows, aliases = [], {}
    subject = {(tuple(t["dev_ino"]),t["sha256"]):key for key,t in tools.items()}
    need(len(subject)==len(tools), "ambiguous enrolled native images")
    for e in closed["execs"]:
        img=e["image"]; ident=((img["dev"],img["ino"]),img["sha256"])
        literal=Path(e["execfn"])
        if not literal.is_absolute(): literal=Path(e["cwd"])/literal
        name=literal.name
        role=subject.get(ident)
        is_tool=name in RELEVANT
        if role in {"cargo","rustc","wild","system_ld"}:
            need(is_tool,"registered executable hidden by unrecognized alias")
        if not is_tool: continue
        need(e["pid"]==e["former_tid"] and e["ordinal"] in post,"uncompleted relevant kernel image")
        if name in ("cargo","rustc"):
            need(role in (name,"rustup"), "foreign Cargo or compiler exec")
        if name in ("ld","ld.bfd","ld.gold","ld.lld","rust-lld","wild","wild-ld","mold"):
            need(role in ("wild","system_ld"), "foreign native linker")
        key=str(literal)
        fact={"physical":e["exe"],"sha256":img["sha256"],"dev_ino":list(ident[0])}
        if role and role!="rustup":
            need(e["exe"]==tools[role]["physical"], "kernel/provenance physical path disagreement")
        if role:
            # Hardlinked rustup's mapped name is routinely the originally requested cargo/rustc alias.
            fact=tools[role]
        need(key not in aliases or aliases[key]==fact,"executable under one path changed during Cargo")
        aliases[key]=fact
        rows.append([e["pid"],"KERNEL2\t"+json.dumps([key,e["argv"]],separators=(",",":"))])
    summary={k:closed[k] for k in ("schema","sha256","code","images","lifetimes","reaped","displaced","spawned")}
    summary["successful_execs"]=len(closed["execs"])
    return rows,parents,root,exits,aliases,summary

if __name__=="__main__":
    from linux_reopen import Corpus
    root=Path(sys.argv[1]).resolve()
    qualify(root,Path(sys.argv[2]))
    receipts=Corpus(root/"receipts")
    verify_fixtures(receipts,receipts.json("shared/enrollment.json"))
