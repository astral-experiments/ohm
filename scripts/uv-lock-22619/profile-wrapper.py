#!/usr/bin/python3
"""Record and profile only the selected check-mode library, preserving Cargo's original unit."""
import json, os, sys
from pathlib import Path
rustc, *args = sys.argv[1:]
assert rustc == os.environ["OHM_EXPECTED_RUSTC"], (rustc, os.environ["OHM_EXPECTED_RUSTC"])
if "--crate-name" in args and args[args.index("--crate-name")+1] == "uv_lock":
    assert args[args.index("--crate-type")+1] == "lib"
    assert sum(v.startswith("--emit=") and set(v[7:].split(",")) == {"dep-info", "metadata"} for v in args) == 1
    assert not any(x.startswith("-Zself-profile") for x in args)
    added = ["-Zself-profile=" + os.environ["OHM_PROFILE_DIR"], "-Zself-profile-events=" + os.environ["OHM_PROFILE_EVENTS"]]
    receipt = Path(os.environ["OHM_PROFILE_ARGV"]) / (str(os.getpid()) + ".json")
    with receipt.open("x") as f: json.dump({"pid":os.getpid(),"original":[rustc,*args],"executed":[rustc,*args,*added]},f)
    args.extend(added)
os.execv(rustc, [rustc,*args])
