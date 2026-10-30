"""Summarize the verified 756 native commands without retaining personal paths or host metadata."""
from hashlib import sha256
import argparse
import json
from pathlib import Path


def read(path, expected):
    raw = path.read_bytes()
    assert sha256(raw).hexdigest() == expected
    return json.loads(raw)


def project(base, kinds, stock):
    assert base["safety"] and stock["matched_commands"] == 108
    assert set(base["subjects"]) == set(kinds["modes"]) == {"293", "signed"}
    blocks = {}
    for mode, group in base["subjects"].items():
        fixed = mode == "293"
        seen = set()
        rows = {}
        corrections = kinds["modes"][mode]
        assert corrections["artifact"] == group["artifact"] and group["physical_commands"] == 324
        for role in "ANM":
            for watch in ("files", "directories", "undeclared"):
                history = []
                for place in ("direct","library"):
                    key = f"{role}-{watch}-{place}"
                    observed = group["all_physical"][key]
                    stamps = group["actual_same_inode_stamps"][key]
                    for step in ("value","malformed","repair"):
                        a,b = (stamps[step][v] for v in ("before","after"))
                        assert all(a[k] == b[k] for k in ("dev","ino","size","mtime_ns","nlink","mode"))
                        assert a["sha256"] != b["sha256"] and a["ctime_ns"] <= b["ctime_ns"]
                    compared = []
                    baseline = stock["groups"][f"S-{watch}-{place}"]
                    for step, x in observed.items():
                        seen.add((key,step))
                        if step == "cold-lower" or step.startswith("empty-"):
                            continue
                        empty = "empty-" + ("restored-edit" if step == "restored-repeat" else step)
                        ref = observed[empty]
                        diagnostic = lambda r: [r["cargo_exit"],r["answer"]]
                        identical = diagnostic(ref) == diagnostic(x) and ref["elf"] == x["elf"]
                        if fixed:
                            assert identical and x["actual_provider_ld"] > 0 and x["selected_provider"] == ref["selected_provider"]
                        identity = baseline["stock_actual"][step]
                        same_as_stock = diagnostic(x) == diagnostic(identity)
                        assert same_as_stock == (step not in baseline["ordinary_runtime_or_verdict_differing_from_stock"][mode+"/"+role])
                        if mode == "signed" and role == "M":
                            assert same_as_stock
                        corrected = corrections["subjects"][key][step]["kernel_events"]
                        only = sum(r[2] == "link_only" for r in corrected)
                        full = sum(r[2] == "full_rustc" for r in corrected)
                        compared.append([step,diagnostic(x),diagnostic(ref),identical,same_as_stock,
                                         x["actual_provider_ld"],full,only])
                    history.append(sorted(compared))
                # Both native placements must be classified separately, even when their outcomes coincide.
                rows[f"{role}-{watch}"] = dict(zip(("direct","library"),history))
        assert len(seen) == 324
        blocks[mode] = {"cargo":group["cargo_source"],"cargo_sha256":group["cargo"],
                        "physical_rustcs":corrections["physical_rustcs"],"raw":[group["id"],group["bytes"],group["artifact"]],
                        "all_native_rows":rows}
    return {"matched_Ohm_run":base["run"],"stock_run":stock["run"],"real_Cargo_commands":756,
            "row_columns":["phase","ordinary_Cargo_exit_and_QEMU_stdout","empty_Cargo_exit_and_QEMU_stdout",
                           "ordinary_matches_own_empty_complete_elf_and_verdict","same_runtime_and_verdict_as_upstream_1_99",
                           "GNU_ld_processes_opening_or_searching_provider","full_rustcs","link_only_rustcs"],
            "stock":{"cargo":stock["stock_cargo_source"],"rustc":stock["stock_rustc_source"],
                     "raw":stock["raw_artifact"],"ordinary_differs_from_own_empty":{k:v["stock_differences_to_own_empty_full_elf_or_verdict"] for k,v in stock["groups"].items()}},
            "Ohm":blocks}


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("historical_root",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    base=read(a.historical_root/"run-41077287252/matched-provider-readback.json","23caaefad9facf7e5c400c15f77e6c18122dd81d0efae082d8989761dded7f94")
    kinds=read(a.historical_root/"run-41077287252/kernel-rustc-kinds-correction.json","e1cfd927cfb3d44991de9a651d3d5cf38ea78aa3ffd155aa20b864788df2ca38")
    stock=read(a.historical_root/"run-41079383532/independent-stock-physical-108.json","73cbc078c7c8b48674a1d13259bef2fdea0770f47586f022aebae5d9e993d373")
    wire=(json.dumps(project(base,kinds,stock),sort_keys=True,separators=(",",":"))+"\n").encode()
    if a.output.exists():
        assert wire==a.output.read_bytes()
    else:
        a.output.open("xb").write(wire)
    print(sha256(wire).hexdigest(),len(wire))
