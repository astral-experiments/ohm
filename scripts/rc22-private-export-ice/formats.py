"""A separate direct compiler migration control. Cargo fixtures use no forced version or rustc options."""
import argparse
import json
import os
import shlex
from pathlib import Path
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native import need, save, sha, call, environment

STAMP = "private-native-export-test-identical-header"
GRAPH = {"P":8,"C":10}
EPOCH = {"P":1,"C":3}


def meta(data):
    need(data[:8] == b"rust\0\0\0\n", "wrong metadata magic")
    n = 0
    for i,b in enumerate(data[16:22]):
        n |= (b & 127) << (7*i)
        if b < 128:
            start = 17+i
            return start, data[start:start+n].decode()
    raise ValueError("invalid metadata string")


def run(root, p, c, out, previous=None):
    out.mkdir(parents=True)
    env = environment(root, p)
    env["RUSTC_FORCE_RUSTC_VERSION"] = STAMP
    w = root / "fixture"
    w.mkdir()
    (w / "subject.rs").write_text('pub fn value() -> u32 { 17 }\n')
    (w / "reader.rs").write_text('extern crate subject; fn main() {assert_eq!(subject::value(), 17); println!("matched 17");}\n')
    commands = {}
    versions = {}
    prefix_flags = {}
    env["RUSTC_LOG"] = "ohm_metadata_reuse=info"

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

    visits = [("P","first-P","not-loaded"),("P","reuse-P","loaded")]
    if c:
        visits += [("C","upgrade","not-loaded"),("C","reuse-C","loaded"),("P","downgrade","not-loaded"),
                   ("P","reuse-P2","loaded"),("C","empty-C","not-loaded"),
                   ("C","synthetic-generation-9","not-loaded"),("C","reuse-repaired-C","loaded")]
    visits += [("P","empty-P","not-loaded")]
    for role,label,state in visits:
        if label.startswith("empty-"):
            (w/"inc").rename(w/("inc-before-"+label))
        if label=="synthetic-generation-9":
            g,=[x for x in (w/"inc").rglob("dep-graph.bin") if not x.parent.name.endswith("-working")]
            original=g.read_bytes()
            need(original[4:6]==struct.pack("<H",10),"unexpected existing generation")
            need(list(g.parent.glob("*.ohm-prefix-*")),"missing previous prefix during substitution")
            replaced=g.with_name("own-previous-generation.tmp")
            replaced.write_bytes(original[:4]+struct.pack("<H",9)+original[6:]);replaced.replace(g)
            save(out/"generation-9-control.json",{"source":"one generation change to the actual private candidate graph",
                 "before":sha(out/"empty-C"/"libsubject.rmeta"),"original_graph_sha":__import__("hashlib").sha256(original).hexdigest(),
                 "substituted_graph":sha(g),"unchanged_prefixes":{p.name:sha(p) for p in g.parent.glob("*.ohm-prefix-*")}})
        target = p if role == "P" else c
        alias = root / "rustup/toolchains/ohm"
        alias.unlink()
        alias.symlink_to(target.resolve())
        r = ["rustc", "+ohm"]
        if role not in versions:
            versions[role] = invoke("version-"+role,r+["-vV"],0).stdout.decode()
            ordinary = w / ("normal-"+role)
            (ordinary/"src").mkdir(parents=True)
            (ordinary/"src/lib.rs").write_bytes((w/"subject.rs").read_bytes())
            (ordinary/"Cargo.toml").write_text('[package]\nname="export_prefix_control"\nversion="0.0.0"\nedition="2024"\n[workspace]\n')
            cargo = invoke("normal-cargo-"+role,["cargo","+ohm","build","-vv","--offline","--manifest-path",ordinary/"Cargo.toml"],0)
            line, = [l.strip() for l in cargo.stderr.decode().splitlines() if "Running `" in l and "--crate-name export_prefix_control " in l]
            parts=shlex.split(line.split("Running `",1)[1].removesuffix("`"))
            k=parts.index("--crate-name")
            prefix_flags[role],=[v for v in parts if v=="-Zpublic-api-hash"]
            exe, = [Path(v) for v in parts[:k] if v.startswith("/") and v.endswith("/bin/rustc")]
            need(exe.samefile(target/"bin/rustc"), "different Cargo compiler")
            inc, = [Path(v.removeprefix("incremental=")) for v in parts if v.startswith("incremental=")]
            need(inc.resolve().is_relative_to(root/"target") and inc.is_dir(),"wrong private Cargo cache")
            actual=[x for x in inc.rglob("*.ohm-prefix-*") if x.is_file()]
            need(actual,"normal Cargo did not create a metadata prefix")
            save(out/("normal-cargo-"+role)/"prefixes.json",{"actual_flag":prefix_flags[role],
                 "ordinary":[[str(x.relative_to(root)),sha(x)] for x in sorted(actual)]})
        invoke(label, r + ["subject.rs","--crate-name","subject","--crate-type","rlib","--emit=link,metadata",
                            "-Cincremental=inc","-Cmetadata=fixed",prefix_flags[role],"-Zassert-incr-state="+state], 0)
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
        if label.startswith("empty-"):
            peers = ("first-P","reuse-P") if role=="P" else ("upgrade","reuse-C")
            if c and role=="P":
                peers += ("downgrade","reuse-P2")
            need(all((out/name/"libsubject.rmeta").read_bytes()==rm for name in peers),
                 ("different complete same-role clean metadata",label,peers))
        other = " (Ohm metadata 2)"
        mutated = bytearray(rm)
        mutated[start:start+len(version)] = (version[:-len(suffix)]+other).encode()
        need(len(mutated)==len(rm) and sum(x!=y for x,y in zip(rm,mutated))==1,"epoch mutation not isolated")
        changed = out/label/"libother.rmeta"
        changed.write_bytes(mutated)
        prefixes={f.name:sha(f) for f in sorted(graph.parent.glob("*.ohm-prefix-*"))}
        need(prefixes and (graph.parent/"metadata.rmeta").read_bytes()==rm, "no matching finalized prefix/metadata")
        if label in ("upgrade","downgrade"):
            need(b"reused metadata item prefix" not in (out/label/"stderr").read_bytes(), "reused foreign-epoch prefix")
        save(out/label/"headers.json", {"version":version,"graph":sha(graph),"generation":GRAPH[role],"prefixes":prefixes,
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
        if role=="C" and label=="upgrade":
            need(previous and sha(previous)=="1f38f5367ebc64a846729456a9764280beb94182fa00b6d3fd4e48d68e21c4ae",
                 "missing actual predecessor compiler metadata")
            reject("reject-actual-previous-epoch2", previous)
        if label in ("synthetic-generation-9","reuse-repaired-C"):
            need(rm==(out/"empty-C"/"libsubject.rmeta").read_bytes(),"previous generation influenced complete current rmeta")
        if label in ("upgrade","downgrade"):
            reject(label+"-real-other",out/("reuse-P" if role=="C" else "reuse-C")/"libsubject.rmeta")
        invoke(label+"-link",r+["reader.rs","--extern","subject=libsubject.rlib","-o","reader"],0)
        need(invoke(label+"-run",["./reader"],0).stdout == b"matched 17\n","wrong native result")
    save(out/"verified.json",{"commands":commands,"versions":versions,"shared_graph_stamp":STAMP,
          "epochs":EPOCH,"generations":GRAPH,"scope":"actual cache read and direct foreign rmeta, independent one-byte mutations"})


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("work",type=Path);a.add_argument("out",type=Path);a.add_argument("parent",type=Path)
    a.add_argument("--candidate",type=Path);a.add_argument("--previous",type=Path)
    v=a.parse_args()
    run(v.work.resolve(),v.parent.resolve(),v.candidate.resolve() if v.candidate else None,v.out.resolve(),v.previous.resolve() if v.previous else None)
