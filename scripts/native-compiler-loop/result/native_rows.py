"""Re-read kernel argv and shared-stage rosters with the frozen ordinary check/build verifier."""

from collections import defaultdict
from pathlib import Path
import os, re
import formats as f
from signed_readers import read as J

HERE = Path(__file__).resolve().parent
PRIOR = J((HERE.parents[1] / "strict-unwrapped-profile/prior.json").read_bytes())[
    "observed"
]
GEN = "crates/ruff_unicode_names2_generator/src/lib.rs"
OPT = {"A": 0, "B": 1, "C": 2}
FLAG = "-Zshare-generics=no"


def actual_switches(a):
    opts = []
    for i, t in enumerate(a):
        if t in ("-C", "-Z"):
            group, arg = t, a[i + 1]
        elif len(t) > 2 and t[:2] in ("-C", "-Z"):
            group, arg = t[:2], t[2:]
        else:
            continue
        key, eq, v = arg.partition("=")
        if group == "-C" and key in ("metadata", "extra-filename"):
            pattern = "[0-9a-f]{16}" if key == "metadata" else "-[0-9a-f]{16}"
            assert re.fullmatch(pattern, v), (t, arg)
            v = "<Cargo artifact identity>"
        if group == "-C" and key == "incremental":
            assert Path(v).is_absolute() and "incremental" in Path(v).parts
            v = "<Cargo incremental output directory>"
        opts.append(group + key + (eq + v if eq else ""))
    return opts


def native(bs, path, tools, arm, roster):
    rid = tools["rustc"]["dev_ino"]
    wid = tools["wild"]["dev_ino"]
    history = defaultdict(list)
    stages = []
    compiles = []
    links = []
    selected = []
    levels = defaultdict(list)
    switches = defaultdict(list)
    for line in bs[path + "/kernel/exec.tsv"].decode().splitlines():
        idx, pid, dev, ino, _, exe = line.split("\t")
        pid = int(pid)
        ident = [int(dev), int(ino)]
        raw = bs[path + "/kernel/args-" + idx.zfill(4)]
        assert raw.endswith(b"\0")
        a = [os.fsdecode(x) for x in raw[:-1].split(b"\0")]
        assert "bridge-workspace-rustc" not in exe
        if (
            ident == rid
            and "--crate-name" in a
            and "--out-dir" in a
            and not any(x.startswith("--print") for x in a)
        ):
            assert not history[pid]
            crate = a[a.index("--crate-name") + 1]
            source = next(
                (n for n in a if n.endswith(".rs") and not n.startswith("-")), None
            )
            gen = source == GEN and crate == "unicode_names2_generator"
            flag = [x for x in a if "share-generics" in x]
            assert flag == ([FLAG] if gen and arm == "Q" else [])
            if gen:
                assert (
                    f.codegen(a) == (str(OPT[arm]), "on", "on")
                    and "--emit=dep-info,metadata,link" in a
                    and "--target" not in a
                    and "-Zohm-shared-stages" in a
                )
                selected.append([pid, a])
            if "-Zohm-shared-stages" in a:
                assert source
                stages.append(
                    source.split("/registry/src/", 1)[-1]
                    if "/registry/src/" in source
                    else source
                )
            assert not any(x in ("link-only", "-Zlink-only") for x in a)
            compiles.append([pid, crate])
            levels[f.physical_role(a)].append([*f.codegen(a), bool(flag)])
            switches[f.physical_role(a)].append(actual_switches(a))
        if ident == wid and "-o" in a:
            links.append([pid, a[a.index("-o") + 1]])
        history[pid].append(exe)
    observed = {
        "actual_full": len(compiles),
        "stage_sources": sorted(stages),
        "workspace": sum(x.startswith("crates/") for x in stages),
    }
    original = J(bs[path + "/ordinary-physical.json"])
    assert original == {
        "role": arm,
        "roster": roster,
        "stages": observed,
        "direct_rustcs": compiles,
        "wild": links,
        "generator_compiler": selected,
    }
    if roster:
        assert (
            observed == PRIOR[roster]
            and len(selected) == int(roster.endswith("-cold"))
            and len(links) == (48 if roster == "check-cold" else 1)
        )
    return (
        {
            "full": len(compiles),
            "wild": len(links),
            "workspace_shared_stage": observed["workspace"],
            "all_shared_stage": len(stages),
            "compiled_names": sorted(c[1] for c in compiles)
            if len(compiles) < 50
            else None,
            "selected_signed_compilers": selected,
        },
        dict(levels),
        dict(switches),
    )
