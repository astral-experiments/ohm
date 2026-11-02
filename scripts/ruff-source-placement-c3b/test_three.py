"""Adversarial validation of real parked-file identities and the frozen aggregate against tiny test inputs."""

from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scope
from arm_names import INTERNAL
from three_kit import ThreeRuntime, rt
import three_decision
import exact_stats


def swapped_id_test():
    def link(source, dest):
        dest.parent.mkdir(exist_ok=True, parents=True)
        os.link(source, dest)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        obj = ThreeRuntime.__new__(ThreeRuntime)
        obj.sdk = root / "visible/rustup/toolchains/ohm"
        obj.sdk.parent.mkdir(parents=True)
        obj.active = None
        obj.parked = {}
        obj.origins = {}
        obj.refs = {}
        for k in ("P", "C", "C2"):
            family = root / ("older" if k == "C2" else "newer")
            alias = "P" if k == "P" else "C"
            obj.parked[k] = d = family / "parked" / alias
            obj.origins[k] = (family, alias)
            name = "bin/rustc"
            raw = (k + " native input").encode()
            import hashlib

            key = hashlib.sha256(raw).hexdigest()
            src = family / "capsule/objects" / key
            src.parent.mkdir(exist_ok=True, parents=True)
            src.write_bytes(raw)
            link(src, d / name)
            link(src, family / "doc-products" / alias / "rustdoc")
            link(src, d / "bin/rustdoc")
            obj.refs[k] = {"front": {"name": name, "sha": key, "id": rt.stat_id(d / name)}}
        # Each previous family has now created every link. Re-read the correct
        # enrollment ctime after fixture setup, in the same way as the real SDK.
        for k in obj.refs:
            obj.refs[k]["front"]["id"] = rt.stat_id(obj.parked[k] / "bin/rustc")
        for order in exact_stats.PERMS:
            for k in order:
                obj.select(INTERNAL[k])
        obj.select("C2")
        wrong = obj.sdk / "bin/rustc"
        real = wrong.read_bytes()
        wrong.unlink()
        wrong.write_bytes(real)
        refused = False
        try:
            obj.select("C2")
        except (RuntimeError, ValueError, AssertionError):
            refused = True
        assert refused, "an equal-byte different inode was accepted"


def aggregate_test():
    s = json.loads((scope.HERE / "three-arm-protocol.json").read_bytes())
    rr = exact_stats.ROLES
    rows = []
    for i, b in enumerate(s["blocks"], 1):
        fake = {
            "slot": i,
            "boot": f"simulated-{i}",
            "forbidden_boots": ["previous"],
            "study": scope.base.sha(scope.HERE / "three-arm-protocol.json"),
            "assignment": b,
            "source": s["source"],
            "factory": {"C2": 1, "C3b": 2},
            "kit_products": {"C2": "a", "C3b": "b"},
            "prior_native": {"simulated": True},
            "qa": "control",
            "run": 0,
            "kits": {r: {"driver": {"sha": "fake-" + r}} for r in rr},
            "reader": {"id": 100 + i},
            "raw": {"id": 200 + i},
            "counts": {},
            "controls": {},
            "native_rosters": {},
            "terminal_sha256": "control-" + str(i),
        }
        for suite in ("option", "e2e"):
            fake["counts"][suite] = {}
            fake["controls"][suite] = {}
            fake["native_rosters"][suite] = {}
            for j, r in enumerate(rr):
                fake["counts"][suite][r] = {}
                fake["controls"][suite][r] = {}
                fake["native_rosters"][suite][r] = {}
                for ph in ("old", "new", "unchanged"):
                    n = (
                        1000 + i - 100 * j
                        if suite == "option" and ph == "new"
                        else 2000 + i + 100 * j
                    )
                    fake["counts"][suite][r][ph] = {
                        "status": 0,
                        "phase": ph,
                        "enabled": 100,
                        "running": 100,
                        "instructions": n,
                        "raw_sha256": "0" * 64,
                    }
                    fake["controls"][suite][r][ph] = {
                        "rss": {"kernel_maxrss_kib": 1},
                        "storage": {
                            "allocated": {"allocated": 500},
                            "optional_tail_bytes": 0,
                            "optional_entries": 0,
                            "rows_sha256": "0" * 64,
                        },
                    }
                    fake["native_rosters"][suite][r][ph] = {}
        rows.append(fake)
    ans = three_decision.decide(rows, s)
    assert (
        ans["primary_over_10_percent_each_of_6"] == {"C2": False, "C3b": True}
        and not ans["old_C2_two_pair_2x_screen"]
    )
    for i in range(5):
        v = deepcopy(rows)
        if i == 0:
            v[2]["boot"] = v[1]["boot"]
        elif i == 1:
            v[4]["source"] = s["source"] | {"C2": "not the existing compiler"}
        elif i == 2:
            v[3]["counts"]["option"]["C2"]["new"]["running"] = 99
        elif i == 3:
            v[5]["boot"] = "previous"
        else:
            v[1]["assignment"] = v[0]["assignment"]
        rejected = False
        try:
            three_decision.decide(v, s)
        except (AssertionError, ValueError, RuntimeError):
            rejected = True
        assert rejected, ("aggregate accepted changed receipt", i)
    print(
        "Actual inode and raw-aggregate corruption tests passed, all permutations and strict threshold tested."
    )


if __name__ == "__main__":
    swapped_id_test()
    aggregate_test()
