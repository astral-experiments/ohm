"""Read physical A/warm-B/cold-B products before enrolling the genuine first edits."""

import gzip
from pathlib import Path
import core as c, wire, scoped

m = c.m
ENROLL = m.read(c.HERE / "imports.json")


def root_inputs(parse, vault, products):
    def raw(n):
        size, sha = products["raw"][n]
        blob = gzip.decompress((vault / (sha + ".gz")).read_bytes())
        c.guard((len(blob), m.digest(blob)) == (size, sha), "bad measured product")
        return blob

    return wire.selected(parse, raw("uv_metadata"), raw("uv_client"), ENROLL)


def role(parse, vault, q):
    keys = {}
    for phase in ("ordinary-A", "warm-B", "cold-B"):
        keys[phase] = root_inputs(parse, vault, m.read(q / phase / "products.json"))
        m.save(q / phase / "projected-foreign-inputs.json", keys[phase])
    effect = wire.effects(*(keys[n] for n in ("ordinary-A", "warm-B", "cold-B")))
    m.save(q / "foreign-effect.json", effect)
    return effect


def holds(panel, hold):
    vals = {
        r: m.read(panel / f"hold-{hold}-{r}" / "foreign-effect.json") for r in c.ROLES
    }
    wire.planned(*(vals[r] for r in c.ROLES))
    rosters = {
        r: m.read(panel / f"hold-{hold}-{r}" / "typed-B/roster.json")["artifact_crates"]
        for r in c.ROLES
    }
    c.guard(
        all(
            v == dict.fromkeys(c.P["edited_workspace_roster"], 1)
            for v in rosters.values()
        ),
        (
            "actual edited unit set changed; adjudicate retained raw before scoring",
            rosters,
        ),
    )
    return vals


def independently_read(parse, out, q):
    keys = []
    for n in ("ordinary-A", "warm-B", "cold-B"):
        path = q / n
        x = root_inputs(parse, out / "rmeta-by-content", m.read(path / "products.json"))
        c.guard(
            x == m.read(path / "projected-foreign-inputs.json"),
            "projection receipt differs from actual rmeta",
        )
        keys.append(x)
    c.guard(
        wire.effects(*keys) == m.read(q / "foreign-effect.json"),
        "projected declaration effects differ",
    )
    p = q / "scoped-B"
    request = m.read(q / "scoped-request.json")
    c.guard(
        request
        == {
            "command": c.CHECK,
            "cwd": str(m.SRC),
            "environment": m.ENV,
            "compiler_path": str(m.RUSTC),
            "selectors": {
                a[a.index("--crate-name") + 1]: a
                for a in m.read(q / "typed-B/roster.json")["commands"]
            },
        },
        "wrong retained native selector set",
    )
    counts = scoped.read(p, request)
    c.guard(
        counts == m.read(p / "counts.json")
        and m.read(q / "scoped-equivalence.json")["passed"] is True,
        "false scoped count, wrong outputs",
    )
    return counts


def reduce(parse, out, panel):
    holds_data = []
    for h in (0, 1):
        vals = holds(panel, h)
        counts = {
            r: independently_read(parse, out, panel / f"hold-{h}-{r}") for r in c.ROLES
        }
        holds_data.append(
            {
                "hold": h,
                "effects": vals,
                "user_instructions": counts,
                "sum_of_nine_disjoint_compilers": {
                    r: sum(x.values()) for r, x in counts.items()
                },
            }
        )
    return {
        "scope": "true kernel-selected nine rustc images and their threads, user instructions only; independent untimed restores",
        "earlier_access_observer": ENROLL["A"]["stable_crate_id"],
        "joined_by": "complete unique native DefKey paths, with real provider and terminal metadata per SDK",
        "per_hold": holds_data,
    }
