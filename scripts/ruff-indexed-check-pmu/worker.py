"""Counterbalanced, whole-command instruction comparison on two real editable Ruff histories."""

import gzip, hashlib, json, math, os, random, re, shutil, statistics, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import ROOT, LOG, REG, need, sha, json_save

WS = Path(os.environ["GITHUB_WORKSPACE"])
WORK = ROOT / "work"
SRC = WORK / "ruff"
STATE = WORK / "state"
RUSTUP = WORK / "home/.rustup"
PROXIES = WORK / "proxies"


def run(args, *, cwd=None, env=None, check=True, timeout=420, pass_fds=()):
    p = subprocess.run(
        list(map(str, args)),
        cwd=cwd or WORK,
        env=env,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        pass_fds=pass_fds,
    )
    if check:
        need(
            p.returncode == 0,
            (
                args,
                p.returncode,
                p.stderr[-2700:].decode(errors="replace"),
                p.stdout[-500:].decode(errors="replace"),
            ),
        )
    return p


def git(root, *args):
    return run(["git", "-C", root, *args]).stdout.decode().strip()


def dump_gz(folder, name, data):
    (folder / name).write_bytes(gzip.compress(data, compresslevel=4, mtime=0))


def window(prefix, cmd, env, cwd, domain):
    if domain == "native":
        p = run(
            [WORK / "watch", prefix.with_suffix(".json"), *cmd],
            env=env,
            cwd=cwd,
            check=False,
        )
        v = json.loads(prefix.with_suffix(".json").read_bytes())
        if (
            v["event_errno"]
            or v["instructions"] <= 0
            or v["enabled"] != v["running"]
            or v["running"] <= 0
        ):
            return p, None
        return p, v["instructions"]
    with prefix.with_suffix(".lackey").open("xb") as log:
        p = run(
            [
                "valgrind",
                "--tool=lackey",
                "--basic-counts=yes",
                "--trace-children=yes",
                "--log-fd=" + str(log.fileno()),
                *cmd,
            ],
            env=env,
            cwd=cwd,
            pass_fds=(log.fileno(),),
            check=False,
            timeout=720,
        )
    path = prefix.with_suffix(".lackey")
    raw = path.read_bytes()
    numbers = re.findall(rb"^==[0-9]+==\s+guest instrs:\s*([0-9,]+)\s*$", raw, re.M)
    need(numbers and b"PTRACE_TRACEME" not in raw, "missing guest instruction counters")
    dump_gz(prefix.parent, prefix.name + ".lackey.gz", raw)
    path.unlink()
    return p, sum(int(i.replace(b",", b"")) for i in numbers)


def calibrate(env):
    d = LOG / "calibration"
    d.mkdir()
    src = WS / "collector/scripts/gnu-example-ceiling"
    for filename, expected in REG["reader"].items():
        need(sha(src / filename) == expected, filename)
        run(
            [
                "cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                src / filename,
                "-o",
                WORK / ("watch" if filename == "watch.c" else "loop"),
            ]
        )
    for domain in ("native", "Valgrind-guest"):
        outcomes = []
        good = True
        for mode, copies in [("0", 1), ("1", 2), ("thread", 2), ("exec", 1)]:
            values = []
            for i, n in enumerate([100001, 800001, 800001, 100001]):
                cmd = [WORK / "loop", mode, n, copies]
                r, c = window(
                    d / (domain + "-" + mode + "-" + str(i)), cmd, env, WORK, domain
                )
                need(
                    r.returncode == 0 and not r.stdout and not r.stderr,
                    "calibration program failed",
                )
                if c is None:
                    good = False
                    break
                values.append(c)
            if not good:
                break
            expected = 2 * copies * 700000
            delta = statistics.mean(values[1:3]) - statistics.mean(
                (values[0], values[3])
            )
            outcomes.append(
                dict(
                    mode=mode, copies=copies, raw=values, delta=delta, expected=expected
                )
            )
            if not abs(delta / expected - 1) < 0.02:
                good = False
                break
        json_save(d / (domain + ".json"), dict(qualified=good, cases=outcomes))
        if good:
            return domain
    raise ValueError("neither native nor guest instruction calibration passed")


def cpus():
    physical = {}
    for cpu in sorted(os.sched_getaffinity(0)):
        p = Path("/sys/devices/system/cpu") / ("cpu" + str(cpu)) / "topology"
        identity = tuple(
            (p / k).read_text().strip() for k in ("physical_package_id", "core_id")
        )
        physical.setdefault(identity, cpu)
    need(len(physical) >= 2, "need two distinct physical cores")
    selected = dict(list(physical.items())[:2])
    os.sched_setaffinity(0, set(selected.values()))
    json_save(
        LOG / "cpu.json",
        dict(
            selected=[
                dict(package=k[0], core=k[1], cpu=v) for k, v in selected.items()
            ],
            cpuinfo=Path("/proc/cpuinfo").read_text(),
            kernel=os.uname().release,
            boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        ),
    )


def set_arm(role, env0):
    target = ROOT / "reopened" / ({"P": "normal", "C": "defer"}[role])
    alias = RUSTUP / "toolchains/ohm"
    if alias.is_symlink():
        alias.unlink()
    alias.symlink_to(target, target_is_directory=True)
    env = dict(env0, LD_LIBRARY_PATH=str(target / "lib"))
    for tool in ("rustc", "cargo"):
        physical = Path(
            run(["rustup", "which", "--toolchain", "ohm", tool], env=env)
            .stdout.decode()
            .strip()
        )
        need(physical.samefile(target / "bin" / tool), "foreign " + tool)
    return env


def validate_sources(case):
    roots = [WS / (case["name"] + "-" + key) for key in ("A", "B")]
    for key, repo, t in zip(("A", "B"), roots, case["trees"]):
        need(
            [git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")]
            == [case[key], t]
            and not git(repo, "status", "--porcelain"),
            "changed Ruff checkout",
        )
    need(
        ("parent " + case["A"]) in git(roots[1], "cat-file", "-p", "HEAD").splitlines(),
        "not an actual direct Ruff child",
    )

    # Compare the actual trees from the two independent shallow checkouts.
    def tree(repo):
        return {
            line.split("\t", 1)[1]: line.split("\t", 1)[0]
            for line in git(repo, "ls-tree", "-r", "HEAD").splitlines()
        }

    a, b = map(tree, roots)
    actual = [
        ("M" if k in a and k in b else "A" if k in b else "D") + "\t" + k
        for k in sorted(a.keys() | b.keys())
        if a.get(k) != b.get(k)
    ]
    need(
        actual == case["changes"],
        "declared change does not equal both complete source trees",
    )
    SRC.mkdir()
    with subprocess.Popen(
        ["git", "-C", str(roots[0]), "archive", "HEAD"], stdout=subprocess.PIPE
    ) as arch:
        subprocess.run(["tar", "-xf", "-", "-C", SRC], stdin=arch.stdout, check=True)
        need(arch.wait() == 0, "git archive failed")
    return roots


def revision(case, roots, to_b):
    for row in case["changes"]:
        mode, name = row.split("\t")
        f = SRC / name
        need(mode in ("A", "M") and not f.is_symlink(), "unsafe diff")
        path = roots[1 if to_b else 0] / name
        if to_b:
            need(
                (
                    not f.exists()
                    if mode == "A"
                    else f.read_bytes() == (roots[0] / name).read_bytes()
                ),
                "incorrect Ruff preimage",
            )
        if not path.exists():
            need(mode == "A" and not to_b, "unexpected deletion")
            f.unlink(missing_ok=True)
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, f)
        if not to_b:
            os.utime(f, ns=(1650000000000000000, 1650000000000000000))
    need(
        (SRC / "Cargo.lock").read_bytes()
        == (roots[1 if to_b else 0] / "Cargo.lock").read_bytes(),
        "changed Cargo.lock",
    )


def graphs(case, role):
    result = {p: {} for p in case["crates"]}
    for f in (
        f
        for directory in ("target", "build")
        for f in (STATE / directory).rglob("ohm-check-dep-graph.bin")
    ):
        keys = [p for p in result if any(s.startswith(p + "-") for s in f.parts)]
        if not keys:
            continue
        need(len(keys) == 1, "ambiguous graph owner")
        data = f.read_bytes()
        end = len(data) - len(b"rust-end-file")
        version = int.from_bytes(data[4:6], "little")
        need(
            data[:4] == b"RSIC"
            and data.endswith(b"rust-end-file")
            and version == (10 if role == "P" else 11),
            (keys, role, "wrong check graph version"),
        )
        mark = data[end - 32 : end - 24]
        need(
            mark == b"OHMIDX01" if role == "P" else mark[2:] == b"OHMF11",
            "wrong tail marker",
        )
        result[keys[0]][hashlib.sha256(data).hexdigest()] = len(data)
    need(
        all(x for x in result.values()),
        (
            "missing graph",
            role,
            result,
            [str(f.relative_to(STATE)) for f in STATE.rglob("ohm-check-dep-graph.bin")][
                :32
            ],
        ),
    )
    return result


def cargo(case, role, env, out, tag, domain=None):
    cmd = [
        "cargo",
        "+ohm",
        "check",
        "-p",
        case["root"],
        "--lib",
        "--locked",
        "--offline",
        "-j2",
        "--message-format=json",
    ]
    if domain:
        r, count = window(out / (tag + "-clock"), cmd, env, SRC, domain)
    else:
        r, count = run(cmd, cwd=SRC, env=env, check=False), None
    dump_gz(out, tag + ".stdout.gz", r.stdout)
    dump_gz(out, tag + ".stderr.gz", r.stderr)
    need(
        r.returncode == 0 and (not domain or count is not None),
        ("failed ordinary check", role, tag, r.returncode, r.stderr[-1900:]),
    )
    rows = [json.loads(i) for i in r.stdout.splitlines()]
    need(rows[-1] == dict(reason="build-finished", success=True), "wrong check verdict")
    units = [m for m in rows if m["reason"] == "compiler-artifact"]
    need(
        not [
            m
            for m in rows
            if m["reason"] == "compiler-message" and m["message"]["level"] == "error"
        ],
        "unexpected rustc error",
    )
    libs = [
        Path(f)
        for m in units
        if m["target"]["name"] == "ruff_python_ast"
        for f in m["filenames"]
        if f.endswith(".rmeta")
    ]
    need(len(libs) == 1 and libs[0].is_file(), "missing AST metadata")
    return dict(
        guest_or_retired=count,
        dirty=sorted(m["target"]["name"] for m in units if not m["fresh"]),
        units=len(units),
        lib=libs[0],
        dirs=sorted(
            {
                str(Path(f).parent)
                for m in units
                for f in m["filenames"]
                if Path(f).suffix in (".so", ".rlib", ".rmeta")
            }
        ),
    )


def typecheck(case, env, out, tag, result, is_b):
    if case["name"] == "ast":
        probes = [
            (
                "width-" + str(w),
                "extern crate ruff_python_ast; const _: [(); "
                + str(w)
                + "] = [(); std::mem::size_of::<ruff_python_ast::Expr>()];",
                [] if w == (56 if is_b else 64) else ["E0308"],
            )
            for w in (56, 64)
        ]
    else:
        pre = "extern crate ruff_python_ast; use ruff_python_ast::token::TokenKind; const _: () = assert!("
        probes = [
            (
                "new-methods",
                pre + "TokenKind::Dot.is_dot() && TokenKind::Lbrace.is_lbrace());",
                [] if is_b else ["E0599", "E0599"],
            ),
            (
                "wrong-method",
                pre + "TokenKind::Lbrace.is_dot());",
                ["E0080"] if is_b else ["E0599"],
            ),
        ]
    verdicts = {}
    for name, source, expect in probes:
        file = WORK / "client.rs"
        file.write_text(source + "\n")
        r = run(
            [
                "rustc",
                "+ohm",
                "--crate-name",
                "wire_client",
                "--crate-type=lib",
                "--emit=metadata",
                "--error-format=json",
                "--extern",
                "ruff_python_ast=" + str(result["lib"]),
                *[arg for x in result["dirs"] for arg in ("-L", "dependency=" + x)],
                "-o",
                WORK / "client.rmeta",
                file,
            ],
            cwd=SRC,
            env=env,
            check=False,
        )
        dump_gz(out, tag + "-" + name + ".stderr.gz", r.stderr)
        codes = [
            m["code"]["code"]
            for m in map(json.loads, r.stderr.splitlines())
            if m.get("code")
        ]
        need(
            (r.returncode, codes) == (int(bool(expect)), expect),
            (tag, name, r.returncode, codes),
        )
        verdicts[name] = [r.returncode, codes]
    return verdicts


def copy_seed(seed):
    need(not STATE.exists() and seed.is_relative_to(WORK), "overlapping seed")
    run(["cp", "-a", "--reflink=auto", seed, STATE], timeout=240)


def clear_state():
    need(
        STATE.parent == WORK and not STATE.is_symlink() and STATE.is_dir(),
        "foreign disposable state",
    )
    shutil.rmtree(STATE)


def design(case, env0, domain):
    group = LOG / case["name"]
    group.mkdir()
    roots = validate_sources(case)
    expected = sorted(case["crates"])
    seeds = {}
    oldgraphs = {}
    for role in ("P", "C"):
        dest = group / ("seed-" + role)
        dest.mkdir()
        env = set_arm(role, env0)
        seed = WORK / (case["name"] + "-seed-" + role)
        seeds[role] = seed
        revision(case, roots, False)
        STATE.mkdir()
        base = cargo(case, role, env, dest, "A")
        need(set(expected) <= set(base["dirty"]), "incomplete cold A")
        v = typecheck(case, env, dest, "A", base, False)
        oldgraphs[role] = graphs(case, role)
        fresh = cargo(case, role, env, dest, "A-repeat")
        need(not fresh["dirty"], "A did not settle")
        json_save(
            dest / "seed.json",
            dict(
                typed=v,
                graphs=oldgraphs[role],
                units=base["units"],
                rmeta=sha(base["lib"]),
            ),
        )
        STATE.rename(seed)
    rows = []
    for pair in range(REG["pairs"]):
        for role in ("P", "C") if pair % 2 == 0 else ("C", "P"):
            dest = group / (str(pair) + "-" + role)
            dest.mkdir()
            env = set_arm(role, env0)
            revision(case, roots, False)
            copy_seed(seeds[role])
            fresh = cargo(case, role, env, dest, "A-restored")
            need(not fresh["dirty"], "the source tree or seed was not restored")
            revision(case, roots, True)
            before = time.monotonic_ns()
            b = cargo(case, role, env, dest, "B-edit", domain)
            stop = time.monotonic_ns()
            need(
                b["dirty"] == expected,
                (
                    "wrong edited compiler inventory",
                    case["name"],
                    role,
                    b["dirty"],
                    expected,
                ),
            )
            typed = typecheck(case, env, dest, "B", b, True)
            g = graphs(case, role)
            need(
                all(set(g[k]) - set(oldgraphs[role][k]) for k in expected),
                "post-edit check retained the old graph",
            )
            fresh = cargo(case, role, env, dest, "B-repeat")
            need(not fresh["dirty"], "unchanged B invoked a compiler")
            row = dict(
                pair=pair,
                role=role,
                count=b["guest_or_retired"],
                domain=domain,
                units=b["units"],
                dirty=b["dirty"],
                typed=typed,
                graphs=g,
                rmeta=sha(b["lib"]),
                elapsed_ns=stop - before,
            )
            json_save(dest / "row.json", row)
            rows.append(row)
            print(case["name"], pair, role, domain, row["count"], flush=True)
            clear_state()
    for role in ("P", "C"):
        dest = group / ("clean-B-" + role)
        dest.mkdir()
        env = set_arm(role, env0)
        STATE.mkdir()
        b = cargo(case, role, env, dest, "B-empty")
        need(set(expected) <= set(b["dirty"]), "empty B reused an artifact")
        v = typecheck(case, env, dest, "empty-B", b, True)
        need(
            all(x["typed"] == v for x in rows if x["role"] == role),
            "clean and incremental B disagree",
        )
        json_save(
            dest / "clean.json",
            dict(
                verdicts=v,
                graphs=graphs(case, role),
                units=b["units"],
                rmeta=sha(b["lib"]),
            ),
        )
        clear_state()
        shutil.rmtree(seeds[role])
    shutil.rmtree(SRC)
    paired = []
    for index in range(REG["pairs"]):
        pair = {r["role"]: r["count"] for r in rows if r["pair"] == index}
        need(set(pair) == {"P", "C"}, "partial pair")
        paired.append(1 - pair["C"] / pair["P"])
    rng = random.Random(2833528145)
    br = sorted(
        statistics.median(rng.choices(paired, k=len(paired))) for _ in range(20000)
    )
    above = sum(x > 0 for x in paired)
    n = len(paired)
    p = min(
        1, 2 * sum(math.comb(n, i) for i in range(min(above, n - above) + 1)) / 2**n
    )
    report = dict(
        domain=domain,
        rows=rows,
        paired=paired,
        median_reduction=statistics.median(paired),
        bootstrap95=[br[500], br[19499]],
        sign_p=p,
    )
    json_save(group / "result.json", report)
    return {k: v for k, v in report.items() if k != "rows"}


def main():
    need(
        os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm"
        and os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and os.environ["GITHUB_REF"]
        == "refs/heads/charlie/qa-indexed-check-whole-pmu-20261102"
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"],
        "unexpected nonrelease runner",
    )
    WORK.mkdir()
    need(
        git(WS / "qa", "rev-parse", "HEAD") == os.environ["GITHUB_SHA"]
        and not git(WS / "qa", "status", "--porcelain")
        and git(WS / "collector", "rev-parse", "HEAD") == REG["collector"],
        "unreviewed runner or meter",
    )
    cpus()
    (RUSTUP / "toolchains").mkdir(parents=True)
    (RUSTUP / "settings.toml").write_text('version = "12"\nprofile = "minimal"\n')
    PROXIES.mkdir()
    rustup = Path(shutil.which("rustup")).resolve(strict=True)
    for name in ("cargo", "rustc", "rustup"):
        (PROXIES / name).symlink_to(rustup)
    (WORK / "cargo-home").mkdir()
    (WORK / "temp").mkdir()
    env0 = dict(
        HOME=str(WORK / "home"),
        RUSTUP_HOME=str(RUSTUP),
        RUSTUP_AUTO_INSTALL="0",
        CARGO_HOME=str(WORK / "cargo-home"),
        CARGO_NET_OFFLINE="true",
        CARGO_CACHE_AUTO_CLEAN_FREQUENCY="never",
        CARGO_TARGET_DIR=str(STATE / "target"),
        CARGO_BUILD_BUILD_DIR=str(STATE / "build"),
        PATH=str(PROXIES) + ":/usr/bin:/bin",
        TMPDIR=str(WORK / "temp"),
        LC_ALL="C",
        CARGO_TERM_COLOR="never",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        SSL_CERT_FILE="/etc/ssl/certs/ca-certificates.crt",
    )
    dom = calibrate(set_arm("P", env0))
    json_save(LOG / "domain.json", dict(domain=dom, source=REG["reader"]))
    for case in REG["source"]:
        for version in ("A", "B"):
            src = WS / (case["name"] + "-" + version)
            env = set_arm("P", env0)
            env.pop("CARGO_NET_OFFLINE")
            env["CARGO_TARGET_DIR"] = str(WORK / "fetch-state/target")
            env["CARGO_BUILD_BUILD_DIR"] = str(WORK / "fetch-state/build")
            run(
                [
                    "cargo",
                    "+ohm",
                    "fetch",
                    "--locked",
                    "--target",
                    "x86_64-unknown-linux-gnu",
                ],
                cwd=src,
                env=env,
                timeout=600,
            )
    results = {case["name"]: design(case, env0, dom) for case in REG["source"]}
    json_save(
        LOG / "accepted.json",
        dict(
            qa=os.environ["GITHUB_SHA"],
            run=os.environ["GITHUB_RUN_ID"],
            domain=dom,
            compiler=[REG["compiler_parent"], REG["compiler_candidate"]],
            results=results,
        ),
    )
    print("Accepted ordinary command results", json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
