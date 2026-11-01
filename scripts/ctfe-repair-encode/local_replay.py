"""Reopen raw output from both portable two-crate candidate controls, including negative event mutations."""

import copy
import gzip
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evidence as ev


def load(p):
    return json.loads(p.read_bytes())


def rejected(callback):
    try:
        callback()
    except (ValueError, KeyError):
        return 1
    raise ValueError("accepted mutated original")


def read(base):
    summaries = {}
    normalized = {}
    total = 0
    commands = {}
    tools = {}
    elfs = []
    for label in ("pass", "blocked"):
        d = base / label
        clinical = load(d / "result.json")
        auth = load(d / "source.json")
        live = load(d / "sdk-files.json")
        ev.need(
            all(auth[k] == [r[0], r[3], r[4]] for k, r in live.items())
            and len(live) == 81
            and clinical["source"] == "df2c077a113a709ab379c8ec34e62c94c7513325"
            and clinical["identical_reopened"],
            "foreign local kit",
        )
        cli = ev.sha(d / "repair.elf")
        ev.need(cli == clinical["cli"] == clinical["empty"], "missing physical repair output")
        elfs.append(d / "repair.elf")
        for phase, n in [
            ("Y-B", 17),
            ("X-A", 29),
            ("X-B", 17),
            ("invalid", None),
            ("repair", 37),
            ("settled", 37),
            ("empty", 37),
        ]:
            cmd = load(d / (phase + ".command.json"))
            ev.need(
                cmd["argv"]
                == [
                    "cargo",
                    "+ohm",
                    "build",
                    "--locked",
                    "--offline",
                    "-j2",
                    "-p",
                    "repair_app",
                    "--message-format=json",
                ]
                and cmd["status"] == (101 if n is None else 0),
                "wrong ordinary Cargo command",
            )
            raw = [
                json.loads(line)
                for line in gzip.decompress((d / (phase + ".stdout.gz")).read_bytes()).splitlines()
            ]
            ev.need(
                raw[-1] == {"reason": "build-finished", "success": n is not None}, "incomplete Cargo verdict"
            )
            if n is None:
                errors = [x for x in raw if (x.get("message", {}).get("code") or {}).get("code") == "E0308"]
                ev.need(
                    len(errors) == 1
                    and any(
                        s["is_primary"] and "const WRONG" in str(s["text"])
                        for s in errors[0]["message"]["spans"]
                    ),
                    "different invalid control",
                )
            else:
                result = load(d / (phase + ".native.json"))
                ev.need(
                    result["stdout"] == str(n) + "\n"
                    and result["status"] == 0
                    and (phase not in ("repair", "settled", "empty") or result["elf"] == cli),
                    "stale actual native product",
                )
        old, new = [load(d / (k + ".json")) for k in ("before", "after")]
        owner = clinical["owner"]
        paths = [old["owners"][owner]]
        c = d / "control"
        ev.need(
            (c / "config").read_text() == ev.config("B" if label == "blocked" else "P", paths),
            "changed fixture config",
        )
        bridge = load(d / "images.json")
        sdk = Path(next(im["identity"][3] for im in bridge.values() if im["role"] == "rustc")).parent.parent
        images, events = ev.physical(c, sdk, paths, inventory=live)
        ev.mapped_observer(c, images, sdk.parents[3] / "gate.so")
        ev.need(images == bridge and events == load(d / "events.json"), "raw open/image projections differ")
        apps = [k for k in events if k.startswith("repair_app-")]
        ev.need(len(apps) == 1, "no unique negative-control owner")

        def route(e):
            return ev.routes(old, new, images, e, [owner], label == "blocked", extra_passthrough=apps)

        inspected = route(events)
        record = load(d / "objects.json")[owner]
        ev.need(
            inspected[owner] == {q: record[q] for q in ("final", "donor", "packed_pair")},
            "different published pair",
        )
        ev.need(
            [r["aliases"] for r in record["tables"]] == [3, 3]
            and all(("packed" in t) == (label == "pass") for t in record["tables"]),
            "incorrect alias/representation",
        )
        normalized[label] = {n: [r["packed"], r["bytes"], r["digest"]] for n, r in record["objects"].items()}
        ev.need(
            sorted(v[0] for v in normalized[label].values()) == [False, True],
            "missing real independent object packer",
        )
        broken = copy.deepcopy(events)
        broken[owner] = [e for e in broken[owner] if e["tag"] != "g"]
        total += rejected(lambda: route(broken))
        wrong = copy.deepcopy(events)
        next(e for e in wrong[owner] if e["tag"] == "q")["ino"] += 1
        total += rejected(lambda: route(wrong))
        rogue = copy.deepcopy(events)
        next(e for e in rogue[apps[0]] if e["tag"] == "G").update(error=13, fd=-1)
        total += rejected(lambda: route(rogue))
        extra = copy.deepcopy(events)
        extra[owner].append(next(e for e in extra[owner] if e["tag"] == "G"))
        total += rejected(lambda: route(extra))
        misplaced = copy.deepcopy(events)
        next(e for e in misplaced[owner] if e["tag"] == "G")["path"] = str(
            Path(paths[0]) / "other-working" / ev.FILES[0]
        )
        total += rejected(lambda: route(misplaced))
        fallback = copy.deepcopy(events)
        event = next(x for x in fallback[owner] if x["tag"] == "U")
        place = Path(event["path"])
        event["path"] = str(place.parent.with_name("s-old-working") / place.name)
        total += rejected(lambda: route(fallback))
        if label == "blocked":
            fake = copy.deepcopy(events)
            sham = next(v for v in fake[owner] if v["tag"] == "N")
            sham["tag"] = "Q"
            total += rejected(lambda: route(fake))
        (wild,) = [x for x in images.values() if x["role"] == "wild"]
        link = load(d / "link.json")
        ev.need(
            wild["argv"][wild["argv"].index("-o") + 1] == link["path"]
            and link["file"] == link["cargo"]
            and link["file"]["sha256"] == cli,
            "wrong physical stock-Wild output",
        )
        commands[label] = ev.compiler_commands(images)
        tools[label] = [clinical["gate"], clinical["driver"], clinical["wild"]]
        summaries[label] = dict(
            table_bytes=[r["body_bytes"] for r in record["tables"]],
            table_sha256=[r["body_sha256"] for r in record["tables"]],
            events=[[v["tag"], v["error"], v["index"]] for group in events.values() for v in group],
        )
    ev.need(
        commands["pass"] == commands["blocked"]
        and tools["pass"] == tools["blocked"]
        and normalized["pass"] == normalized["blocked"],
        "unequal interventions/native outputs",
    )
    subprocess.run(["cmp", "--", *elfs], check=True)
    return dict(
        arms=summaries,
        rejected_mutations=total,
        cli=ev.sha(elfs[0]),
        tools=tools["pass"],
        objects=normalized["pass"],
    )


if __name__ == "__main__":
    print(json.dumps(read(Path(sys.argv[1])), indent=2, sort_keys=True))
