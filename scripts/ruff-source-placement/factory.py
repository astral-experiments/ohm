"""Two independent, matched, complete stage1 builds on the proven #337 source factory."""
import ast
import gzip
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import CRATES, HERE, HOST, LEGACY, PARENT, capsule, enrollment, git, need, save, sha
import build as previous
import physical

EXEC = re.compile(r'^execve\(("(?:\\.|[^"\\])*"), (\[.*\]), [^\n]*\)\s+= 0$')
WRAPPER = "OhmSourcePlacement.cpp"
COALESCER = "OhmRegisterCoalescer.cpp"


def setup(ws, root, reg):
    need(platform.machine() == "x86_64" and len(os.sched_getaffinity(0)) >= 8, "requires eight GNU CPUs")
    need(git(ws / "source-factory", "rev-parse", "HEAD") == reg["source_factory"], "unexpected source factory")
    spec = json.loads((ws / "source-factory/scripts/rc23-expanded-inputs/registration.json").read_bytes())
    need(git(ws, "rev-parse", "HEAD") == spec["coordinator"] and git(ws / "packed", "rev-parse", "HEAD") == reg["kit"]["commit"],
         "unexpected release coordinator or runtime freezer")
    kit = ws / "packed/scripts/ohm-packed-ruff"
    need(all(sha(kit / p) == reg["kit"][p] for p in ("runtime.py", "prepare.sh")), "altered runtime freezer")
    root.mkdir()
    (root / "logs").mkdir()
    save(root / "logs/entry.json", {"qa": os.environ["GITHUB_SHA"], "source": reg["roles"], "source_registration": sha(HERE / "registration.json"),
         "original_registration": sha(LEGACY / "registration.json"), "physical_factory": git(ws / "source-factory", "rev-parse", "HEAD"),
         "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "host": platform.uname()._asdict(),
         "cpus": sorted(os.sched_getaffinity(0))})


def verified_sources(rust, reg):
    # This first, immutable bundle reconstructs the actual public #337 head from the same source factory.
    previous.bundle(rust)
    p, c = [reg["roles"][role]["revision"] for role in ("P", "C")]
    need(git(rust, "rev-parse", "FETCH_HEAD") == p == PARENT and sha(LEGACY / "candidate.bundle") == reg["previous_bundle_sha256"],
         "wrong first source segment")
    bundle = str(HERE / "candidate.bundle")
    need(git(rust, "bundle", "list-heads", bundle) == c + " HEAD", "incorrect child transport")
    git(rust, "bundle", "verify", bundle)
    git(rust, "fetch", "--no-tags", "--no-recurse-submodules", bundle, "HEAD")
    need(git(rust, "rev-parse", "FETCH_HEAD", c + "^").splitlines() == [c, p], "incorrect direct ancestry")
    changes = reg["changed_sources"]
    need(git(rust, "diff", "--name-status", "--no-renames", p, c).splitlines() ==
         [("M" if row["P"] else "A") + "\t" + path for path, row in sorted(changes.items())], "unregistered compiler edit")
    for role, row in reg["roles"].items():
        rev = row["revision"]
        need(git(rust, "rev-parse", rev + "^{tree}", rev + ":compiler").splitlines() == [row["tree"], row["compiler"]], "different Rust source tree")
        for path, objects in changes.items():
            oid = objects[role]
            need(git(rust, "ls-tree", rev, "--", path) == ("100644 blob " + oid + "\t" + path if oid else ""), ("source blob", role, path))
        need(all(git(rust, "rev-parse", rev + ":" + k) == v for k, v in reg["unchanged"].items()), "unexpected coalescer, LLVM, std or bootstrap")


def constructor_receipt(traces, stage0, rust, out, role, reg):
    rusts = {crate: [] for crate in CRATES}
    native = {name: [] for name in (COALESCER, WRAPPER)}
    total = 0
    with gzip.open(out / (role + "-constructors.jsonl.gz"), "xt", encoding="utf-8") as raw:
        for path in sorted(traces.glob("exec.*")):
            with path.open() as f:
                for line in f:
                    if not line.startswith("execve(") or not line.rstrip().endswith("= 0"):
                        continue
                    total += 1
                    if not any(s in line for s in (*CRATES, COALESCER, WRAPPER)):
                        continue
                    m = EXEC.fullmatch(line.rstrip())
                    need(m is not None, ("unreadable selected physical build command", line[:90]))
                    exe = Path(ast.literal_eval(m[1]))
                    is_real_rustc = exe.is_file() and exe.samefile(stage0)
                    is_watched_cxx = '"-c"' in m[2] and any(n + '"' in m[2] for n in native)
                    if not is_real_rustc and not is_watched_cxx:
                        continue
                    args = ast.literal_eval(m[2])
                    need(isinstance(args, list) and all(isinstance(a, str) for a in args), "abbreviated selected kernel argv")
                    row = None
                    if "--crate-name" in args:
                        crate = args[args.index("--crate-name") + 1]
                        if crate in rusts and is_real_rustc:
                            rs = [a for a in args if a.endswith("compiler/" + crate + "/src/lib.rs") or a == "compiler/" + crate + "/src/lib.rs"]
                            if rs and any(v.startswith("--emit") and "link" in v for v in args):
                                row = {"crate": crate, "source": rs, "exe": str(exe), "pid": int(path.suffix[1:]), "argv": args}
                                rusts[crate].append({"pid": row["pid"], "path": rs[0]})
                    if "-c" in args:
                        for name in native:
                            source = [v for v in args if Path(v).name == name]
                            if source:
                                base = rust / "compiler/rustc_llvm/llvm-wrapper" / name
                                need(base.is_file(), "unregistered C++ source")
                                row = {"cpp": name, "pid": int(path.suffix[1:]), "exe": str(exe), "argv": args, "sha256": sha(base)}
                                native[name].append({"pid": row["pid"], "sha256": row["sha256"]})
                    if row:
                        print(json.dumps(row, sort_keys=True), file=raw)
    need(all(rusts.values()) and native[COALESCER] and bool(native[WRAPPER]) == (role == "C"),
         ("missing actual source producer", role, {k: len(v) for k,v in rusts.items()}, {k:len(v) for k,v in native.items()}))
    return {"role": role, "total_physical_execs": total, "stage0_rustc": sha(stage0), "source": reg["roles"][role],
            "rustc_crates": rusts, "cxx": native, "native_selection": sha(out / (role + "-constructors.jsonl.gz"))}


def source_build(ws, root, reg):
    rust = ws / "source/rust"
    orig = json.loads((root / "logs/source.json").read_bytes())
    need(git(rust, "rev-parse", "HEAD") == orig["source"]["rust"] and orig["qa"] == os.environ["GITHUB_SHA"], "incomplete authenticated composite")
    verified_sources(rust, reg)
    kit = previous.load("frozen_runtime", ws / "packed/scripts/ohm-packed-ruff/runtime.py")
    layout = previous.load("actual_layout", ws / "legacy/scripts/dep-graph-slots/layout.py")
    source = json.loads((ws / "source-factory/scripts/rc23-expanded-inputs/registration.json").read_bytes())
    substitutions = {"src/tools/" + n: (source["sources"][n]["end"], source["sources"][n]["tree"]) for n in ("clippy", "rustfmt")}
    capsule_path = root / "capsule"
    (capsule_path / "objects").mkdir(parents=True)
    signed = previous.signed_tools(root)
    env = previous.private_env(root)
    os.chdir(rust)
    directory = root / "build"
    docs = {}
    for role, desc in sorted(reg["roles"].items(), reverse=True):
        rev = desc["revision"]
        git(rust, "checkout", "--quiet", "--detach", "--no-recurse-submodules", rev)
        full = json.loads(json.dumps(layout.checked(rust, rev, desc["tree"], substitutions)))
        need(full["gitlinks"] == orig["layout"]["gitlinks"] and full["authorized_differences"] == orig["layout"]["authorized_differences"], "changed nested sources")
        directory.mkdir()
        need(not any(directory.iterdir()), "bootstrap reused another role")
        st = directory.stat()
        argv = [sys.executable, "-IB", str(rust / "x.py"), "--build-dir", str(directory), *reg["bootstrap_flags"],
                "build", "--stage", "1", "-j8", "compiler/rustc", "library", "src/tools/rustdoc"]
        traces = root / ("stage-exec-" + role)
        traces.mkdir()
        actual = ["/usr/bin/strace", "-ff", "-qq", "-s", "131072", "-e", "trace=execve,execveat", "-o", str(traces / "exec"), "--", *argv]
        save(root / "logs" / (role + "-inputs.json"), {"source": desc, "full_layout": full, "empty": True, "argv": argv, "observer": actual, "epoch": reg["source_epoch"]})
        print("Starting clean stage1", role, rev, flush=True)
        log = root / "logs" / ("build-" + role + ".log")
        try:
            previous.guarded(actual, rust, env, log, root)
        except BaseException:
            if log.exists():
                subprocess.run(["tail","-130",log])
            raise
        stage = directory / HOST / "stage1"
        compiled = constructor_receipt(traces, directory / HOST / "stage0/bin/rustc", rust, root / "logs", role, reg)
        save(root / "logs" / (role + "-constructed.json"), compiled)
        inv = physical.symbol_inventory(stage, "C")  # Both arms retain the proven #337 and #326 code.
        driver = stage / "lib" / inv["driver"]
        symbols = {}
        with subprocess.Popen(["nm","--defined-only",driver],stdout=subprocess.PIPE,text=True) as nm:
            for line in nm.stdout:
                row = line.split()
                if row[-1:] == ["LLVMRustGetSourcePlacement"]:
                    need(len(row) == 3 and row[1] in ("t","T") and not symbols, "ambiguous wrapper in real driver")
                    symbols[row[2]] = row[0]
            need(nm.wait() == 0, "could not read actual driver symbol set")
        need(bool(symbols) == (role == "C"), ("incorrect executing driver wrapper",role,symbols))
        save(root / "logs" / (role + "-driver.json"), {"coalescer_and_ldv": inv, "placement": symbols})
        kit.freeze(stage, role, rev)
        docdest = root / "documentation" / role
        docdest.mkdir(parents=True)
        doc = stage / "bin/rustdoc"
        shutil.copy2(doc, docdest / "rustdoc")
        docs[role] = [sha(doc), doc.stat().st_size, doc.stat().st_mode & 0o777]
        example = docdest / "witness.rs"
        example.write_text("/// Placement SDK documentation witness.\npub fn placement_witness() -> usize { 1 }\n")
        html = docdest / "html"
        docenv = env | {"LD_LIBRARY_PATH":str(stage / "lib")}
        subprocess.run([doc,"--crate-name","osp_witness","--edition=2024","-o",html,example],env=docenv,check=True)
        page = html / "osp_witness/fn.placement_witness.html"
        need(b"Placement SDK documentation witness." in page.read_bytes(), "missing real generated documentation")
        save(root / "logs" / (role + "-docs.json"), {"rustdoc":docs[role],"source":rev,"html_sha256":sha(page)})
        need(json.loads(json.dumps(layout.checked(rust, rev, desc["tree"], substitutions))) == full, "bootstrap changed Rust checkout")
        after = directory.stat()
        need(not directory.is_symlink() and (st.st_dev,st.st_ino) == (after.st_dev,after.st_ino), "observed build root replaced")
        shutil.rmtree(directory)  # This job's freshly created, already frozen stage directory only.
        shutil.rmtree(traces)  # The actual selected compiler commands are already durably retained above.
    receipt = {"schema":"ohm-remat-rustc-capsule-v1","registration":sha(HERE / "registration.json"),"source_sha256":sha(root/"logs/source.json"),
               "signed_tools":signed,"manifests":{r:sha(capsule_path/(r+".json")) for r in reg["roles"]}}
    save(capsule_path / "qualified.json", receipt)
    capsule.seal(capsule_path)
    manifests=capsule.admit(capsule_path)
    proof = {r:{k:{"member":next(n for n in manifest if n.startswith(prefix))} for k,prefix in (("driver","lib/librustc_driver-"),("frontend","bin/rustc"))} for r,manifest in manifests.items()}
    for r, items in proof.items():
        for row in items.values():
            row["sha256"]=manifests[r][row["member"]][0]
    save(root/"logs/factory.json", {"registration":sha(HERE/"registration.json"),"roles":reg["roles"],"physical":proof,
                                    "docs":docs,"qualified":sha(capsule_path/"qualified.json")})
    out=root/"transport"
    out.mkdir()
    artifact=out/"placement-sdk.tar.zst"
    members=["capsule","documentation/P/rustdoc","documentation/C/rustdoc","logs/entry.json","logs/source.json","logs/factory.json"]
    for r in ("P","C"):
        members += ["logs/"+r+"-"+tail for tail in ("driver.json","constructed.json","constructors.jsonl.gz","inputs.json","docs.json")]
    subprocess.run(["tar","--sort=name","--mtime=@0","--owner=0","--group=0","--numeric-owner","-C",root,"-I","zstd -3 -T2","-cf",artifact,*members],check=True)
    need(0 < artifact.stat().st_size < 768 << 20, "excess matched runtime archive")
    save(out/"seal.json",{"factory_run":int(os.environ["GITHUB_RUN_ID"]),"qa":os.environ["GITHUB_SHA"],"candidate":reg["roles"]["C"]["revision"],
                          "sha256":sha(artifact),"bytes":artifact.stat().st_size,"factory":sha(root/"logs/factory.json"),
                          "boot":json.loads((root/"logs/entry.json").read_bytes())["boot"]})
    print("Both independent physical SDKs sealed", sha(artifact), flush=True)


if __name__ == "__main__":
    reg=enrollment()
    ws=Path(os.environ["GITHUB_WORKSPACE"]).resolve(strict=True)
    root=Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)/"ohm-branch-object-qa"
    {"preflight":setup,"build":source_build}[sys.argv[1]](ws, root, reg)
