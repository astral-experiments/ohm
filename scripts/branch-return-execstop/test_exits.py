"""Exercise refusal attribution independently of the strict positive family reader."""
from pathlib import Path
import json
import tempfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from exits import inspect
from history import need


def suite(originals):
    native = {}
    for p in sorted(originals.glob("*.tsv")):
        evidence = inspect(p, p.with_name(p.name + ".exits"))
        native[p.stem] = {k: evidence[k] for k in ("ledger_sha256", "sidecar_sha256", "terminal")}
    need({k for k, v in native.items() if v["terminal"][0] == "OK"} ==
         {"family", "thread", "duplicate", "abort", "signals", "long"} and len(native) == 8, "actual native controls")
    # Linux can reuse a numeric PID after wait. The generation of the leader at birth,
    # not a numeric TGID, must delimit evidence for a subsequent sibling's refusal.
    prefix = ("R 1 8\nN 1 8 1 2 20\nB 2 20 20\nX 2 20 0\nT 2 20 0\n"
              "N 1 8 1 3 20\nB 3 20 20\nN 3 20 3 4 21\nB 4 21 20\n"
              "X 3 20 10752\nT 3 20 10752\n").replace(" ", "\t") + "REFUSE\tunclosed final task\t3\n"
    entries = "EXIT_GROUP 2 20 20 0\nEXIT_GROUP 3 20 20 42\nESRCH 4 21 24 0\n".replace(" ", "\t")
    last = "REFUSE_FINAL 21 4 10752 20 1 1 0 0 0 0\n".replace(" ", "\t")
    corrupt = {"drop-final": entries, "unknown-generation": entries + last.replace("\t21\t4\t", "\t21\t5\t"),
               "foreign-group": entries.replace("3\t20\t20\t42", "3\t20\t8\t42") + last,
               "wrong-pid": entries + last.replace("\t21\t4\t", "\t20\t4\t"),
               "born-mismatch": entries + last.replace("\t20\t1\t1", "\t20\t1\t0"),
               "admissible-state": entries + last.replace("\t20\t1\t1\t0", "\t20\t1\t1\t1"),
               "stopped-not-terminal": entries + last.replace("10752", "4991"), "extra-event": entries + last + entries}
    with tempfile.TemporaryDirectory() as tmp:
        p, s = Path(tmp) / "core", Path(tmp) / "exits"
        p.write_text(prefix)
        s.write_text(entries + last)
        out = inspect(p, s)
        need([e["lifetime"] for e in out["same_group_exit_syscalls"]] == [3] and
             out["same_group_exit_syscalls"][0]["kernel"]["T"] == 10752 and out["refused_task"]["tid"] == 21,
             "cross-generation attribution")
        for name, modified in corrupt.items():
            s.write_text(modified)
            try:
                inspect(p, s)
            except ValueError:
                pass
            else:
                raise AssertionError(("accepted mutated sidecar", name))
    return {"native": native, "forgeries_rejected": len(corrupt), "pid_reuse_negative": True}


if __name__ == "__main__":
    print(json.dumps(suite(Path(sys.argv[1])), sort_keys=True))
