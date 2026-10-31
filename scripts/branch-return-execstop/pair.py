"""Cross-check two independently reopened cold diagnostics without pooling their rosters."""
import json
from pathlib import Path
import sys

def pair(a, b):
    if (a["arm"], b["arm"]) != ("Foff", "Kon") or not a["boot"] or not b["boot"] or a["boot"] == b["boot"]:
        raise ValueError("expected one fresh, distinct boot per registered role")
    if any(a[key] != b[key] for key in ("head", "run")) or not all(row["performance_observations"] == 0 for row in (a, b)):
        raise ValueError("two different runs, revisions, or observed clocks")
    statuses = {}
    for row in (a, b):
        if row.get("status") == "original-kernel-refusal":
            if (row["exit_evidence"]["terminal"][0] != "REFUSE" or row["clean_typed"] != 375 or
                    [e["role"] for e in row["root_images"]] != ["proxy", "cargo"] or "physical_execs" in row):
                raise ValueError("refusal presented as a complete roster")
            statuses[row["arm"]] = "refused"
        else:
            if ([row[k] for k in ("typed", "physical_execs", "full_rustcs", "wild_outputs", "gnu_configure_links")] !=
                    [375, 4188, 379, 69, 62] or row["exit_sidecar"]["terminal"][0] != "OK"):
                raise ValueError("unqualified positive")
            statuses[row["arm"]] = "strictly-closed"
    return {"run": a["run"], "head": a["head"], "boots": [a["boot"], b["boot"]], "individual_results": statuses,
            "performance_observations": 0}

if __name__ == "__main__":
    print(json.dumps(pair(*(json.loads(Path(p).read_bytes()) for p in sys.argv[1:])), sort_keys=True))
