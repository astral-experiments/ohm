#!/usr/bin/python3
"""Pass ordinary invocations through and freeze just the selected compiler's two outputs."""

import gzip
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def selected(argv):
    return (
        "--crate-name" in argv
        and argv[argv.index("--crate-name") + 1] == "ruff_workspace"
        and "--crate-type" in argv
        and argv[argv.index("--crate-type") + 1] == "lib"
        and any(x.startswith("--emit=") and "link" in x[7:].split(",") for x in argv)
    )


def original_identity(argv):
    """Fields which identify the owner, callers, crate disambiguator and codegen configuration."""
    options = {name: argv[argv.index(name) + 1] for name in ("--crate-name", "--crate-type")}
    options["features"] = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--cfg"]
    options["source"] = [arg for arg in argv if arg.endswith(".rs")]
    options["configuration"] = [arg for arg in argv if arg.startswith(
        ("--emit=", "--edition=", "metadata=", "extra-filename=", "incremental=",
         "opt-level=", "debuginfo=", "codegen-units=", "-Zohm-", "-Zthreads=", "-Zpublic-api-hash", "-Zremap-cwd-prefix="))]
    options["extern_names"] = [argv[i + 1].split("=")[0] for i, arg in enumerate(argv) if arg == "--extern"]
    return options


def freeze(source, destination):
    st = source.stat()
    need(source.is_file() and not source.is_symlink() and 0 < st.st_size <= (2 << 30), ("extent", source, st.st_size))
    h = hashlib.sha256()
    length = 0
    with source.open("rb") as r, destination.open("xb") as f, gzip.GzipFile(filename="", fileobj=f, mode="wb", compresslevel=4, mtime=0) as z:
        while chunk := r.read(1 << 20):
            z.write(chunk)
            length += len(chunk)
            h.update(chunk)
    end = source.stat()
    need((st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size) == (end.st_dev, end.st_ino, end.st_mtime_ns, end.st_ctime_ns, length), "compiler artifact changed while freezing")
    return dict(length=length, sha256=h.hexdigest(), gzip_sha256=sha(destination))


def main():
    rustc, *argv = sys.argv[1:]
    if not selected(argv):
        os.execv(rustc, [rustc, *argv])
    sdk = Path(os.environ["PROFILE_SIGNED_SDK"])
    dest = Path(os.environ["PROFILE_RECEIPT"])
    profiles = Path(os.environ["PROFILE_DIRECTORY"])
    expected = sdk / "bin/rustc"
    need(Path(rustc).samefile(expected) and sha(expected) == "7e35096dab1b661924cb3c31982c870dd99c7c00a7fba28aa958f451e7c9474e", "signed compiler")
    need(Path.cwd() == Path(os.environ["PROFILE_RUFF_ROOT"]) and not any("self-profile" in x for x in argv), "ordinary Ruff owner")
    with (dest / "owner.original.nul").open("xb") as f:
        f.write(b"\0".join(os.fsencode(x) for x in [rustc, *argv]) + b"\0")
    inc, = [Path(x.partition("incremental=")[2]) for x in argv if x.startswith(("incremental=", "-Cincremental="))]
    need(inc.is_absolute() and inc.is_relative_to(Path(os.environ["PROFILE_WORK_ROOT"])), "private incremental root")
    get_graphs = lambda: set(inc.glob("ruff_workspace-*/s-*/dep-graph.bin"))
    need(not get_graphs() and not list(profiles.iterdir()), "nonempty cold owner")
    cmd = [rustc, *argv, "-Zself-profile=" + str(profiles), "-Zself-profile-events=default,query-keys"]
    proc = subprocess.Popen(cmd)
    status = proc.wait()
    need(status == 0, ("signed rustc status", proc.pid, status))
    graph, = get_graphs()
    profile, = profiles.glob("*.mm_profdata")
    need(int(profile.stem.rsplit("-", 1)[1]) == proc.pid and not graph.parent.name.endswith("-working"), "completed same-process graph/profile")
    alias = "ohm-build-dep-graph.bin"
    need(sha(graph) == sha(graph.parent / alias), "canonical signed build graph")
    state = dict(
        pid=proc.pid, argv=cmd, cwd=str(Path.cwd()), graph_alias=alias,
        owner_identity=original_identity(argv), original_sha256=sha(dest / "owner.original.nul"),
        signed_rustc=sha(expected), current_graph_name=str(graph), profile_name=str(profile),
        source=sha(Path("crates/ruff_workspace/src/lib.rs")), previous_sessions=[],
        selected_probe_options=cmd[-2:],
    )
    for label, path in (("graph", graph), ("profile", profile)):
        state[label] = freeze(path, dest / (label + ".gz"))
    with (dest / "process.json").open("x") as f:
        json.dump(state, f, indent=2, sort_keys=True)


if __name__ == "__main__":
    main()
