"""Reopen the registered bytes and conservative unit ceilings for all three independent edits."""
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
def require(value, error):
    if not value:
        raise ValueError(error)

def read_originals():
    result = {}
    for name, binding in json.loads((HERE / "binding.json").read_bytes()).items():
        path = HERE / name
        require(path.stat().st_size == binding["size_in_bytes"], (name, "wrong length"))
        with path.open("rb") as f:
            require("sha256:" + hashlib.file_digest(f, "sha256").hexdigest() == binding["digest"],
                    (name, "wrong authenticated archive"))
        with zipfile.ZipFile(path) as archive:
            require(archive.testzip() is None, (name, "ZIP checksum"))
            names = archive.namelist()
            require(len(names) == len(set(names)), (name, "duplicate member"))
            result[name] = {part: json.loads(archive.read(part)) for part in names}
    return result

def verify_project(original):
    require(set(original) == {"29697.json", "29604.json"}, "different Ruff edits")
    summary = {}
    for case, both in sorted(original.items()):
        require(set(both) == {"old", "edit"}, "different states")
        for state, v in both.items():
            key = case.removesuffix(".json") + "/" + state
            r = v["ranges"]
            exact = r["same_local_name_bytes_and_relocations_other_unit"]
            require(exact == r["same_local_name_bytes_and_relocations_in_retained_unit"],
                    (key, "different retained private copies"))
            require(0 <= exact["function_rows"] <= r["all_affected_local"]["function_rows"]
                    <= r["all_affected"]["function_rows"], (key, "inconsistent populations"))
            require(bool(v["affected"]) and len(v["affected"]) == len(set(v["affected"])),
                    (key, "different regenerated objects"))
            summary[key] = {"regenerated": len(v["affected"]), "all_objects": v["units"],
                            "local_with_external_owner": r["same_local_name_also_external_elsewhere"],
                            "repeated_private": exact}
    return summary

def verify_earlier(original):
    require(set(original) == {"result.json"}, "different typed LLVM evidence")
    data = original["result.json"]
    register = json.loads((HERE.parent / "heldout-28106.json").read_bytes())
    units = register["modules"]
    require(len(units) == 21 and data["native_units"] == 125
            and set(data["rows"]) == set(units), "original LLVM cohorts")
    group = {}
    for k in data["upper_unit_bounds_units_ir_machine"]:
        group[k] = {"definitions": 0, "units": 0, "ir": 0, "machine": 0}
    for name, (raw, optimized, ir, machine) in units.items():
        row = data["rows"][name]
        require((row["input"], row["optimized"], row["phase_guest_Ir"]) == (raw, optimized, [ir, machine]),
                (name, "different original prices or bitcode"))
        require(row["pre_internal_noinline"] <= row["pre_internal"] <= row["pre_definitions"]
                and set(row["counts"]) == set(group), (name, "inconsistent IR population"))
        for k, count in row["counts"].items():
            require(0 <= count <= row["pre_definitions"], (name, k, "invalid count"))
            g = group[k]
            g["definitions"] += count
            if count:
                g["units"] += 1
                g["ir"] += ir
                g["machine"] += machine
    for k, g in group.items():
        require([g["units"], g["ir"], g["machine"]] == data["upper_unit_bounds_units_ir_machine"][k],
                (k, "irreproducible class ceiling"))
        g["continuous_upper"] = g["ir"] + g["machine"] + 36 * g["units"]
    full = sum(ir + machine + 36 for raw, optimized, ir, machine in units.values())
    require(full == 120906271208 and register["continuous_instruction_overhead_per_unit"] == 36,
            "different registered cost domain")
    return {"continuous_all_21": full, "classes": group}

def main():
    originals = read_originals()
    require(set(originals) == {"ty-project.zip", "ruff-workspace.zip"}, "incomplete source boards")
    print(json.dumps({"ty_project": verify_project(originals["ty-project.zip"]),
                      "ruff_workspace": verify_earlier(originals["ruff-workspace.zip"])},
                     sort_keys=True, indent=2))

if __name__ == "__main__":
    main()
