"""A separate direct compiler migration control. Cargo fixtures use no forced version or rustc options."""
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native import need, save, sha, call, environment

STAMP = "private-native-export-test-identical-header"
GRAPH = {"P":8,"C":9}
EPOCH = {"P":1,"C":2}


def meta(data):
    need(data[:8] == b"rust\0\0\0\n", "wrong metadata magic")
    n = 0
    for i,b in enumerate(data[16:22]):
        n |= (b & 127) << (7*i)
        if b < 128:
            start = 17+i
            return start, data[start:start+n].decode()
    raise ValueError("invalid metadata string")


def run(root, p, c, out):
    out.mkdir(parents=True)
    env = environment(root, p)
    env["RUSTC_FORCE_RUSTC_VERSION"] = STAMP
    w = root / "fixture"
    w.mkdir()
    (w / "subject.rs").write_text('pub fn value() -> u32 { 17 }\n')
    (w / "reader.rs").write_text('extern crate subject; fn main() {assert_eq!(subject::value(), 17); println!("matched 17");}\n')
    commands = {}
    versions = {}

    def invoke(label, args, expected):
        proc = call(args, env, w)
        d = out / label
        d.mkdir()
        (d / "stdout").write_bytes(proc.stdout)
        (d / "stderr").write_bytes(proc.stderr)
        save(d / "command.json", {"argv":list(map(str,args)), "exit":proc.returncode,"stdout":sha(d/"stdout"),"stderr":sha(d/"stderr")})
        need(proc.returncode == expected, (label,proc.returncode,expected,proc.stderr[-2000:]))
        commands[label] = proc.returncode
        return proc

    for role,label,state in ([("P","first-P","not-loaded"),("P","reuse-P","loaded")] +
                           ([("C","upgrade","not-loaded"),("C","reuse-C","loaded"),
                             ("P","downgrade","not-loaded"),("P","reuse-P2","loaded")] if c else [])):
        target = p if role == "P" else c
        alias = root / "rustup/toolchains/ohm"
        alias.unlink()
        alias.symlink_to(target.resolve())
        r = ["rustc", "+ohm"]
        if role not in versions:
            versions[role] = invoke("version-"+role,r+["-vV"],0).stdout.decode()
        invoke(label, r + ["subject.rs","--crate-name","subject","--crate-type","rlib","--emit=link,metadata",
                            "-Cincremental=inc","-Cmetadata=fixed","-Zassert-incr-state="+state], 0)
        graphs = [g for g in (w/"inc").rglob("dep-graph.bin") if not g.parent.name.endswith("-working")]
        need(len(graphs) == 1, ("different incremental root",graphs))
        graph = graphs[0]
        raw = graph.read_bytes()
        need(raw[:4] == b"RSIC" and struct.unpack_from("<H",raw,4)[0]==GRAPH[role]
             and raw[7:7+raw[6]].decode()==STAMP, "wrong physical graph")
        rm = (w/"libsubject.rmeta").read_bytes()
        start, version = meta(rm)
        suffix = f" (Ohm metadata {EPOCH[role]})"
        need(version.endswith(suffix), ("wrong physical metadata",version))
        own = out/label/"libsubject.rmeta"
        own.write_bytes(rm)
        other = f" (Ohm metadata {3-EPOCH[role]})"
        mutated = bytearray(rm)
        mutated[start:start+len(version)] = (version[:-len(suffix)]+other).encode()
        need(len(mutated)==len(rm) and sum(x!=y for x,y in zip(rm,mutated))==1,"epoch mutation not isolated")
        changed = out/label/"libother.rmeta"
        changed.write_bytes(mutated)
        save(out/label/"headers.json", {"version":version,"graph":sha(graph),"generation":GRAPH[role],
              "stamp":STAMP,"private_session_directory":str(graph.parent.relative_to(w/"inc")),
              "actual":sha(own), "one_byte_control":sha(changed)})
        def reject(name, path):
            f=w/"rejected.rmeta"
            need(not f.exists(),"stale rejection output")
            result=invoke(name,r+["reader.rs","--emit=metadata","--error-format=json","--extern","subject="+str(path),"-o",f],1)
            errors=[json.loads(e) for e in result.stderr.splitlines() if e.startswith(b"{")]
            need(any((e.get("code") or {}).get("code")=="E0514" and "subject" in e["message"] for e in errors)
                 and not f.exists(),"incorrect compatibility diagnostic")
        reject(label+"-one-byte", changed)
        if label in ("upgrade","downgrade"):
            reject(label+"-real-other",out/("reuse-P" if role=="C" else "reuse-C")/"libsubject.rmeta")
        invoke(label+"-link",r+["reader.rs","--extern","subject=libsubject.rlib","-o","reader"],0)
        need(invoke(label+"-run",["./reader"],0).stdout == b"matched 17\n","wrong native result")
    save(out/"verified.json",{"commands":commands,"versions":versions,"shared_graph_stamp":STAMP,
          "epochs":EPOCH,"generations":GRAPH,"scope":"actual cache read and direct foreign rmeta, independent one-byte mutations"})


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("work",type=Path);a.add_argument("out",type=Path);a.add_argument("parent",type=Path)
    a.add_argument("--candidate",type=Path)
    v=a.parse_args()
    run(v.work.resolve(),v.parent.resolve(),v.candidate.resolve() if v.candidate else None,v.out.resolve())
