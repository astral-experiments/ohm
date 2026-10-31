"""Run the new native reader on authentic F and E visits separately. These files cannot constitute a new cohort."""

from pathlib import Path
import argparse
import json
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent)]
import media
import physical as p
import confirm_binding as r


def run(file, which, roles, inputs, parsers):
    spec = json.loads((r.INPUTS / "pilots.json").read_bytes())["runs"][which]
    row = spec["hosts"]["01"]
    media.verify(file, row)
    out = {}
    with zipfile.ZipFile(file) as z:
        en = p.top(z, "enrollment.json")
        p.need(
            (en["boot"], en["run"], en["head"]) == (row["boot"], spec["run"], spec["head"]),
            "wrong original worker",
        )
        p.need(
            p.sha(z.read("complete.json")) == row["complete_sha256"]
            and p.top(z, "ruff-inputs.json") == inputs,
            "wrong native terminal/source",
        )
        calibration = p.replay_controls.calibration(z, en["boot"])
        p.hardware.verify(z, calibration, p.top(z, "meter-ready.json"))
        for arm in roles:
            role = arm[0]
            info = {role: p.read(z, "sdk", role + ".json")}
            digest = en["E"]["qualified"]["manifest"] if role == "E" else en["F"]["manifest"]
            env = p.active(z, "clean/" + arm, arm, info, digest)
            refs = {}
            imgs = {}
            for state, phase in [("A", "cold-A"), ("B", "cold-B"), ("A-edit", "same-empty-edit")]:
                v, _ = p.operation(
                    z, f"clean/{arm}/{state}", arm, "clean", phase, state, env, parsers
                )
                refs[state] = v
                for name in ("cli", "reader"):
                    p.physical(z, name, v["native"][name], state, imgs)
            native = p.replay_controls.native_provider(z, arm)
            visits = {}
            windows = []
            for lane in ("ordinary", "measured"):
                for study, phases in (("main", p.metrics.PHASES), ("same", p.metrics.SAME)):
                    last = None
                    for ph in phases:
                        prefix = f"{lane}/{arm}/{study}/{ph}"
                        state = p.STATE[ph]
                        v, ledger = p.operation(
                            z, prefix, arm, lane, ph, state, env, parsers, refs[state]
                        )
                        record = v["record"]
                        if lane == "ordinary":
                            visits[ph] = record
                            if ph in (
                                "cold-A",
                                "first-B",
                                "same-cold-A",
                                "same-edit",
                                "same-repeat",
                                "same-first-B",
                            ):
                                last, _ = p.inspect_tables(z, prefix, arm, ph, ledger, last)
                        else:
                            c = p.read(z, prefix, "clock.json")
                            n = p.measured_count(c, 101 if ph == "invalid" else 0)
                            p.need(
                                n == record["instructions"]
                                and all(
                                    record[k] == v
                                    for k, v in visits[ph].items()
                                    if k not in ("instructions", "allocated")
                                ),
                                "rehearsal physical original",
                            )
                            windows.append((c["start"], c["stop"]))
            p.need(
                len(windows) == 11
                and all(x[0] < x[1] for x in windows)
                and all(x[1] < y[0] for x, y in zip(windows, windows[1:])),
                "historical role chronology",
            )
            out[arm] = {
                "archived_complete_ordinary": len(visits),
                "archived_complete_measured": len(windows),
                "confirmed_clean_programs": sorted({k[0] for k in imgs}),
                "boot": en["boot"],
                "official_zip": row["sha256"],
                "native_provider": native["status"],
            }
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--t-zip", type=Path, required=True)
    ap.add_argument("--e-zip", type=Path, required=True)
    ap.add_argument("--ruff", type=Path, required=True)
    ap.add_argument("--observer", type=Path, required=True)
    ap.add_argument("--calibration", type=Path, required=True)
    args = ap.parse_args()
    p.replay_controls.OBSERVER = args.observer
    p.replay_controls.PACKAGING = args.calibration
    src, parsers = p.corpus.source(args.ruff)
    primary = run(args.e_zip, "E", ("Eon",), src, parsers)
    parent = run(args.t_zip, "T", ("Foff", "Fon"), src, parsers)
    print(
        json.dumps(
            {
                "scope": "Historical physical reader rehearsal only, roles from two separate original pilots; zero future samples.",
                "E": primary,
                "T": parent,
            },
            sort_keys=True,
            indent=2,
        )
    )
