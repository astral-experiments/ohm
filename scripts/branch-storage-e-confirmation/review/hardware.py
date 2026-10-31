"""Cross-check physical calibration entry, ABI and source files against the immutable observer checkout."""
import hashlib, json, subprocess
from pathlib import Path
from replay_metrics import need
import replay_controls

def verify(z,calibration,ready):
    binder=json.loads(z.read("observer.json")); ref=calibration["observer"]
    abi={"type":"PERF_TYPE_HARDWARE","config":"PERF_COUNT_HW_INSTRUCTIONS",
         "pid":"fork child blocked on its one-byte pipe before execvp cargo +ohm",
         "inherit":1,"disabled":1,"enable_on_exec":1,"exclude_kernel":1,"exclude_hv":1,
         "cpu":-1,"group_fd":-1,"read_format":["PERF_FORMAT_TOTAL_TIME_ENABLED","PERF_FORMAT_TOTAL_TIME_RUNNING"],"read_bytes":24}
    need(binder["abi"]==abi and sorted(binder["bins"])==sorted(("plain","loop","tree","nested","workers","calibrator"))
         and calibration["whole_control_cells"]==28 and calibration["nested"]==["plain","tree"],"wrong physical PMU scope")
    paths={"scripts/gnu-example-ceiling/"+p for p in ("watch.c","calibrate.c","observer.c","nested.c")}
    paths |= {"scripts/gnu-renderer-library-workers/"+p for p in ("workers.c","calibrator.c")}
    need(set(binder["sources"])==paths,"hardware observer source omissions")
    for path in paths:
        b=subprocess.check_output(["git","--no-optional-locks","-C",replay_controls.OBSERVER,"show",ref+":"+path])
        need(hashlib.sha256(b).hexdigest()==binder["sources"][path],"wrong observed hardware source")
    return {"abi":abi,"binary_sha256":binder["bins"]["plain"],"sources":binder["sources"]}
