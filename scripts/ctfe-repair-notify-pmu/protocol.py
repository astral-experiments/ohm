"""Check the source-bound admission and report the prespecified per-boot repair contrasts."""

import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parent / "ctfe-repair-encode"
CONTACT_RUN = 41296516686
CONTACT_JOB = 124818400853
CONTACT_HEAD = "084db0cf9d1156c9644880fda30f320072734865"
CONTACT_RUNNER = "nsc-runner-5dstl8jniahdk"
ARMS = {"01": ("E", "O", "P", "B"), "02": ("B", "P", "O", "E")}
CAL = "2f413ca94b84af2dbd6d6231bcf8d860c97ebee8"
OBS = "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc"
GRAPH = "f5909e1cbd4832369f783bdbd733e54562bcce15e44592b8ec15793e9996c660"
CARGO = (
    "cargo",
    "+ohm",
    "build",
    "-p",
    "ruff",
    "--bin",
    "ruff",
    "--locked",
    "--offline",
    "-j4",
    "--message-format=json",
)
CLOCK_FIELDS = {
    "start",
    "stop",
    "user_us",
    "system_us",
    "instructions",
    "enabled",
    "running",
    "event_errno",
    "code",
}


def require(condition, problem):
    if not condition:
        raise ValueError(problem)


def digest(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def certificate(directory, media, observer_source, registry):
    """Only call from authenticated intake. Repeat every source/native/file check on the actual official ZIP."""
    sys.path.insert(0, str(FROZEN))
    import read_contact

    j = json.loads((directory / "jobs.json").read_bytes())["jobs"]
    a = json.loads((directory / "artifacts.json").read_bytes())["artifacts"]
    require(
        len(j) == len(a) == 1 and j[0]["id"] == CONTACT_JOB and j[0]["runner_name"] == CONTACT_RUNNER,
        "unregistered contact job",
    )
    result = read_contact.official(directory, media, CONTACT_RUN, CONTACT_HEAD, observer_source)
    raw = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
    proof = {
        "run": CONTACT_RUN,
        "head": CONTACT_HEAD,
        "job": CONTACT_JOB,
        "runner": CONTACT_RUNNER,
        "boot": result["boot"],
        "artifact": a[0]["id"],
        "bytes": media.stat().st_size,
        "sha256": digest(media),
        "independent_sha256": hashlib.sha256(raw).hexdigest(),
    }
    require(
        result["qualified"] is True
        and result["issues"] == []
        and result["score"] is None
        and result["unscored"] is True,
        "failed native contact",
    )
    admit(proof, registry)
    require(raw == (HERE / "source-contact.json").read_bytes(), "qualified original readback altered")
    return proof


def admit(proof, registry):
    """The registry is the reviewed local source file. An unfilled, refused, expired or different contact is ineligible."""
    fields = {
        "run",
        "head",
        "job",
        "runner",
        "boot",
        "artifact",
        "bytes",
        "sha256",
        "independent_sha256",
    }
    require(
        isinstance(proof, dict) and set(proof) == fields and proof == registry,
        "unsealed or different prerequisite",
    )
    require(
        (proof["run"], proof["head"], proof["job"], proof["runner"])
        == (CONTACT_RUN, CONTACT_HEAD, CONTACT_JOB, CONTACT_RUNNER),
        "foreign prerequisite",
    )
    require(
        valid_boot(proof["boot"])
        and all(
            isinstance(proof[k], str) and re.fullmatch(r"[0-9a-f]{64}", proof[k])
            for k in ("sha256", "independent_sha256")
        ),
        "missing original or readback digest",
    )
    require(
        all(type(proof[k]) is int and proof[k] > 0 for k in ("artifact", "bytes")),
        "missing original ID or bytes",
    )


def valid_boot(boot):
    return isinstance(boot, str) and re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", boot)


def measured(row):
    require(
        set(row) == CLOCK_FIELDS and all(type(v) is int for v in row.values()), "bad native counter ABI"
    )
    require(
        row["event_errno"] == row["code"] == 0
        and row["enabled"] == row["running"] > 0
        and row["instructions"] > 0
        and row["stop"] > row["start"] > 0
        and min(row["system_us"], row["user_us"]) >= 0
        and row["system_us"] + row["user_us"] > 0,
        "incomplete hardware duty or failed command",
    )
    return row["instructions"]


def ratio(n, d):
    return {"numerator": n, "denominator": d}


def contrasts(numbers):
    require(
        set(numbers) == set("EOPB") and all(type(n) is int and n > 0 for n in numbers.values()),
        "missing whole repair",
    )
    e, o, p, b = (numbers[k] for k in "EOPB")
    h, d, j = o - e, p - b, p - o
    return {
        "instructions": numbers,
        "signed": {
            "ordinary_candidate_minus_parent": h,
            "pass_minus_block": d,
            "pass_minus_ordinary_candidate": j,
            "ordinary_excess_minus_intervention": h - d,
        },
        "ratios": {
            "ordinary_excess_over_parent": ratio(h, e),
            "intervention_over_pass": ratio(d, p),
            "intervention_over_ordinary_candidate": ratio(d, o),
            "pass_effect_over_ordinary_candidate": ratio(j, o),
            "intervention_over_contemporaneous_excess": ratio(d, h) if h > 0 else None,
        },
        "criteria": {
            "ordinary_excess_positive": h > 0,
            "intervention_reduces_user_instructions": d > 0,
            "at_least_half_positive_excess": h > 0 and d > 0 and 2 * d >= h,
            "pass_within_2pct_of_ordinary_candidate": 100 * abs(j) <= 2 * o,
        },
    }


def paired(positions, registry, forbidden):
    """Inputs are produced by independent per-archive replay, never the worker's proposed ratios."""
    require(set(positions) == set(ARMS), "two complete independent positions required")
    boots = set(forbidden)
    runners = {CONTACT_RUNNER}
    results = {}
    runs = set()
    jobs = set()
    for pos, order in ARMS.items():
        row = positions[pos]
        admit(row["contact"], registry)
        boot, runner, job = row["boot"], row["runner"], row["job"]
        boots.add(row["contact"]["boot"])
        require(
            valid_boot(boot)
            and boot not in boots
            and isinstance(runner, str)
            and re.fullmatch(r"nsc-runner-[a-z0-9]+", runner)
            and runner not in runners,
            "unregistered or repeated native host",
        )
        require(
            row["position"] == pos and row["order"] == list(order) and set(row["repairs"]) == set(order),
            "missing arm or incorrect physical execution order",
        )
        require(
            type(job) is int
            and job > 0
            and job not in jobs
            and row["attempt"] == 1
            and type(row["run"]) is int
            and row["run"] > 0
            and row["run"] != CONTACT_RUN,
            "incorrect hardware-run enrollment",
        )
        require(
            row["complete"] is True
            and not row["issues"]
            and row["calibration"] is True
            and row["products"] is True
            and row["publication"] is True
            and row["separate_native_role"] == ("E" if pos == "01" else "O"),
            "unqualified physical command, product, allocation or calibration",
        )
        last = 0
        nums = {}
        for mode in order:
            clock = row["repairs"][mode]
            nums[mode] = measured(clock)
            require(clock["start"] > last, "clock windows overlap or actual treatment order changed")
            last = clock["stop"]
        results[pos] = {
            "boot": boot,
            "runner": runner,
            "job": job,
            "order": list(order),
            **contrasts(nums),
        }
        boots.add(boot)
        runners.add(runner)
        jobs.add(job)
        runs.add(row["run"])
    require(len(runs) == 1, "two different studies")
    return {
        "run": runs.pop(),
        "boot_results": results,
        "both_hosts_meet_all_diagnostic_criteria": all(
            all(r["criteria"].values()) for r in results.values()
        ),
        "measurement": "inherited Cargo-tree user instructions through Cargo return",
        "intervention": "allow vs deny the first packed dep-graph create for 14 selected fresh owners",
        "supervisor_cpu_included": False,
        "kernel_cpu_included": False,
    }


def launches(mode, root, where, sdk):
    """Stable CLI for each treatment. The optional listener is always outside the counted Cargo tree."""
    require(
        mode in ARMS["01"]
        and root.is_absolute()
        and where == root / "logs" / ("return-" + mode) / "repair",
        "unexpected launch path or mode",
    )
    inner = [str(root / "logs/observers/plain"), str(where / "clock.json"), *CARGO]
    if mode in ("E", "O"):
        return inner
    calls = where / "calls"
    return [
        str(root / "logs/tools/table-notify"),
        str(calls),
        str(sdk),
        str(calls / "notify.status"),
        "--",
        *inner,
    ]


def completion(raw):
    """Use chronology of kernel EXIT and terminal waits, after the complete enrolled decoder verified the ledger."""
    lines = [l.split(b"\t") for l in raw.splitlines()]
    # The observer’s root execs cargo/rustup and then the enrolled Cargo in the same generation.
    cargo = [
        int(row[2])
        for row in lines
        if row[0] == b"E" and bytes.fromhex(row[8].decode()).endswith(b"/bin/cargo")
    ]
    require(cargo and set(cargo) == {1}, "cannot identify actual direct Cargo generation")
    tgid = {}
    done = {}
    reaped = {}
    for i, r in enumerate(lines):
        if r[0] == b"R":
            tgid[int(r[1])] = int(r[2])
        elif r[0] == b"B":
            tgid[int(r[1])] = int(r[3])
        elif r[0] == b"X":
            done[int(r[1])] = i
        elif r[0] == b"T":
            reaped[int(r[1])] = i
    require(set(tgid) == set(done) == set(reaped) and 1 in tgid, "incomplete positive exit population")
    later = [g for g, t in tgid.items() if t != tgid[1] and done[g] >= reaped[1]]
    require(not later, "a non-Cargo task was still before its EXIT at the Cargo terminal transition")
    return dict(
        cargo_generation=1,
        closed=len(tgid),
        noncargo_before_cargo_reap=sum(t != tgid[1] for t in tgid.values()),
    )
