"""Reopen all original measurements and make only the registered hierarchical inferences."""

from fractions import Fraction
from math import comb
from pathlib import Path
from statistics import median
import json
import service as s
import collector as cc
import scoped

m = s.m


def stats(rows):
    ratios = [Fraction(b, a) for a, b in rows]
    above = sum(q < Fraction(4, 5) for q in ratios)
    below = sum(q > Fraction(4, 5) for q in ratios)
    n = above + below
    return dict(
        control_and_treatment=rows,
        paired_treatment_over_control=[float(v) for v in ratios],
        paired_median=float(median(ratios)),
        percent_reduction=100 * (1 - float(median(ratios))),
        half_medians=[float(median(ratios[:3])), float(median(ratios[3:]))],
        exact_median_interval_96_875_percent=[float(min(ratios)), float(max(ratios))],
        one_sided_sign_p=sum(comb(n, k) for k in range(above, n + 1)) / 2**n
        if n
        else 1,
        all_six_below_80_percent=above == n == 6,
    )


def verify(out, meter, check_binary=False):
    panel = out / "native-22958"
    guards = m.read(panel / "all-native-guards.json")
    cal = m.read(out / "calibration.json")
    ready = cal["ready"]
    order = ([s.ROLES[0], s.ROLES[1]], [s.ROLES[1], s.ROLES[0]]) * 3
    assert (
        guards["independent"] == 12
        and guards["orders"] == list(order)
        and guards["boot"] == ready["boot"]
        and guards["case"] == s.case["registered"]
    )
    allocation = m.read(out / "boot-attestation.json")
    hosted_workspace = Path(allocation["workspace"])
    assert hosted_workspace.is_absolute() and ".." not in hosted_workspace.parts
    assert (
        allocation["boot"] == ready["boot"]
        and cal["unmultiplexed_calibration_clocks"] == 28
    )
    scoped.cal_raw(out / "per-rustc-calibration")
    states = []
    history = set()
    for i, rr in enumerate(order):
        data = {}
        windows = []
        for role in rr:
            d = panel / (str(i + 1) + "-" + role)
            seed = m.read(d / "seed.json")["sha256"]
            assert seed not in history
            history.add(seed)
            roster = m.read(d / "kernel-B/forms.json")
            selectors = {k: v[0] for k, v in roster.items()}
            assert set(selectors) == {"uv_client", "uv_configuration"} and all(
                len(v) == 1 for v in roster.values()
            )
            ctr = m.read(d / "native-before-score.json")
            assert ctr["same_seed"] and ctr["canonical"]
            material = m.read(d / "kernel-B/products.json")
            assert m.read(d / "bare-B/products.json") == material
            assert len(material["workspace"]) == 39 and {
                k: len(v) for k, v in material["externs"].items()
            } == {"uv_client": 64, "uv_configuration": 30}
            baseline = cc.streams(d / "kernel-B")
            assert baseline == cc.streams(d / "bare-B")
            own = {}
            for mode in ("wall", "whole", "threads"):
                v = d / mode
                flag = m.read(v / "verified.json")
                assert (
                    flag["seed"] == seed
                    and flag["source"] == s.case["B"]
                    and flag["boot"] == ready["boot"]
                    and flag["same_seed"]
                )
                assert (
                    cc.streams(v) == baseline
                    and m.read(v / "products.json") == material
                    and flag["measured"] == m.filesha(v / "products.json")
                )
                q = m.read(v / "native/witness.json")
                assert q["codes"]["schema"] == [0, []] and q["codes"][
                    "client-negative"
                ] == [1, ["E0308"]]
                if mode == "threads":
                    req = m.read(d / "scoped-request.json")
                    assert (
                        req["command"] == s.CHECK
                        and req["selectors"] == selectors
                        and req["cwd"] == str(m.SRC)
                        and req["environment"] == m.ENV
                    )
                    nums = scoped.read(v, req)
                    assert nums == m.read(v / "counts.json") and set(nums) == set(
                        selectors
                    )
                    own.update(nums)
                    own["sum_two"] = sum(nums.values())
                    continue
                q = m.read(v / "ordinary.json")
                assert (
                    q["boot"] == ready["boot"]
                    and q["cpus"] == ready["affinity"]
                    and q["argv"] == s.CHECK
                    and q["exit"] == 0
                    and q["env"] == m.ENV
                )
                assert q["end_ns"] - q["start_ns"] == q["ns"] > 0
                windows.append((q["start_ns"], q["end_ns"], role, mode))
                if mode == "whole":
                    assert (
                        q["invoked"]
                        == [
                            ready["plain"],
                            str(
                                hosted_workspace
                                / "trait-results"
                                / v.relative_to(out)
                                / "whole-clock.json"
                            ),
                            *s.CHECK,
                        ]
                        and q["mode"] == "pmu"
                    )
                    lc = meter.clock(v / "whole-clock.json", 0)
                    assert lc["running"] == lc["enabled"] > 0
                    own[mode] = lc["instructions"]
                else:
                    assert q["mode"] == "native" and q["invoked"] == s.CHECK
                    own[mode] = q["ns"]
            data[role] = own
        by = sorted(windows)
        assert all(a[1] <= b[0] for a, b in zip(by, by[1:])) and list(
            dict.fromkeys(x[2] for x in by)
        ) == list(rr)
        states.append(data)
    metrics = {}
    for key in ("uv_client", "sum_two", "uv_configuration", "whole", "wall"):
        metrics[key] = stats([[x[s.ROLES[0]][key], x[s.ROLES[1]][key]] for x in states])
    primary = metrics["uv_client"]["all_six_below_80_percent"]
    secondary = primary and metrics["sum_two"]["all_six_below_80_percent"]
    return dict(
        complete=True,
        actual_signed_Cargo=s.CHECK,
        sources={n: s.old.PAIR["arms"][n]["source"] for n in s.ROLES},
        boot=ready["boot"],
        metrics=metrics,
        primary_terminal_confirmed=primary,
        secondary_sum_of_two_confirmed=secondary,
        primary_then_secondary=True,
        original_exact_cold_gate_redeemed=False,
        independent_histories=len(history),
        registered=s.case["registered"],
        scope="independent hardware diagnostic; thread-group and inherited whole-package counters and ordinary wall are separate",
    )


def close(out):
    w, tmp, _ = s.host()
    _, meter = m.pmu(w, tmp)
    z = verify(out, meter)
    m.save(out / "native-22958/score.json", z)
    print(json.dumps(z, sort_keys=True))
