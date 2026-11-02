"""Trace an unchanged test build after all metered commands in its history."""
from pathlib import Path
import re


def input_files(r, work, binary, out):
    folder = out/"fingerprints"
    folder.mkdir()
    suffix = binary.name.rsplit("-", 1)[-1]
    names = (binary.name+".d", "test-integration-test-e2e.json", "dep-test-integration-test-e2e")
    matches = {}
    for area in ("target", "build"):
        for name in names:
            for p in sorted((work/area).rglob(name)):
                if p.name != names[0] and not (p.parent.name.endswith("-"+suffix) or
                                               (p.parent.name == "fingerprint" and p.parent.parent.name == suffix)):
                    continue
                if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(work) or p.stat().st_size > 4*1024**2:
                    raise ValueError(("unexpected owner dep-info", p))
                data = p.read_bytes()
                key = str(p.relative_to(work))
                keep = folder/f"{len(matches):02}-{p.name}"
                keep.write_bytes(data)
                matches[key] = {"sha256":r.sha(keep), "bytes":len(data),
                                "ohm_markers":sorted({m.decode() for m in re.findall(rb"/dev/null/ohm-[a-z0-9-]+",data)})}
    r.put(out/"dependency-files.json", matches)


def dependency_markers(r, work, out):
    names = re.compile(rb"(?:^|/)(ohm-(?:recheck-dependent-links(?:-v2)?|untracked-relink-inputs|foreign-span-bytes|untrackable-foreign-span))(?=[\x00\s:]|$)")
    marked = {}
    scanned = 0
    skipped = []
    folder = out/"fingerprints"
    for area in ("target", "build"):
        for p in sorted((work/area).rglob("*.d")):
            key = str(p.relative_to(work))
            if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(work) or p.stat().st_size > 16*1024**2:
                skipped.append(key)
                continue
            data = p.read_bytes()
            scanned += 1
            hits = sorted({m.decode() for m in names.findall(data)})
            if hits:
                stored = folder/f"markers-{len(marked):04}-{p.name}"
                stored.write_bytes(data)
                marked[key] = {"saved":stored.name, "sha256":r.sha(stored), "bytes":len(data), "markers":hits}
    r.put(out/"transitive-markers.json", {"scanned":scanned, "skipped":skipped, "marked":marked})


def execs(out):
    processes = []
    for f in sorted(out.glob("exec.[0-9]*")):
        for line in f.read_text(errors="replace").splitlines():
            if not re.search(r" = 0\s*$",line):
                continue
            m = re.match(r'^(?:execve\(|execveat\([^,]+, )"([^"\\]+)"',line)
            if not m:
                raise ValueError(("unrecognized successful exec trace", line[:180]))
            exe = Path(m[1])
            name = exe.name
            role = "process"
            if name == "rustc" and '"--crate-name", "e2e"' in line:
                role = "e2e-rustc"
            elif name in {"ld", "ld.bfd", "ld.gold", "ld.lld", "rust-lld", "wild", "ld.wild", "mold"} or name.endswith(("-ld", "-ld.bfd", "-ld.lld", "-ld.wild")):
                role = "linker"
            elif name in {"gcc", "clang", "cc", "collect2"} or name.endswith(("-gcc","-clang")):
                role = "driver"
            processes.append({"pid":int(f.name.split(".")[-1]),"executable":str(exe),"role":role})
    if not processes or not any(Path(row["executable"]).name == "cargo" for row in processes):
        raise ValueError("missing successful native Cargo exec")
    return processes


def collect(r, e, w, cli, repo, env, work, out, expected, owners, blobs, stable_dirty, repaired):
    out.mkdir()
    source = e.source_state(r,repo,blobs,"repair")
    old = r.sha(repaired)
    input_files(r,work,repaired,out)
    result = {}
    for phase in ("ordinary","traced","fingerprint"):
        argv = list(cli)
        extra = dict(env)
        if phase == "fingerprint":
            extra["CARGO_LOG"] = "cargo::compiler::fingerprint=trace"
        if phase == "traced":
            argv = ["strace","-ff","-qq","-e","trace=execve,execveat","-e","signal=none",
                    "-s","1024","-o",str(out/"exec"),"--",*argv]
        dest = out/phase
        r.run(argv,repo,extra,dest,work,out)
        rows = r.cargo_rows((dest/"outer.stdout").read_bytes())
        w.ownership.check_roots(rows,work)
        dirty, keys, binary = e.products(rows,expected,owners,"unchanged",work,repo)
        digest = r.sha(binary)
        same_product = binary.samefile(repaired) and digest == old
        e.need(source == e.source_state(r,repo,blobs,"repair"), ("changed effective source",phase))
        if phase != "fingerprint":
            e.need(same_product, ("ordinary invocation changed executable",phase))
        r.run([binary,"--exact",e.ADDED,"--nocapture"],repo,env,dest/"native",work,out)
        e.executed((dest/"native/outer.stdout").read_text(),(dest/"native/outer.stderr").read_text(),e.ADDED,False)
        e.need(not (dest/"clock.json").exists(), "diagnostic command was metered")
        result[phase] = {"dirty_keys":dirty, "products":len(keys), "binary":digest, "same_product":same_product}
        r.put(dest/"result.json",result[phase])
        if phase == "fingerprint":
            logs = (dest/"outer.stderr").read_bytes()
            e.need(b"cargo::compiler::fingerprint" in logs, "signed Cargo emitted no fingerprint records")
            result["fingerprint_lines"] = sum(b"cargo::compiler::fingerprint" in line for line in logs.splitlines())
        if phase == "traced":
            result["processes"] = execs(out)
            result["matches_original_unchanged"] = all(result[p]["dirty_keys"] == stable_dirty for p in ("ordinary","traced"))
            r.put(out/"ordinary-trace.json",result)
    dependency_markers(r, work, out)
    r.put(out/"trace.json",result)
