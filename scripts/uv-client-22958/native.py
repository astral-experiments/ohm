"""Qualify both distributions and sixteen independent histories before the eight wall pairs."""

from pathlib import Path
import gzip
import os
import re
import shutil
import subprocess
import time
import traceback
import blocking_clock
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


def noedit(place, archive, stamp, labels, expected, blobs):
    fixed.restore(archive, stamp)
    plain = place / "plain"
    cc.checked_run(s.CHECK, plain)
    assert cc.products(plain, labels, blobs) == expected
    fixed.restore(archive, stamp)
    traced = place / "kernel"
    forms = cc.kernel(traced, None)
    assert cc.products(traced, labels, blobs) == expected
    def stream(d):
        err = (d / "cargo.stderr").read_text()
        normalized, n = re.subn(r"(?m)^(    Finished `dev` profile \[unoptimized \+ debuginfo\] target\(s\)) in [^\r\n]+$", r"\1", err)
        assert n == 1
        return m.filesha(d / "cargo.stdout"), normalized
    assert stream(plain) == stream(traced)
    fixed.restore(archive, stamp)
    m.save(place / "verified.json", dict(seed=stamp, forms=forms, same_material=True))
    return forms


def qualify_role(role, ds, blobs):
    cc.source("A")
    fixed.target_reset()
    cold_a = ds / "cold-A"
    a = cc.kernel(cold_a, False)
    ro = {n: a[n][0] for n in ("uv_configuration", "uv_client")}
    old_products = cc.products(cold_a, ro, blobs)
    first = oo.probes(cold_a / "native", "A", role)
    archive = m.ROOT / "bank" / (ds.name + "-A.tar.zst")
    a_stamp = fixed.make_seed(archive)
    recurring_a = noedit(sub(ds / "noedit-A"), archive, a_stamp, ro, old_products, blobs)
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
    saved = m.ROOT / "bank" / (ds.name + "-B.tar.zst")
    stamp = fixed.make_seed(saved)
    recurring_b = noedit(sub(ds / "noedit-B"), saved, stamp, {n: fb[n][0] for n in actual}, fresh, blobs)
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
        recurring={"A": recurring_a, "B": recurring_b},
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


def wall(path, boot, mask):
    path.mkdir()
    assert set(os.sched_getaffinity(0)) == mask
    with (path/"cargo.stdout").open("xb") as so, (path/"cargo.stderr").open("xb") as se:
        measured = blocking_clock.measure(s.CHECK, cwd=m.SRC, env=m.ENV, stdout=so, stderr=se)
    assert measured["exit"] == 0 and set(os.sched_getaffinity(0)) == mask
    m.save(path/"ordinary.json", dict(**measured, mode="native", invoked=s.CHECK, boot=boot, cpus=sorted(mask), env=m.ENV))


def refusal(ds, inp, blobs):
    warm, cold = inp["first"], inp["fresh"]
    def raw(pair):
        n, sha = pair
        data = gzip.decompress((blobs/(sha+".gz")).read_bytes())
        assert len(data) == n and m.digest(data) == sha
        return data
    assert set(warm["workspace"]) == set(cold["workspace"]) and set(warm["all_public_sidecars"]) == set(cold["all_public_sidecars"])
    changed = {n:[a,cold["all_public_sidecars"][n]] for n,a in warm["all_public_sidecars"].items() if a != cold["all_public_sidecars"][n]}
    present = {n:[a,cold["workspace"][n]] for n,a in warm["workspace"].items() if a != cold["workspace"][n]}
    terminal, = [n for n in warm["workspace"] if Path(n).name.startswith("libuv_client-")]
    for name, row in (("warm-B",warm), ("cold-B",cold)):
        b=raw(row["workspace"][terminal]);f=ds/(name+".uv_client.rmeta");f.write_bytes(b)
        info=subprocess.run([m.RUSTC,"-Zls=root",f],cwd=m.SRC,env=m.ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        (ds/(name+".uv_client-ls.txt")).write_bytes(info.stdout+info.stderr)
    result=dict(changed_public_sidecars=changed, changed_workspace=present,
        native_matching_observables=True, score_permitted=False, same_seed_primary_and_kernel=True,
        warm_inventory=m.filesha(ds/"initial-kernel/products.json"),cold_inventory=m.filesha(ds/"fresh-B/products.json"),
        error=traceback.format_exc())
    m.save(ds/"unchanged-identity-refusal.json",result)
    return result


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
    migration=m.read(out/"intake/release-migration.json")
    assert migration["fixtures_only"] and migration["ordinary_benchmark_caches_separate"] and set(migration["roles"]) == {"S-F","F-S"}
    clk=m.read(out/"blocking-clock-pre/verified.json")
    assert clk["eligible_blocking_calibration"] and clk["boot"]==boot and clk["affinity"]==sorted(mask)
    load = m.read(out / "intake.json")
    sdks = load["installed"]
    assert list(sorted(sdks)) == list(sorted(s.ROLES))
    bank = m.ROOT / "bank"
    m.save(out / "uv-source.json", cc.initialize(w, bank))
    pool = tmp / "ctfe22-root-sdks"
    for role in s.ROLES:
        assert sdks[role]["source"] == s.SOURCES[role]
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
    openings_seen=[m.read(panel/("opening-"+r)/"admitted.json") for r in s.ROLES]
    for k in ("A_observable","B_observable"):
        assert openings_seen[0][k] == openings_seen[1][k]
    names=lambda x:{state:{n:len(a)for n,a in forms.items()}for state,forms in x["recurring"].items()}
    assert names(openings_seen[0]) == names(openings_seen[1])

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

    failures={}
    for role in s.ROLES:
        m.choose(role, bank, sdks)
        cc.source("B")
        ds = panel / ("opening-" + role)
        try:
            accept(ds, role, openings[role]["first"])
        except AssertionError:
            failures[role]=refusal(ds,openings[role],blobs)
    if failures:
        m.save(panel/"refused-native-admission.json",failures)
        raise RuntimeError("At least one independent native warm/cold admission failed before any scored visit")
    orders = s.ORDERS
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
    assert len({v[1]["sha256"] for v in stages.values()}) == 16
    m.save(
        panel / "all-native-guards.json",
        dict(
            roles=list(s.ROLES),
            independent=16,
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
            visits=[]
            for mode in ("wall", "whole", "threads"):
                dest = d / mode
                fixed.restore(seed, stamp)
                started=time.monotonic_ns()
                if mode == "threads":
                    scoped.measure(dest, list(labels.values()), sdks[role]["runtime"])
                elif mode == "wall":
                    wall(dest,boot,mask)
                else:
                    primary.command(dest,s.CHECK,"pmu",binary)
                visits.append([mode,started,time.monotonic_ns()])
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
            m.save(d/"visit-order.json",visits)
            print("completed pair arm", i + 1, role, flush=True)
    for role in s.ROLES:
        m.choose(role, bank, sdks)
        m.save(
            panel / ("final-sdk-" + role + ".json"),
            primary.final_sdk(role, sdks, m.SDK, out),
        )
