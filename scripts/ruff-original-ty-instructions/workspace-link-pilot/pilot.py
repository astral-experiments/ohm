"""Measure a fresh native write on the frozen 48 roles through ordinary Cargo."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import gzip, json, os, shutil, stat, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [
    str(HERE),
    str(HERE.parent / "workspace-link-proof"),
    str(HERE.parent / "e2e-existing-output"),
]
import native_fallback
import audit, multi_source

b, w, P = audit.b, audit.w, audit.P
put = lambda name, data: b.write(P / name, data)
read = lambda p: json.loads(p.read_bytes())
ROLES = read(HERE.parent / "workspace-link-proof/roles.json")
ACCEPTED = set(read(HERE / "accepted-48.json"))
E2E = multi_source.E2E
STOCK = audit.donor.WILD
RECEIPT_MEMORY = None


def original_env(release):
    if release == 23:
        return w.install()
    assert release == 24
    import release24

    return release24.install(w, P)


def reset_roots(env, registry):
    for p in (w.shared, w.target, w.home):
        assert p.is_dir() and not p.is_symlink() and p.parent == w.root
        shutil.rmtree(p)
    b.PHYSICAL.clear()
    assert b.inputs(env) == registry


def swap(original, to, expected):
    assert w.hf(original) == expected and to.parent.is_relative_to(w.sdk)
    new = to.with_name("qa-stage-physical-wild")
    assert not new.exists()
    shutil.copy2(original, new)
    os.replace(new, to)
    assert w.hf(to) == expected


def rolemap(inv):
    found = {}
    for path, entry in inv["executables"].items():
        for role in ROLES:
            if path.endswith(role):
                assert role not in found and ROLES[role]["owner"] == entry["unit"]
                found[role] = (w.root / path, entry["elf"]["sha256"])
    assert len(found) == 50 and len(inv["executables"]) == 102
    return found


def storage(paths, inst):
    targets = {str(p) for p, h in paths.values()}
    sizes = defaultdict(set)
    images = defaultdict(list)
    normal = {}
    for role, (p, h) in paths.items():
        st = p.lstat()
        assert stat.S_ISREG(st.st_mode) and not p.with_suffix(".delete").exists()
        sizes[st.st_size].add(h)
        images[h].append(str(p))
        normal[role] = [
            st.st_dev,
            st.st_ino,
            st.st_size,
            512 * st.st_blocks,
            st.st_nlink,
        ]
    aliases = []
    for base in (w.shared, w.target):
        for directory, subdirs, files in os.walk(base, followlinks=False):
            for name in files:
                p = Path(directory) / name
                if str(p) in targets:
                    continue
                try:
                    st = p.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(st.st_mode) and st.st_size in sizes:
                    h = w.hf(p)
                    if h in sizes[st.st_size]:
                        aliases.append(
                            [
                                str(p.relative_to(w.root)),
                                h,
                                st.st_dev,
                                st.st_ino,
                                st.st_size,
                                512 * st.st_blocks,
                            ]
                        )
    put(
        inst + "-retained-generations.json.gz",
        {"canonical": normal, "other_same_image": aliases},
    )
    return aliases


def originals(state, td):
    files = list(state.glob("actor-*.tsv"))
    raw = {}
    for p in files:
        data = p.read_bytes()
        assert 0 < len(data) < 48 << 20
        pid = p.stem[6:]
        assert pid.isdecimal() and pid not in raw
        gz = td / ("actor-" + pid + ".tsv.gz")
        gz.write_bytes(gzip.compress(data, compresslevel=2, mtime=0))
        raw[pid] = data.decode()
    for pattern in ("actor-*.tsv", "ready-*", "answer-*"):
        for p in state.glob(pattern):
            assert p.parent == state and p.is_file() and not p.is_symlink()
            p.unlink()
    return raw


def stage(
    tag,
    arm,
    env,
    meta,
    state,
    image,
    llvm,
    *,
    expected=0,
    typed=True,
    mode="allow",
    raw_failure=None,
):
    td = P / tag
    source = arm == "C"
    report = td / "physical-decisions.json"
    oldrun = b.run
    cargo = shutil.which("cargo", path=env["PATH"])
    direct = list(b.CMD)
    assert direct[0] == "cargo" and cargo and Path(cargo).is_absolute()

    def observed(argv, current, place, allowed=0):
        assert current is env and place == td and list(argv) == direct
        if source:
            argv = [
                sys.executable,
                "-IB",
                str(HERE / "coordinator.py"),
                str(state),
                str(report),
                image,
                str(llvm),
                tag,
                mode,
                str(RECEIPT_MEMORY),
                os.environ["ENROLLED_RELEASE"],
                cargo,
                *direct,
            ]
        return oldrun(
            argv,
            env,
            td,
            allowed=expected,
            pass_fds=(RECEIPT_MEMORY,) if source else (),
        )

    b.run = observed
    try:
        if expected:
            td.mkdir()
            b.run(direct, env, td)
            data = (td / "stdout.jsonl").read_bytes()
            msgs = [json.loads(r) for r in data.splitlines()]
            assert msgs[-1] == {"reason": "build-finished", "success": False}
            assert any(
                m.get("reason") == "compiler-message"
                and m["message"]["level"] == "error"
                for m in msgs
            )
            if raw_failure:
                assert raw_failure in (data + (td / "stderr").read_bytes()), (
                    tag,
                    raw_failure,
                )
            inv = None
        else:
            inv = b.inventory(tag, env, meta, "plain")
    except BaseException:
        if source and td.is_dir():
            originals(state, td)
        raise
    finally:
        b.run = oldrun
    raw = originals(state, td) if source else {}
    if not source:
        assert not list(state.glob("actor-*.tsv"))
    info = {
        "source_role_logs": len(raw),
        "arm": arm,
        "exit": expected,
        "state": w.git("rev-parse", "HEAD"),
    }
    if source:
        receipt = read(report)
        assert receipt["exit"] == expected
        info["proof_refusals"] = receipt["proof_refusals"]
        if not expected:
            assert receipt["commit"] and len(raw) == 48
            acted = receipt["actors"]
            # A grammar refusal always receives full. Its native completion stays in the packet.
            assert (
                len(acted) + len(receipt["proof_refusals"]) == 48
                and acted.keys() <= ACCEPTED
            )
            info["actions"] = dict(Counter(r["action"] for r in acted.values()))
            info["fresh_roles"] = sorted(
                k for k, r in acted.items() if r["action"] == "fresh"
            )
            info["native_bytes_consumed"] = sum(
                r["input_bytes"] for r in acted.values()
            )
            info["held_allocated"] = sum(r["held_allocated"] for r in acted.values())
            info["signed_output_reads_for_donor"] = sum(
                r.get("donor_bytes_read_after_emission", 0) for r in acted.values()
            )
            info["metadata_bytes"] = receipt["after_bytes"]
            for k, r in acted.items():
                assert r["pid"] in raw and k in raw[r["pid"]]
        else:
            assert not receipt["commit"] and not any(
                k for k in raw if "FRESH-PUBLISH\t" in raw[k] and E2E in raw[k]
            )
    assert not (td / "hardware.json").exists() and not (td / "tasks").exists()
    resources = read(td / "resources.json")
    assert resources["exit"] == expected and resources["minimum_mem"] >= 8 * 2**30
    info["acquisition"] = "ordinary-unmetered"
    if inv is not None:
        paths = rolemap(inv)
        exe = w.root / inv["binary"]
        if typed:
            assert (
                b.verdict(exe, tag + "-native", env, 0)
                == audit.contact.LITERALS["list"]
            )
        info["published"] = {k: h for k, (p, h) in paths.items()}
        info["output_sizes"] = {k: p.stat().st_size for k, (p, h) in paths.items()}
        if source:
            for k, r in receipt["actors"].items():
                if "physical" not in r:
                    continue
                st = paths[k][0].lstat()
                ph = r["physical"]
                assert [st.st_dev, st.st_ino, st.st_size] == [
                    ph["dev"],
                    ph["ino"],
                    ph["size"],
                ]
        if tag.endswith(("warm1", "empty-new")):
            info["same_bytes_elsewhere"] = storage(paths, tag)
    else:
        exe = None
    put(tag + "-receipt.json.gz", info)
    return info, exe


def main():
    global RECEIPT_MEMORY, ROLES
    RECEIPT_MEMORY = os.memfd_create("ohm-bounded-links", os.MFD_CLOEXEC)
    assert os.fstat(RECEIPT_MEMORY).st_size == 0
    assert (
        os.environ["REVIEWED_HEAD"] == os.environ["GITHUB_SHA"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
    )
    assert w.git("rev-parse", "HEAD") == b.NEW and w.git("rev-parse", "HEAD^") == b.OLD
    assert (
        w.hf(w.src / "sdk.json") == b.SPEC["sdk_manifest"]
        and len(ACCEPTED) == 48
        and ACCEPTED < set(ROLES)
    )
    assert shutil.disk_usage(w.root).free > 45 * 2**30
    w.guard()
    b.save_elf = w.hf
    release = int(os.environ["ENROLLED_RELEASE"])
    assert release == 24
    from release_scope import for_release

    ROLES = for_release(release)
    reg = read(HERE / "source-preflight.json")
    put(
        "admission.json",
        {
            "run": os.environ["GITHUB_RUN_ID"],
            "head": os.environ["GITHUB_SHA"],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "runner": os.environ["RUNNER_NAME"],
            "source_registration": reg,
            "roles": sorted(ACCEPTED),
            "Ruff": [b.OLD, b.NEW],
            "release": release,
            "kind": "unmetered-native-safety-v1",
        },
    )
    env = original_env(release)
    state = w.root / "native-donor-state"
    state.mkdir()
    stock, llvm = audit.build(
        env, source=multi_source.apply, registration=HERE / "source-preflight.json"
    )
    live = w.sdk / "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
    actor = w.root / "qa-diagnostic-build/target/release/wild"
    sha = w.hf(actor)
    assert w.hf(live) == sha
    image = audit.donor.full_b3(live)
    audit.calibrate(env, state)
    originals(state, P)
    put(
        "physical.json",
        {"stock": w.hf(stock), "actor": sha, "image_b3": image, "llvm": w.hf(llvm)},
    )
    b.select(b.OLD)
    registry = b.inputs(env)
    put("registry.json.gz", registry)
    meta = json.loads(
        subprocess.check_output(
            [
                "cargo",
                "+ohm",
                "metadata",
                "--format-version=1",
                "--locked",
                "--offline",
                "--no-deps",
            ],
            cwd=w.work,
            env=env,
        )
    )
    assert (
        sorted(meta["workspace_default_members"]) == sorted(meta["workspace_members"])
        and len(meta["workspace_default_members"]) == 55
    )
    provider = audit.donor.provider_file()
    results = {}

    def run(tag, arm, **kw):
        record, path = stage(tag, arm, env, meta, state, image, llvm, **kw)
        results[tag] = record
        return path

    for arm in ("P", "C"):
        swap(stock if arm == "P" else actor, live, STOCK if arm == "P" else sha)
        if arm == "C":
            # The previous P clean and this C clean are independent; no target or donor survives either reset.
            state.joinpath("coordinate").touch(exist_ok=False)
            b.select(b.NEW)
            reset_roots(env, registry)
            assert os.fstat(RECEIPT_MEMORY).st_size == 0
            run("C-empty-new", "C")
            reset_roots(env, registry)
            os.ftruncate(RECEIPT_MEMORY, 0)
            assert os.fstat(RECEIPT_MEMORY).st_size == 0
        b.select(b.OLD)
        out = run(arm + "-old", arm)
        b.select(b.NEW)
        assert (
            b.verdict(out, arm + "-withheld-old-on-new", env, 101)
            == audit.contact.LITERALS["list"]
        )
        out = run(arm + "-edit", arm)
        out = run(arm + "-warm1", arm)
        b.select(b.OLD)
        out = run(arm + "-ordinary-repeat-old", arm)
        b.select(b.NEW)
        assert (
            b.verdict(out, arm + "-withheld-ordinary-repeat-old", env, 101)
            == audit.contact.LITERALS["list"]
        )
        out = run(arm + "-ordinary-repeat-edit", arm)
        if arm == "P":
            reset_roots(env, registry)
            run("P-empty-new", "P")
    put(
        "ordinary-second-edit-and-empty.json",
        {
            "certified_second_edit_hits": results["C-ordinary-repeat-edit"][
                "fresh_roles"
            ],
            "P_second_vs_signed_empty": {
                k: results["P-ordinary-repeat-edit"]["published"][k]
                == results["P-empty-new"]["published"][k]
                for k in ROLES
            },
            "C_second_vs_signed_empty": {
                k: results["C-ordinary-repeat-edit"]["published"][k]
                == results["P-empty-new"]["published"][k]
                for k in ROLES
            },
            "C_independent_empty_vs_signed_empty": {
                k: results["C-empty-new"]["published"][k]
                == results["P-empty-new"]["published"][k]
                for k in ROLES
            },
        },
    )
    # Invalidation via the ordinary existing native / source inputs. The withheld
    # original P and C binaries above already exercised the real changed Ruff text.
    symbol_input = None
    if release == 24:
        # Freeze the actual generated operand before any mutation. Its entire byte
        # sequence was the normal source actor's operand on the real edit frame.
        prior = read(P / "C-ordinary-repeat-edit" / "physical-decisions.json")[
            "actors"
        ][E2E]
        live_log = gzip.decompress(
            (
                P / "C-ordinary-repeat-edit" / ("actor-" + prior["pid"] + ".tsv.gz")
            ).read_bytes()
        ).decode()
        (actual,) = [
            r.split("\t")
            for r in live_log.splitlines()
            if r.startswith("FROZEN\t") and r.endswith("/symbols.o")
        ]
        assert len(actual) == 6 and 48 < int(actual[3]) <= 1 << 20
        symbol_input = (int(actual[3]), actual[4])
        put("genuine-temporary-symbol-input.json", symbol_input)
    for mode in (("earlier",) if release == 24 else ()) + (
        "four",
        "malformed",
        "mid-read",
    ):
        labels = {
            "earlier": "C-native-earlier",
            "four": "C-native-four",
            "malformed": "C-native-malformed",
            "mid-read": "C-native-save",
        }
        tag = labels[mode]
        # Obtain an actual eligible normal e2e publication before the challenge. All
        # attempts run ordinary Cargo with its real jobserver and remain in the archive.
        for n in range(1, 7):
            before = "C-before-native-" + mode + "-" + str(n)
            out = run(before, "C")
            normal_actor = read(P / before / "physical-decisions.json")["actors"][E2E]
            if normal_actor.get("physical") and normal_actor["allowed"]:
                break
        else:
            raise AssertionError("No actual certified normal e2e output before " + mode)
        put(
            "selected-before-native-" + mode + ".json",
            {"phase": before, "sha256": results[before]["published"][E2E]},
        )
        wait = state / ("mid-read" if mode == "mid-read" else "entry-wait")
        wait.touch(exist_ok=False)
        with ThreadPoolExecutor(max_workers=1) as pool:
            edit = pool.submit(
                audit.donor.witness, state, mode, provider, out, symbol_input
            )
            current = run(
                tag,
                "C",
                expected=0 if mode in ("four", "earlier") else 101,
                typed=mode == "earlier",
            )
            mutation = edit.result(timeout=135)
        put(tag + "-actual-change.json", mutation)
        if mode in ("earlier", "four"):
            proof = native_fallback.on_worker(
                P / tag,
                E2E,
                mutation,
                provider,
                current,
                results[before]["published"][E2E],
                results[tag]["published"][E2E],
                w.hf,
                audit.donor.full_b3,
            )
            put(tag + "-full-output.json", proof)
        if mode == "four":
            ret = subprocess.run(
                [current, "--list"],
                cwd=w.work / "crates/ty_server",
                env=env,
                capture_output=True,
            )
            assert ret.returncode == 83 and not ret.stdout
            put(tag + "-verdict.json", {"exit": ret.returncode, "stdout_bytes": 0})
        for f in (
            "mid-read",
            "entry-wait",
            "entry-ready",
            "read-first-half",
            "entry-continue",
            "continue-read",
        ):
            (state / f).unlink(missing_ok=True)
        out = run(tag + "-repair", "C")
    out = run("C-before-output-control-1", "C")
    wanted = {E2E} | {
        k
        for k in ACCEPTED
        if k.startswith("/ty_ide/") and k.split("/")[-1].startswith("ty_ide-")
    }
    assert len(wanted) == 2
    for attempt in range(2, 7):
        before_corruption = "C-before-output-control-" + str(attempt)
        out = run(before_corruption, "C")
        if wanted <= set(results[before_corruption]["fresh_roles"]):
            break
    else:
        raise AssertionError(
            "Two true unchanged existing-output admissions required before corruption"
        )
    put(
        "before-output-selection.json",
        {"phase": before_corruption, "targets": sorted(wanted)},
    )

    targets = {E2E: out}
    if release == 24:
        (ide,) = [
            k
            for k in ACCEPTED
            if k.startswith("/ty_ide/") and k.split("/")[-1].startswith("ty_ide-")
        ]
        inv = json.loads(
            gzip.decompress((P / before_corruption / "inventory.json.gz").read_bytes())
        )
        paths = rolemap(inv)
        targets[ide] = paths[ide][0]
        for trial in range(1, 7):
            phase = "C-distinct-OPATHs" + ("" if trial == 1 else "-" + str(trial))
            held = {
                k: os.open(path, os.O_PATH | os.O_CLOEXEC)
                for k, path in targets.items()
            }
            start = time.monotonic_ns()
            controls = {}
            try:
                out = run(phase, "C")
                # A genuine multi-thread full link can keep the old inode. Never write through
                # a held descriptor until BOTH registered outputs actually publish fresh inodes.
                if not set(targets) <= set(results[phase]["fresh_roles"]):
                    put(
                        phase + "-ordinary-fallback.json",
                        {"fresh": results[phase]["fresh_roles"]},
                    )
                    continue
                for k, fd in held.items():
                    old = os.fstat(fd)
                    now = targets[k].lstat()
                    assert old.st_nlink == 0 and (old.st_dev, old.st_ino) != (
                        now.st_dev,
                        now.st_ino,
                    )
                    with open(
                        "/proc/self/fd/" + str(fd), "r+b", buffering=0
                    ) as writable:
                        assert os.pwrite(writable.fileno(), bytes(2), 18) == 2
                    assert w.hf(targets[k]) == results[phase]["published"][k]
                    controls[k] = {
                        "old": [
                            old.st_dev,
                            old.st_ino,
                            old.st_size,
                            512 * old.st_blocks,
                            old.st_nlink,
                        ],
                        "new": [now.st_dev, now.st_ino],
                        "held_ns": time.monotonic_ns() - start,
                    }
            finally:
                for fd in held.values():
                    os.close(fd)
            break
        else:
            raise AssertionError(
                "Both genuine fresh generations required in one held-OPATH command"
            )
        put("actual-canonical-OPATHs.json", controls)
        put("actual-canonical-OPATHs-stage.json", {"phase": phase})
    for trial in range(1, 7):
        suffix = "" if trial == 1 else "-" + str(trial)
        refs = {k: results[phase]["published"][k] for k in targets}
        for k, path in targets.items():
            put(
                "corrupted-existing-" + k.split("/")[-1] + suffix + ".json",
                audit.witness.corrupt_text(path, audit.donor.text_flip, refs[k]),
            )
        phase = "C-actual-output-repair" + suffix
        out = run(phase, "C")
        repaired = read(P / phase / "physical-decisions.json")["actors"]
        for k in targets:
            # Any apparent hit or unrepaired output is an immediate safety failure.
            assert repaired[k]["action"] in ("full", "full-typed-refusal")
            assert results[phase]["published"][k] == refs[k] == w.hf(targets[k])
        proved = {
            k
            for k in targets
            if repaired[k]["action"] == "full"
            and repaired[k]["response"] == "verify"
            and "output-bytes-or-generation" in repaired[k]["reasons"]
        }
        if set(targets) == proved:
            break
        put(phase + "-ordinary-fallback.json", {"verified_corruption": sorted(proved)})
        for attempt in range(1, 7):
            phase = "C-train-output-repair-" + str(trial) + "-" + str(attempt)
            out = run(phase, "C")
            if set(targets) <= set(results[phase]["fresh_roles"]):
                break
        else:
            raise AssertionError(
                "Two genuine prior outputs required to retry the physical corruption test"
            )
    else:
        raise AssertionError(
            "Actual output-byte verification and real relink required on both corrupt outputs"
        )
    put("actual-output-repair-stage.json", {"phase": phase, "targets": sorted(targets)})
    # Include a normal Rust error through the very same test command, then restore
    # the tracked bytes before the independent empty histories.
    source = w.work / "crates/ty_server/src/lib.rs"
    original = source.read_bytes()
    try:
        source.write_bytes(original + b"\nconst _: () = 279;\n")
        run("C-actual-type-error", "C", expected=101, typed=False, raw_failure=b"E0308")
    finally:
        source.write_bytes(original)
    assert not w.git("status", "--porcelain")
    out = run("C-actual-type-repair", "C")
    # Persist all raw directions/section inventories before refusing a comparison.
    reference = results["P-empty-new"]
    violations = {}
    all_diffs = {}
    for tag, row in results.items():
        if "published" not in row or tag == "C-native-four":
            continue
        other = results["P-old"] if tag.endswith("-old") else reference
        complete = {
            k: [row["published"][k], other["published"][k]]
            for k in ROLES
            if row["published"][k] != other["published"][k]
        }
        all_diffs[tag] = complete
        # Stronger than actual hit-only: training, edit, repair and empty C must
        # independently reproduce the signed full ELF on all 48 frozen candidates.
        if tag.startswith("C-") and any(k in ACCEPTED for k in complete):
            violations[tag] = sorted(ACCEPTED & complete.keys())
        if row.get("fresh_roles") and set(row["fresh_roles"]) & complete.keys():
            violations[tag] = sorted(set(row["fresh_roles"]) & complete.keys())
    put("all-signed-native-differences.json.gz", all_diffs)
    put(
        "complete.json",
        {
            "qualified": not violations,
            "failures": violations,
            "kind": "unmetered-native-safety-v1",
            "all_actions": {
                k: r.get("actions") for k, r in results.items() if k.startswith("C-")
            },
            "default_members": 55,
            "executables": 102,
            "whole_signed_roles": 50,
            "frozen_eligible": 48,
        },
    )
    assert not violations, violations


if __name__ == "__main__":
    main()
