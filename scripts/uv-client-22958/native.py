"""Qualify all twelve independent histories before enabling either hardware observation."""

from pathlib import Path
import os
import shutil
import subprocess
import service as s
import collector as cc
import fixed
import oracles as oo
import run as primary
import scoped

m = s.m


def sub(d):
    d.mkdir()
    return d


def qualify_role(role, ds, blobs):
    cc.source("A")
    fixed.target_reset()
    cold_a = ds / "cold-A"
    a = cc.kernel(cold_a, False)
    ro = {n: a[n][0] for n in ("uv_configuration", "uv_client")}
    cc.products(cold_a, ro, blobs)
    first = oo.probes(cold_a / "native", "A", role)
    archive = m.ROOT / "bank" / ("opening-A-" + role + ".tar.zst")
    a_stamp = fixed.make_seed(archive)
    cc.source("B")
    bare = ds / "initial-bare"
    cc.checked_run(s.CHECK, bare)
    wb = cc.products(bare, ro, blobs)
    fixed.restore(archive, a_stamp)
    kernel = ds / "initial-kernel"
    f = cc.kernel(kernel, True)
    actual = {n: q[0] for n, q in f.items()}
    warm = cc.products(kernel, actual, blobs)
    assert warm == wb and cc.streams(bare) == cc.streams(kernel)
    warm_w = oo.probes(kernel / "native", "B", role)
    fixed.target_reset()
    b = ds / "fresh-B"
    fb = cc.kernel(b, False)
    fresh = cc.products(b, {n: fb[n][0] for n in actual}, blobs)
    saved = m.ROOT / "bank" / ("opening-B-" + role + ".tar.zst")
    stamp = fixed.make_seed(saved)
    cold_w = oo.probes(b / "native", "B", role)
    assert oo.observables(warm_w) == oo.observables(cold_w)
    d = dict(
        places=str(ds),
        seed_A=a_stamp,
        cold_B=stamp,
        A_observable=oo.observables(first),
        B_observable=oo.observables(cold_w),
        full_first_B_argv=actual,
        cold_forms=m.filesha(b / "forms.json"),
    )
    m.save(ds / "admitted.json", d)
    return dict(
        fresh=fresh,
        archive=saved,
        seal=stamp,
        forms=b / "forms.json",
        witness=cold_w,
        first=warm,
        labels=actual,
    )


def run():
    w, tmp, boot = s.host()
    out = w / "trait-results"
    reported = m.read(out / "boot-attestation.json")
    assert reported["boot"] == boot
    ready = m.read(out / "calibration.json")["ready"]
    mask = set(ready["affinity"])
    assert mask <= os.sched_getaffinity(0)
    os.sched_setaffinity(0, mask)
    old, meter = m.pmu(w, tmp)
    binary = Path(ready["plain"])
    assert (
        old.cpu_receipt(out)["boot"] == boot
        and m.filesha(binary) == m.read(out / "calibration.json")["plain_sha256"]
    )
    scope = m.read(out / "per-rustc-calibration/source.json")
    assert (
        scope["host"] == scoped.machine()
        and len(scoped.cal_raw(out / "per-rustc-calibration")) == 3
    )
    assert (out / "intake/foreign-transition/passed.json").is_file() and (
        out / "intake/coroutine-transition/passed.json"
    ).is_file()
    load = m.read(out / "intake.json")
    sdks = load["installed"]
    assert list(sorted(sdks)) == list(sorted(s.ROLES))
    bank = m.ROOT / "bank"
    m.save(out / "uv-source.json", cc.initialize(w, bank))
    pool = tmp / "ctfe22-root-sdks"
    for role in s.ROLES:
        assert sdks[role]["source"] == s.old.PAIR["arms"][role]["source"]
        shutil.move(str(pool / role), bank / ("sdk-" + role))
    m.choose(s.ROLES[0], bank, sdks)
    cc.checked_run(
        [m.SDK / "bin/cargo", "fetch", "--locked"],
        out / "registry-fetch",
        env=dict(m.ENV, CARGO_NET_OFFLINE="false"),
    )
    m.save(out / "registry.json", cc.registry())
    blobs = sub(out / "blobs")
    audit = oo.toolkit(tmp / "22958-forensic-reader", blobs)
    panel = sub(out / "native-22958")
    openings = {}
    fixed_classes = {}
    stages = {}
    for role in s.ROLES:
        m.choose(role, bank, sdks)
        ds = sub(panel / ("opening-" + role))
        cc.source("A")
        ag = cc.graph()
        cc.source("B")
        bg = cc.graph()
        cc.source("A")
        assert ag["normalized"] == bg["normalized"]
        m.save(ds / "A-B-plans.json", {"A": ag, "B": bg})
        inp = qualify_role(role, ds, blobs)
        inp["headers"] = sub(ds / "native-headers")
        openings[role] = inp
        fixed_classes[role] = {}

    comparable = {
        role: {name: cc.comparable_argv(argv) for name, argv in inp["labels"].items()}
        for role, inp in openings.items()
    }
    assert comparable[s.ROLES[0]] == comparable[s.ROLES[1]]
    m.save(panel / "full-cross-arm-arguments.json", comparable)

    def accept(d, role, warm):
        inp = openings[role]
        result = oo.complete_cold_oracle(
            d, warm, inp["fresh"], audit, blobs, inp["headers"]
        )
        for owner in result["fixed_input_owners_required"]:
            (z,) = [
                v
                for p, v in result["changes"].items()
                if Path(p).name[3:].split("-")[0] == owner
            ]
            needed = set(z["physical_moved"])
            known = fixed_classes[role].setdefault(owner, set())
            if not needed <= known:
                data = fixed.certify(
                    d / ("fixed-input-" + owner), role, owner, inp, blobs, audit, needed
                )
                known.update(data["coverage"])
        return result

    for role in s.ROLES:
        m.choose(role, bank, sdks)
        cc.source("B")
        ds = panel / ("opening-" + role)
        accept(ds, role, openings[role]["first"])
    orders = ([s.ROLES[0], s.ROLES[1]], [s.ROLES[1], s.ROLES[0]]) * 3
    for i, order in enumerate(orders):
        for role in order:
            m.choose(role, bank, sdks)
            d = sub(panel / (str(i + 1) + "-" + role))
            cc.source("A")
            fixed.target_reset()
            a = d / "new-cold-A"
            forms = cc.kernel(a, False)
            actual = {n: forms[n][0] for n in ("uv_client", "uv_configuration")}
            cc.products(a, actual, blobs)
            oo.probes(a / "native", "A", role)
            seed = bank / ("A-" + str(i + 1) + "-" + role + ".tar.zst")
            stamp = fixed.make_seed(seed)
            m.save(d / "seed.json", stamp)
            cc.source("B")
            fixed.restore(seed, stamp)
            b = d / "bare-B"
            cc.checked_run(s.CHECK, b)
            before = cc.products(b, actual, blobs)
            fixed.restore(seed, stamp)
            k = d / "kernel-B"
            kv = cc.kernel(k, True)
            labels = {n: f[0] for n, f in kv.items()}
            assert labels == openings[role]["labels"]
            check = cc.products(k, labels, blobs)
            assert before == check and cc.streams(b) == cc.streams(k)
            behavior = oo.probes(k / "native", "B", role)
            assert oo.observables(behavior) == oo.observables(openings[role]["witness"])
            proof = accept(d, role, check)
            stages[i, role] = (seed, stamp, check, labels, cc.streams(k))
            m.save(
                d / "native-before-score.json",
                dict(
                    same_seed=True,
                    canonical=proof["all_guarded"],
                    raw_cold=proof["raw_all_exact"],
                    all_uncertain=proof["fixed_input_owners_required"],
                ),
            )
    assert len({v[1]["sha256"] for v in stages.values()}) == 12
    m.save(
        panel / "all-native-guards.json",
        dict(
            roles=list(s.ROLES),
            independent=12,
            orders=orders,
            boot=boot,
            fixed={
                r: {n: sorted(v) for n, v in rows.items()}
                for r, rows in fixed_classes.items()
            },
            case=s.case["registered"],
        ),
    )
    for i, order in enumerate(orders):
        for role in order:
            m.choose(role, bank, sdks)
            d = panel / (str(i + 1) + "-" + role)
            seed, stamp, expected, labels, stream = stages[i, role]
            cc.source("B")
            for mode in (
                ("wall", "whole", "threads")
                if i % 2 == 0
                else ("threads", "whole", "wall")
            ):
                dest = d / mode
                fixed.restore(seed, stamp)
                if mode == "threads":
                    scoped.measure(dest, list(labels.values()), sdks[role]["runtime"])
                else:
                    primary.command(
                        dest,
                        s.CHECK,
                        "pmu" if mode == "whole" else "native",
                        binary if mode == "whole" else None,
                    )
                assert (
                    cc.products(dest, labels, blobs) == expected
                    and cc.streams(dest) == stream
                    and cc.source("B")["tree"] == s.case["trees"]["B"]
                )
                obs = oo.probes(dest / "native", "B", role)
                assert oo.observables(obs) == oo.observables(openings[role]["witness"])
                m.save(
                    dest / "verified.json",
                    dict(
                        same_seed=True,
                        seed=stamp["sha256"],
                        native=m.filesha(d / "kernel-B/products.json"),
                        measured=m.filesha(dest / "products.json"),
                        source=s.case["B"],
                        boot=boot,
                    ),
                )
            print("completed pair arm", i + 1, role, flush=True)
    for role in s.ROLES:
        m.choose(role, bank, sdks)
        m.save(
            panel / ("final-sdk-" + role + ".json"),
            primary.final_sdk(role, sdks, m.SDK, out),
        )
