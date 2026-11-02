"""Distinguish caller flags from signed Cargo's standard export to a build script."""
from pathlib import Path
import re

DENIED={"LD_PRELOAD","LD_AUDIT","RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER","CARGO_BUILD_RUSTC_WRAPPER",
        "CARGO_BUILD_RUSTC_WORKSPACE_WRAPPER","OHM_LDV_GUARD"}
SCRIPT=re.compile(r"(?:/build-script-build|/out/build_script_build|/build_script_build-[0-9a-f]+)$")


def flags(sdk):
    linker=Path(sdk)/"lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld"
    return "\x1f".join(["-Zpublic-api-hash","-Zthreads=8","-Zohm-early-metadata","-Clinker-features=-lld",
                        "-Clink-self-contained=-linker",f"-Clink-arg=-B{linker}","-Clink-arg=-fuse-ld=bfd"])


def check(env,sdk=None):
    if any(k.startswith("QA_LDV_") or (k.startswith("CARGO_") and "TRUST" in k) or k in DENIED
           or (k=="RUSTFLAGS" and v) for k,v in env.items()):
        raise ValueError("unregistered compiler/plugin/wrapper environment")
    value=env.get("CARGO_ENCODED_RUSTFLAGS","")
    if value and (sdk is None or value!=flags(sdk)):
        raise ValueError("nonstandard rustflags in launcher or child")
    return bool(value)


def ancestry(pid,parents):
    path=[]
    while pid in parents:
        pid=parents[pid]
        if pid in path:
            raise ValueError("cyclic exec ancestry")
        path.append(pid)
    return path


def owners(generated,parents,signed_cargo,entry):
    """Every occurrence must originate in a real build script beneath the actual Cargo process."""
    check(entry)
    roots=[Path(entry[k]) for k in ("CARGO_TARGET_DIR","CARGO_BUILD_BUILD_DIR") if k in entry]
    scripts={(pid,exe) for pid,exe in generated if SCRIPT.search(exe) and
             ".." not in Path(exe).parts and any(root.is_absolute() and Path(exe).is_relative_to(root) for root in roots)}
    script_pids={pid for pid,_ in scripts}
    for pid,exe in scripts:
        if not signed_cargo.intersection(ancestry(pid,parents)):
            raise ValueError("build script with rustflags outside the signed Cargo process tree")
    for pid,exe in generated:
        if (pid,exe) not in scripts and not script_pids.intersection(ancestry(pid,parents)):
            raise ValueError("encoded rustflags outside a real Cargo-launched build script")
    return {"execs_with_export":len(generated),"build_scripts":len(scripts)}
