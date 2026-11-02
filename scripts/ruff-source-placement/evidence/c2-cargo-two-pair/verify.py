"""Read the four independent hosted archive projections and the authentic frozen final decision offline."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
HARDWARE = ("old", "new", "unchanged")


def need(condition, message):
    if not condition:
        raise ValueError(message)


def member(path, digest, size, name):
    raw = path.read_bytes()
    need(
        len(raw) == size and hashlib.sha256(raw).hexdigest() == digest,
        "transport differs from the original Actions archive",
    )
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        need(
            z.namelist() == [name] and z.getinfo(name).file_size < 4 << 20 and z.testzip() is None,
            "bad compact original archive",
        )
        return json.loads(z.read(name))


def validate(manifest, reports, final):
    need(
        len(reports) == 4
        and len({x["boot"] for x in reports}) == 4
        and len({x["raw"]["id"] for x in reports}) == 4,
        "four independent source histories were required",
    )
    need(
        final["source"] == reports[0]["source"]
        and final["reader_run"] == manifest["closed_decision"]["run"]
        and final["reader_qa"] == manifest["closed_decision"]["qa"]
        and final["original_decision_refusal"] == manifest["failed_final_receiver"]["job"],
        "different external decision source",
    )
    out = {}
    pm_total = 0
    for binding, v in zip(manifest["projections"], reports, strict=True):
        stage, slot = v["stage"], v["slot"]
        arm_order = ["P", "C"] if slot == 1 else ["C", "P"]
        need(
            (stage, slot, v["reader_run"], v["raw"], v["terminal_sha256"], v["boot"])
            == (
                binding["role"],
                binding["slot"],
                binding["reader_run"],
                binding["original"],
                binding["terminal"],
                binding["boot"],
            )
            and v["order"] == arm_order,
            "different scheduled original",
        )
        need(
            {r: x["revision"] for r, x in v["source"].items()} == manifest["source"]
            and {r: x["driver"]["sha"] for r, x in v["roles"].items()} == manifest["drivers"],
            "different physical compilers or product revisions",
        )
        for suite in v["suites"]:
            for role in arm_order:
                phases = v["native"][suite][role]
                obs = v["verdicts"][suite][role]
                pms = v["pmu"][suite][role]
                need(
                    set(pms) == (set(HARDWARE) if stage == "score" else set()),
                    "unregistered or missing hardware",
                )
                need(
                    obs["invalid"]["error"] == "E0308"
                    and obs["old"]["elf"] != obs["new"]["elf"]
                    and all(
                        obs[ph]["elf"] == obs["clean-new"]["elf"]
                        and obs[ph]["verdict"] == obs["clean-new"]["verdict"]
                        for ph in (
                            "new",
                            "unchanged",
                            "repair",
                            *(("restored-new",) if suite == "e2e" else ()),
                        )
                    ),
                    "mismatched independent clean verdict/ELF",
                )
                other = "C" if role == "P" else "P"
                need(
                    obs["old"]["elf"] == v["verdicts"][suite][other]["old"]["elf"]
                    and obs["new"]["elf"] == v["verdicts"][suite][other]["new"]["elf"],
                    "different observed objects across compilers",
                )
                for ph in HARDWARE:
                    row = phases[ph]
                    pd = row["disk"]
                    rss = row["rss"]["kernel_maxrss_kib"]
                    need(
                        pd["allocated"]["allocated"] > 0
                        and rss > 0
                        and (
                            role != "P" or pd["optional_entries"] == pd["optional_tail_bytes"] == 0
                        ),
                        "invalid target/shared union or peak RSS",
                    )
                    if suite == "e2e" and ph in ("new", "unchanged"):
                        need(
                            row["compilers"] == (2 if ph == "new" else 1) and row["wild"] == 1,
                            "incorrect signed native link history",
                        )
                    if suite == "option" and ph in ("new", "unchanged"):
                        need(
                            row["compilers"] == (1 if ph == "new" else 0) and row["wild"] == 0,
                            "incorrect option root history",
                        )
                    if stage == "score":
                        pm = pms[ph]
                        need(
                            pm["status"] == 0
                            and pm["phase"] == ph
                            and pm["enabled"] == pm["running"] > 0
                            and pm["instructions"] > 0,
                            "missing, multiplexed or failing hardware count",
                        )
                        decision = final["pairs"][str(slot)]["visits"][suite][ph]
                        need(
                            decision["parent" if role == "P" else "candidate"] == pm["instructions"]
                            and decision["rss"][role] == row["rss"]
                            and decision["disk"][role] == pd,
                            "independent decision differs from original measured data",
                        )
                        key = f"{slot}-{suite}-{ph}"
                        out.setdefault(key, {})[role] = [
                            pm["instructions"],
                            pd["allocated"]["allocated"],
                            rss,
                        ]
                        pm_total += 1
            if stage == "admit" and suite == "option":
                d = v["durable"]
                n = d["round-trip"]["new"]
                need(
                    n["CGUs"] == 125
                    and n["hits"] == 13
                    and n["normal_writes"] == 8
                    and len(set(n["selected"])) == 13
                    and d["object-corrupt"]["new"]["hits"] == 12
                    and d["object-corrupt"]["new"]["normal_writes"] == 9
                    and d["optional-corrupt"]["new"]["hits"] == 0
                    and d["optional-corrupt"]["new"]["normal_writes"] == 21
                    and set(v["check_handoff"]) == {"P", "C"},
                    "incorrect native, previous-object or degraded-index controls",
                )
        if stage == "score":
            d = final["pairs"][str(slot)]
            need(
                d["boot"] == v["boot"]
                and d["raw"] == v["raw"]
                and d["independent"] == binding["reader"],
                "wrong counter artifact",
            )
    need(
        pm_total == 24
        and final["two_pair_primary_screen"]
        == all(out[f"{i}-option-new"]["P"][0] > 2 * out[f"{i}-option-new"]["C"][0] for i in (1, 2))
        and final["two_pair_primary_screen"] is False,
        "incorrect original prospective 2x decision",
    )
    return out


def main(selftest):
    m = json.loads((HERE / "receipts.json").read_bytes())
    reports = [
        member(
            HERE / x["file"],
            x["reader"]["digest"].removeprefix("sha256:"),
            x["reader"]["size_in_bytes"],
            "reopened.json",
        )
        for x in m["projections"]
    ]
    d = m["closed_decision"]
    end = member(HERE / "decision.zip", d["sha256"], d["size"], "placement-pilot.json")
    rows = validate(m, reports, end)
    if selftest:
        for case in range(5):
            xs = deepcopy(reports)
            decision = deepcopy(end)
            if case == 0:
                xs[3]["pmu"]["option"]["C"]["new"]["running"] -= 1
            elif case == 1:
                xs[3]["boot"] = xs[2]["boot"]
            elif case == 2:
                xs[0]["durable"]["optional-corrupt"]["new"]["hits"] = 1
            elif case == 3:
                xs[2]["verdicts"]["option"]["P"]["clean-new"]["elf"] = "incorrect"
            else:
                decision["two_pair_primary_screen"] = True
            try:
                validate(m, xs, decision)
            except ValueError:
                continue
            raise RuntimeError(("accepted false evidence", case))
    print(
        "24 hardware counts and their 24 actual allocated/RSS pairs, 4 independent boots, cold/changed/unchanged and native acceptance intact."
    )
    print("Original 2x screen:", end["two_pair_primary_screen"])
    for name, vals in rows.items():
        n, c = vals["P"], vals["C"]
        print(name, "P", *n, "C2", *c, "ratio", f"{n[0]/c[0]:.6f}")


if __name__ == "__main__":
    main("--self-test" in sys.argv[1:])
