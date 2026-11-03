"""Run independently built A histories. The bare, whole-command and all-rustc visits always restore the same A."""

from pathlib import Path
import gzip, hashlib, json, os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import *
import oracle


def product_set(d, store=None):
    snap, relative = surface()
    save(d / "products.json", snap)
    if store:
        for k, fp in snap["rmeta"].items():
            source = TARGET / relative[k]
            if not (store / (fp[1] + ".gz")).exists():
                require(retain(source, store) == fp, "retaining original metadata")
        for rel, expected in snap["sidecars"].items():
            raw = (TARGET / rel).read_bytes()
            require(
                [len(raw), hashlib.sha256(raw).hexdigest()] == expected,
                "public product changed during capture",
            )
            path = store / (expected[1] + ".public-api-hash")
            if path.exists():
                require(path.read_bytes() == raw, "content-addressed public hash collision")
            else:
                with path.open("xb") as stream:
                    stream.write(raw)
    return snap, relative


def producer(d, originals, reader, phase):
    a = [
        p
        for k, p in originals.items()
        if Path(k).name.startswith("libuv_python-") and "/incremental/" not in k
    ]
    require(len(a) == 1, "one source uv_python")
    p = TARGET / a[0]
    out = oracle.identities(p, reader, (SRC / "crates/uv-python/src/discovery.rs").read_bytes(), phase)
    save(d / "python-identities.json", out)
    return out


def fresh(d, store, reader):
    require(not TARGET.is_symlink(), "unexpected target")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    ordinary(d)
    sur, local = product_set(d, store)
    return sur, producer(d, local, reader, "B")


def scrubbed(argv):
    """Keep the full vector, abstracting only Cargo's locally proven 64-bit per-unit salts."""
    prefix = str(TARGET / "debug/build") + "/"
    result = []
    for original in argv:
        arg = re.sub(
            re.escape(prefix) + r"([^/]+)/[0-9a-f]{16}/",
            r"{build}/\1/{Cargo-unit-salt}/",
            original,
        )
        arg = re.sub(
            r"(?<=/)(lib[a-zA-Z_0-9]+)-[0-9a-f]{16}(?=\.(?:rlib|rmeta|so))",
            r"\1-{Cargo-unit-salt}",
            arg,
        )
        arg = re.sub(
            r"^(extra-filename=-|metadata=)[0-9a-f]{16}$",
            r"\1{Cargo-unit-salt}",
            arg,
        )
        result.append(arg)
    return result


def rooted_externs(forms):
    result = {}
    for name, a in forms.items():
        externs = []
        for i, t in enumerate(a):
            if t == "--extern":
                spell, sep, path = a[i + 1].partition("=")
                require(sep and Path(path).is_file(), "missing compiler input")
                externs.append([spell, path, blob(Path(path))])
        require(externs, "empty extern set")
        result[name] = externs
    return result


def behavior(role, d):
    require(not d.exists(), "separate test evidence")
    d.mkdir()
    target = ROOT / "behavior-target"
    require(not target.exists(), "separate linked behavior target")
    env = dict(
        ENV,
        CARGO_TARGET_DIR=str(target),
        CARGO_INCREMENTAL="0",
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_PROFILE_TEST_DEBUG="0",
        INSTA_UPDATE="no",
    )
    results = {}
    for st in "AB":
        source(SRC, st)
        cases = [
            (
                "stream",
                "sequential_query_strategy_does_not_prefetch",
                "discovery::tests::sequential_query_strategy_does_not_prefetch_"
                + {"A": "executables", "B": "executable_groups"}[st],
            )
        ]
        if st == "B":
            cases.append(
                (
                    "ordering",
                    "installation_key_order_only_partitions_critical_errors",
                    "discovery::tests::installation_key_order_only_partitions_critical_errors",
                )
            )
        for label, filt, test in cases:
            dd = d / (st + "-" + label)
            dd.mkdir()
            cmd = [
                str(CARGO),
                "test",
                "--locked",
                "--offline",
                "-j8",
                "-p",
                "uv-python",
                "--lib",
                filt,
                "--",
                "--test-threads=1",
            ]
            with (dd / "stdout").open("xb") as f, (dd / "stderr").open("xb") as e:
                invoke(cmd, SRC, env, stdout=f, stderr=e)
            out = (dd / "stdout").read_text()
            require(
                re.findall(r"^test (\S+) \.\.\. ok$", out, re.M) == [test]
                and re.search(r"test result: ok\. 1 passed; 0 failed;", out),
                "actual linked test: " + test,
            )
            results[st + "-" + label] = test
    shutil.rmtree(target)
    save(d / "passed.json", results)
    return results


def opening(role, out, store, dec, reader):
    if TARGET.exists():
        shutil.rmtree(TARGET)
    source(SRC, "A")
    a = out / "cold-A"
    ordinary(a)
    _, pa = product_set(a)
    ids_a = producer(a, pa, reader, "A")
    kernel(out / "unchanged-A", False)
    seed = ROOT / "bank" / "opening-A.tar.zst"
    stamp = fixed_seed(seed)
    save(out / "seed.json", {"identity": stamp, "A": sha(a / "products.json")})
    source(SRC, "B")
    plain = out / "ordinary-first-B"
    ordinary(plain)
    unobserved, _ = product_set(plain)
    fixed_seed(seed, stamp)
    seed.unlink()
    b = out / "first-B"
    forms = kernel(b, True)
    warm, rel = product_set(b, store)
    require(warm == unobserved, "same A restored edited kernel/ordinary native products")
    ids_b = producer(b, rel, reader, "B")
    kernel(out / "unchanged-B", False)
    require(
        set(forms) == set(S["observed_F_dirty_libs"]),
        "changed first-edit actual compiler roster; preserve and adjudicate before reading prices",
    )
    save(out / "extern-inputs.json", rooted_externs(forms))
    cold, ids_c = fresh(out / "fresh-B", store, reader)
    checked = oracle.compare_native(warm, cold, store, dec, reader, out / "zls", role)
    oracle.compare_owners(ids_a, ids_b, ids_c, role)
    tested = behavior(role, out / "behavior")
    save(
        out / "native-accepted.json",
        {
            "role": role,
            "typed": checked,
            "behavior": tested,
            "owners": [
                sha(a / "python-identities.json"),
                sha(b / "python-identities.json"),
                sha(out / "fresh-B/python-identities.json"),
            ],
            "roster": sorted(forms),
            "score": None,
        },
    )
    return forms, tested


def select(role, pool, inventory):
    if SDK.exists():
        prev = next(n for n in pool if not (ROOT / "bank" / ("sdk-" + n)).exists())
        SDK.rename(ROOT / "bank" / ("sdk-" + prev))
    (ROOT / "bank" / ("sdk-" + role)).rename(SDK)
    require(sha(CARGO) == S["cargo_sha256"], "expected signed Cargo")
    for p, fd in inventory[role]["runtime"].items():
        require(sha(SDK / p) == fd, "selected runtime " + p)
    lines = invoke([RUSTC, "-vV"], SRC, ENV, stdout=subprocess.PIPE).stdout.decode().splitlines()
    require("commit-hash: " + P["roles"][role]["rust"] in lines, "selected native rustc")


def measure(d, role, opening_forms, store, dec, reader, cal):
    source(SRC, "A")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    from cold import capture as cold_capture

    a = d / "new-cold-A"
    cold_capture(a)
    _, ar = product_set(a)
    ids_a = producer(a, ar, reader, "A")
    kernel(d / "unchanged-A", False)
    seed = ROOT / "bank" / "current-A.tar.zst"
    stamp = fixed_seed(seed)
    save(d / "seed.json", {"bytes_sha256": stamp, "original_A": sha(a / "products.json"), "role": role})
    source(SRC, "B")
    fixed_seed(seed, stamp)
    k = d / "first-B"
    forms = kernel(k, True)
    warm, relative = product_set(k, store)
    require(forms == opening_forms, "changed actual rustc command")
    ids = producer(k, relative, reader, "B")
    save(k / "extern-inputs.json", rooted_externs(forms))
    fixed_seed(seed, stamp)
    bare = d / "bare"
    ordinary(bare)
    bs, _ = product_set(bare)
    require(bs == warm, "bare native products")
    fixed_seed(seed, stamp)
    whole = d / "whole"
    whole.mkdir()
    with (whole / "stdout").open("xb") as out, (whole / "stderr").open("xb") as err:
        invoke([cal["plain"], whole / "raw.json", *CHECK], SRC, ENV, stdout=out, stderr=err)
    complete, _ = product_set(whole)
    require(complete == warm and b"Finished" in (whole / "stderr").read_bytes(), "whole Cargo products")
    fixed_seed(seed, stamp)
    per = d / "per-rustc"
    per.mkdir()
    req = {
        "command": CHECK,
        "environment": ENV,
        "cwd": str(SRC),
        "compiler_path": str(RUSTC),
        "selectors": forms,
    }
    save(d / "request.json", req)
    fid = EV["file_id"](RUSTC)
    invoke(
        [sys.executable, "-ISB", METER / "per_rustc.py", "capture", d / "request.json", per, cal["library"]],
        SRC,
        {"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    counted = read(per / "per-rustc.json")
    tree = EV["decode"](read(per / "kernel-events.json"))
    seen, _ = forms_from_tree(tree, fid)
    require(seen == forms and set(counted["targets"]) == set(forms), "complete scoped kernel roster")
    save(per / "images.json", {"cargo": EV["file_id"](CARGO), "rustc": fid})
    data, _ = product_set(per)
    require(data == warm, "scoped products")
    kernel(d / "unchanged-B", False)
    cold, ids_c = fresh(d / "independent-cold-B", store, reader)
    checked = oracle.compare_native(warm, cold, store, dec, reader, d / "zls", role)
    oracle.compare_owners(ids_a, ids, ids_c, role)
    save(
        d / "native-accepted.json",
        {
            "role": role,
            "full_typed": checked,
            "warm": sha(k / "products.json"),
            "cold": sha(d / "independent-cold-B/products.json"),
            "true_compilers": sorted(forms),
            "complete_separate_visits": True,
        },
    )
    seed.unlink()


def main(out, donor, pool, control, mode):
    independent_role_sources(control, "G")
    require(not ROOT.exists() and not (out / "panel").exists(), "clean acquisition entry")
    ROOT.mkdir()
    (ROOT / "home").mkdir()
    (ROOT / "cargo").mkdir()
    bank = ROOT / "bank"
    bank.mkdir()
    source(SRC, "A", donor)
    inventory = read(out / "installed.json")
    roles = [control, "G"]
    require(set(roles) == set(inventory), "both actual toolchains")
    for role in roles:
        (pool / role).rename(bank / ("sdk-" + role))
    select(control, roles, inventory)
    invoke([CARGO, "fetch", "--locked"], SRC, dict(ENV, CARGO_NET_OFFLINE="false"))
    save(out / "registry.json", package_input())
    d = out / "panel"
    d.mkdir()
    store = out / "blobs"
    store.mkdir()
    dec, r = oracle.toolkit(ROOT / "typed-readers", store)
    form = {}
    tests = {}
    for role in roles:
        select(role, roles, inventory)
        o = d / ("opening-" + role)
        o.mkdir()
        form[role], tests[role] = opening(role, o, store, dec, r)
    require(tests[control] == tests["G"], "real user behavior differs across compiler roles")
    across = {}
    for role in roles:
        where = d / ("opening-" + role)
        cohort = {
            stage: product_roster(read(where / stage / "products.json"))
            for stage in ("cold-A", "ordinary-first-B", "first-B", "fresh-B")
        }
        require(
            all(x == cohort["cold-A"] for x in cohort.values()),
            "changed role-specific package product identity",
        )
        across[role] = cohort["first-B"]
    require(across[control] == across["G"], "different source-package/salt-free native product sets")
    save(
        d / "cross-role-native.json",
        {
            "logical_products": across[control],
            "native_behavior": tests,
            "first-B": {r: sha(d / ("opening-" + r) / "first-B/products.json") for r in roles},
        },
    )
    for n in S["observed_F_dirty_libs"]:
        require(
            scrubbed(form[control][n]) == scrubbed(form["G"][n]),
            "non-identity cross-role compiler command or changed extern " + n,
        )
    cal = read(out / "boot-attestation.json")["tools"]
    for i, order in enumerate(P["orders"][mode], 1):
        for tag in order.split("/"):
            role = control if tag == "control" else tag
            select(role, roles, inventory)
            path = d / (str(i) + "-" + role)
            path.mkdir()
            measure(path, role, form[role], store, dec, r, cal)
    save(
        d / "complete.json",
        {
            "mode": mode,
            "control": control,
            "orders": P["orders"][mode],
            "native": {r: sha(d / ("opening-" + r) / "native-accepted.json") for r in roles},
        },
    )
