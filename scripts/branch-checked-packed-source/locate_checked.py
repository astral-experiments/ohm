"""Reopen the isolated current workflow and its bounded native collision evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corrected
import locate_e
import read_collision

NAME = "Corrected packed reader, actual Cargo fallback and mixed native writers"
OLD_STEP = "Authenticate the original experimental E native corpus and driver"
NATIVE = "Build only the corrected compiler and run all checked-in and mixed native cases"
STEPS = (locate_e.STEPS[0], locate_e.STEPS[1], OLD_STEP, NATIVE, *locate_e.STEPS[3:])


def extra(z, m, end):
    def get(name):
        info = z.getinfo("E/collision/" + name)
        corrected.need(0 < info.file_size <= 12 << 20, "unbounded collision evidence")
        return z.read(info)

    roles = json.loads(get("roles.json"))
    r = roles["roles"]
    old = corrected.ORIGINAL_ARTIFACT
    corrected.need(
        roles["official"] == old
        and roles["old"]["commit"] == corrected.PREVIOUS
        and roles["old"]["driver"] == old["qualified"]["driver"]
        and roles["old"]["manifest"] == old["qualified"]["manifest"]
        and roles["F"]["commit"] == corrected.reg.SOURCE()["roles"]["F"]["commit"]
        and roles["F"]["manifest"] == corrected.K_ORIGIN["manifest"]
        and end["legacy_sdk"] == m["legacy_sdk"] == old["qualified"]["manifest"],
        "wrong original native qualification",
    )

    def ident(source, driver, doc):
        return {"source": source, "driver": driver, "rustdoc": doc}

    read_collision.group_correspondence(
        r,
        ident(
            corrected.PREVIOUS,
            old["qualified"]["driver"][0],
            "08b465fd46ff24e301bb66510a6a223f8dde94cb3271865994cc352c7604da3a",
        ),
        ident(corrected.SHA, m["files"][m["driver"]][0], m["files"]["bin/rustdoc"][0]),
        ident(
            roles["F"]["commit"],
            "fe62e729ee976d9b808b4f94f0a9751c7f6d7b2201aecf3636e9eff8acb88273",
            "636680b705f7d69bb0124bb04738efe01ccbf1d2a5c9e09c486682fe460415e9",
        ),
    )
    raw = get("complete.json")
    corrected.need(
        hashlib.sha256(raw).hexdigest() == m["collision"] == end["collision"]
        and json.loads(raw) == read_collision.verify(get, r),
        "unverified final native collision result",
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=int)
    p.add_argument("head")
    p.add_argument("--gh", default="/home/dev-user/.local/bin/gh-auto")
    p.add_argument("--media", type=Path)
    a = p.parse_args()
    corrected.load()
    corrected.need(
        corrected.reg.rev(HERE.parents[1], "HEAD") == a.head, "use exact qualification checkout"
    )

    def api(suffix):
        return json.loads(
            subprocess.check_output(
                [a.gh, "api", f"repos/{corrected.reg.REPO}/actions/runs/{a.run}" + suffix]
            )
        )

    c = locate_e.check(
        a.run,
        a.head,
        api(""),
        api("/attempts/1/jobs")["jobs"],
        api("/artifacts")["artifacts"],
        ref=corrected.REF,
        job_name=NAME,
        steps=STEPS,
    )
    if a.media:
        c["qualified"] = locate_e.media(c, a.media, authority=corrected, extra_read=extra)
    print(json.dumps(c, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
