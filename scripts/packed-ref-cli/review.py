"""Independently reopen the complete original full Ruff packed-ref contact."""

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from fractions import Fraction
from pathlib import Path, PurePath
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "ctfe-crossover-pilot"
sys.path[:0] = [str(HERE), str(BASE)]
import contact_review as prior
import ctfe_pilot_registration as hist
import endpoints
import git_layout
import packed_donor
import packed_sdk as sdk
import packed_watches
import qualification
import packed_confirmation as six
import reopen as n

BRANCH = "charlie/qa-ruff-sorted-packed-refs-full-20261101"
JOB = "GNU sorted packed Ruff CLI X-B contact"
ARTIFACT = "gnu-sorted-packed-ruff-x-b-contact"
SCHEDULE = (
    ("clean", "reference", n.REFS),
    ("structural", "return", n.PHASES),
    ("structural", "dirty", n.PHASES[:5]),
    ("measured", "return", n.PHASES),
)
get = n.dataset
need = sdk.need


def official_contact(directory, archive, head):
    """Replay the exact, excluded one-host control only when explicitly requested."""
    need(head == six.CONTACT_HEAD, "wrong historical rehearsal head")
    r, jobs, assets = [
        sdk.read(directory / (k + ".json")) for k in ("run", "jobs", "artifacts")
    ]
    need(
        (
            r["run_attempt"],
            r["head_sha"],
            r["head_branch"],
            r["event"],
            r["path"],
            r["status"],
            r["conclusion"],
        )
        == (
            1,
            head,
            BRANCH,
            "workflow_dispatch",
            ".github/workflows/ci.yml",
            "completed",
            "success",
        )
        and r["repository"]["full_name"]
        == r["head_repository"]["full_name"]
        == "astral-experiments/ohm",
        "wrong official attempt",
    )
    need(
        jobs["total_count"]
        == len(jobs["jobs"])
        == assets["total_count"]
        == len(assets["artifacts"])
        == 1,
        "extra or missing worker/original",
    )
    j = jobs["jobs"][0]
    a = assets["artifacts"][0]
    o = a["workflow_run"]
    need(
        (
            j["name"],
            j["run_id"],
            j["run_attempt"],
            j["head_branch"],
            j["head_sha"],
            j["status"],
            j["conclusion"],
            j["labels"],
        )
        == (
            JOB,
            r["id"],
            1,
            BRANCH,
            head,
            "completed",
            "success",
            ["namespace-profile-ubuntu-24-04-16"],
        )
        and j["runner_name"]
        and j["runner_id"] > 0
        and all(
            s["status"] == "completed" and s["conclusion"] == "success"
            for s in j["steps"]
        )
        and {
            "Verify the packed contact source",
            "Install the source-qualified D and Q SDKs",
            "Run the ordinary packed Ruff histories",
        }
        <= {s["name"] for s in j["steps"]},
        "wrong native job",
    )
    need(
        a["name"] == ARTIFACT
        and not a["expired"]
        and (o["id"], o["head_sha"], o["head_branch"]) == (r["id"], head, BRANCH)
        and o["repository_id"] == o["head_repository_id"] == r["repository"]["id"]
        and archive.stat().st_size == a["size_in_bytes"]
        and "sha256:" + hist.sha(archive) == a["digest"],
        "wrong full original ZIP",
    )
    need(
        r["id"] == six.CONTACT and a["digest"] == "sha256:" + six.CONTACT_ORIGINAL,
        "other historical original",
    )
    return dict(
        run=r["id"],
        head=head,
        attempt=1,
        job=j["id"],
        runner=j["runner_name"],
        runner_id=j["runner_id"],
        artifact=a["id"],
        bytes=a["size_in_bytes"],
        sha256=a["digest"][7:],
    )


def concurrent_hosts(excluded, current, pos, path, trusted_sha):
    raw = path.read_bytes()
    need(
        len(raw) <= 65536
        and re.fullmatch(r"[0-9a-f]{64}", trusted_sha)
        and n.digest(raw)
        == trusted_sha
        == excluded["concurrent"]["identity_only_sha256"],
        "different independent identity receipt",
    )
    cohort = json.loads(raw)
    spec = excluded["concurrent"]
    names = {f"{i:02d}" for i in range(1, 7)}
    need(
        cohort["admitted"] is True
        and cohort["outcomes_opened"] == 0
        and not cohort["missing"]
        and cohort["reason"] is None
        and (cohort["run"], cohort["head"]) == (spec["run"], spec["head"])
        and set(cohort["hosts"]) == names,
        "incomplete independent enrollment",
    )
    hosts = cohort["hosts"]
    for field, new in (
        ("boot", pos["boot"]),
        ("runner", current["runner"]),
        ("runner_id", current["runner_id"]),
        ("job", current["job"]),
    ):
        previous = {r[field] for r in hosts.values()}
        need(
            len(previous) == 6 and all(previous) and new not in previous,
            "concurrent " + field + " collision",
        )
    need(
        current["job"] not in excluded["jobs"]
        and {v["job"] for v in hosts.values()} == set(spec["job_ids"])
        and all(
            (v["run"], v["head"], v["position"]) == (spec["run"], spec["head"], k)
            for k, v in hosts.items()
        ),
        "substituted concurrent slot",
    )
    return {"run": spec["run"], "hosts": 6, "sha256": trusted_sha}


def execute(z, records):
    cases = n.semantic_oracle.cases
    closed = {}
    with tempfile.TemporaryDirectory(prefix="packed-cli-reader-") as temp:
        cwd = Path(temp)
        for (kind, sha, edited), (size, stdout) in records.items():
            with (
                z.open("native-bodies/" + sha + ".zst") as src,
                os.fdopen(
                    os.memfd_create("verified-packed-program", os.MFD_ALLOW_SEALING),
                    "w+b",
                ) as f,
            ):
                child = subprocess.Popen(
                    ["zstd", "-dq", "--stdout"], stdin=subprocess.PIPE, stdout=f
                )
                with child.stdin as pipe:
                    shutil.copyfileobj(src, pipe, 1 << 20)
                need(
                    child.wait() == 0 and f.tell() == size,
                    "invalid complete native program",
                )
                f.seek(0)
                need(
                    hashlib.file_digest(f, "sha256").hexdigest() == sha,
                    "native program SHA mismatch",
                )
                # Execute the sealed original with its own observed ELF64 PT_INTERP (no on-disk image).
                f.seek(0)
                header = struct.unpack("<16sHHIQQQIHHHHHH", f.read(64))
                need(
                    header[0][:7] == b"\x7fELF\x02\x01\x01"
                    and header[2] == 62
                    and header[9] == 56,
                    "unexpected native ABI",
                )
                f.seek(header[5])
                ph = list(struct.iter_unpack("<IIQQQQQQ", f.read(56 * header[10])))
                (interp,) = [row for row in ph if row[0] == 3]
                f.seek(interp[2])
                need(
                    f.read(interp[5]) == b"/lib64/ld-linux-x86-64.so.2\x00",
                    "foreign archived PT_INTERP",
                )
                os.fchmod(f.fileno(), 0o500)
                fcntl.fcntl(f, getattr(fcntl, "F_ADD_SEALS", 1033), 15)

                def run(args, data=b""):
                    return subprocess.run(
                        [
                            "/lib64/ld-linux-x86-64.so.2",
                            "/proc/self/fd/" + str(f.fileno()),
                            *args,
                        ],
                        pass_fds=(f.fileno(),),
                        input=data,
                        cwd=cwd,
                        env={"HOME": temp, "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
                        capture_output=True,
                        timeout=30,
                    )

                if kind == "reader":
                    p = run([])
                    need(
                        p.returncode == 0 and not p.stderr and p.stdout == stdout,
                        "reexecuted ABI reader differs",
                    )
                    closed[str((kind, sha, edited))] = p.stdout.decode().strip()
                else:
                    results = {}
                    for name in cases.CASES:
                        p = run(cases.argv(name), cases.SOURCE)
                        cases.verdict(
                            name, edited, p.returncode, p.stdout, p.stderr, cwd
                        )
                        # The checked output contains the reviewer's temporary cwd. Retain its verified basename.
                        normalized = [
                            dict(row, filename=Path(row["filename"]).name)
                            for row in json.loads(p.stdout)
                        ]
                        results[name] = [p.returncode, normalized]
                    closed[str((kind, sha, edited))] = results
    return closed


def stock_schedule(read):
    """Rebuild this host's successful stock link and worker partition from original bytes."""
    host = json.loads(read("host.json"))
    ident = host["identities"]["wild"]
    root = host["out"] + "/group-v2"
    args = [host["wild"], host["tools"] + "/start.o", "-o", root + "/linked.elf"]
    raw = read("wild.tsv")
    closed = n.kernel.parse(raw, expected_code=0, expected_schema=3)
    (event,) = closed["execs"]
    need(
        json.loads(read("wild.command.json"))["argv"]
        == [host["tools"] + "/observe", root + "/wild.tsv", "--", *args]
        and json.loads(read("wild.terminal.json")) == {"status": 0}
        and not read("wild.stdout")
        and not read("wild.stderr")
        and event["argv"] == args
        and event["exe"] == ident["resolved"]
        and all(
            event["image"][key] == ident[key]
            for key in ("dev", "ino", "sha256", "mode", "size", "mtime", "ctime")
        ),
        "different physical stock link or result",
    )
    link = dict(
        event=event["ordinal"],
        lifetime=event["lifetime"],
        pid=event["pid"],
        argv=args,
        output=args[-1],
        rustc_event=None,
        rustc_crate=None,
    )
    (proof,) = prior.wild_fork.finish(raw, closed, [link])
    rows = [line.decode("ascii").split("\t") for line in raw.splitlines()]
    (owner,) = (r for r in rows if r[0] == "G")
    owner_id = str(proof["helper"])
    need(
        closed["lifetimes"] == closed["reaped"] == 4
        and len(proof["workers"]) == 2
        and owner[1:] == [owner_id, str(proof["helper_pid"]), "0"]
        and proof["closure"] == "parked",
        "different native helper group",
    )
    early = []
    for worker in proof["workers"]:
        (born,) = (r for r in rows if r[0] == "N" and r[4] == str(worker))
        need(born[1:4] == [owner_id, owner[2], "3"], "different worker ancestry")
        terminal = ["X", str(worker), born[5], "0"]
        if worker not in proof["parked"]:
            need(
                rows.index(terminal) < rows.index(owner),
                "live unparked worker at exit_group",
            )
            early.append(worker)
    image_sha = n.digest(read("linked.elf"))
    need(
        image_sha == "8999e7633aff70a36e79bbc057c5102b9c36b0f2ba699fd59bc3f8714a9b4bec"
        and json.loads(read("run-linked.command.json"))["argv"] == [args[-1]]
        and json.loads(read("run-linked.terminal.json")) == {"status": 37}
        and not read("run-linked.stdout")
        and not read("run-linked.stderr"),
        "different native linked program or verdict",
    )
    return dict(
        raw_sha256=closed["sha256"],
        linked_elf_sha256=image_sha,
        exit=37,
        schedule=dict(
            helper=proof["helper"],
            workers=proof["workers"],
            parked=proof["parked"],
            exited_before_group=early,
        ),
    )


def ingress(z, meta, kernel, calibrator, observers, rehearsal):
    names = z.namelist()
    need(
        len(names) == len(set(names))
        and not any(
            PurePath(s).is_absolute() or ".." in PurePath(s).parts for s in names
        )
        and "failure.txt" not in names,
        "invalid or refused original",
    )
    pos = get(z, "position.json")
    boot = pos["boot"]
    if rehearsal:
        need(
            (meta["run"], meta["head"], meta["sha256"])
            == (six.CONTACT, six.CONTACT_HEAD, six.CONTACT_ORIGINAL),
            "wrong excluded rehearsal",
        )
        mode, slot, order, plan = (
            "sorted-packed-ref-contact",
            "01",
            sdk.ARMS,
            hist.sha(HERE / "PLAN.md"),
        )
    else:
        need(
            n.digest(z.read("position.json")) == meta["position_sha256"],
            "changed identity-only position",
        )
        six.position_record(pos, meta)
        mode, slot, order, plan = (
            six.MODE,
            meta["position"],
            six.order(meta["position"]),
            six.PLAN,
        )
    need(
        (
            pos["mode"],
            pos["position"],
            pos["run"],
            pos["runner"],
            pos["order"],
            pos["command"],
            pos["head"],
        )
        == (
            mode,
            slot,
            meta["run"],
            meta["runner"],
            list(order),
            n.CARGO,
            meta["head"],
        )
        and pos["plan"] == plan == n.digest(z.read("PLAN.md"))
        and pos["registered_plan"]
        == hist.sha(HERE / "inputs/registered-plan.md")
        == "c10abb820ce6b6da3ab3b2f88d858ee7574ef73d989e55d4a96307aa5c8c26ed"
        and pos["prerequisites"] == qualification.prereqs()
        and pos["packed_source"]
        == [sdk.SOURCE_RUN, sdk.SOURCE_JOB, sdk.compact(sdk.enrolled())],
        "wrong registered endpoint/SDK",
    )
    ex = sdk.read(HERE / "excluded-hosts.json")
    need(
        boot not in ex["boots"]
        and meta["runner"] not in ex["runners"]
        and meta["runner_id"] not in ex["runner_ids"],
        "reused physical worker",
    )
    minimum = prior.host_guards(z, pos)
    observer = n.kernel_binding(z, boot, "contact", kernel, None)
    prefix = "kernel-qualification/fixtures/group-v2/"
    stock = stock_schedule(lambda name: z.read(prefix + name))
    saved = get(z, prefix + "qualified.json")["native"]["wild"]
    need(
        saved["raw_sha256"] == stock["raw_sha256"]
        and saved["worker_schedule"] == stock["schedule"],
        "fixture receipt differs from kernel worker exits",
    )
    observer["stock_wild_schedule"] = stock
    n.replay_controls.PACKAGING, n.replay_controls.OBSERVER = calibrator, observers
    meter = get(z, "meter-ready.json")
    cal = n.replay_controls.calibration(z, boot)
    cost = n.hardware.verify(z, cal, meter)
    need(
        meter["boot"] == boot
        and meter["observer"] == n.replay_controls.OBS
        and meter["calibrator"] == n.replay_controls.CAL
        and pos["host"]["affinity"] == meter["affinity"] == cal["affinity"],
        "wrong calibration/affinity",
    )
    layout = get(z, "git-layout.json")
    need(
        (layout["archive"], layout["carrier"], layout["refs"], layout["commits"])
        == (git_layout.ARCHIVE, git_layout.CARRIER, 1291, 1286),
        "different public ref corpus",
    )
    git_layout.verify_snapshot(layout["initial"], git_layout.Y, git_layout.B)
    records = sdk.verify_pair({a: get(z, "sdk/" + a + ".json") for a in sdk.SOURCES})
    slot = z.read("sdk/q-source-slot.json")
    need(
        n.digest(slot)
        == "ac8449959882c10a84d36898db68a738aae51b7766b58643d4dea66ba2692cd0"
        and sdk.content(sdk.qualified_candidate(json.loads(slot))["files"])
        == sdk.content(records["Q"]["files"]),
        "candidate source artifact slot or restored Q roster differs",
    )
    physical = get(z, "sdk/q-native-source.json")
    need(
        get(z, "sdk/q-official.json") == sdk.enrolled()
        and get(z, "sdk/q-published-source.json")
        == sdk.enrolled()["source"] | {"physical_installation_reopened": True}
        and (
            physical["old"],
            physical["new"],
            physical["tree"],
            physical["qa"],
            physical["run"],
            physical["overlay"],
        )
        == (
            sdk.D,
            sdk.Q,
            sdk.Q_TREE,
            sdk.SOURCE_QA,
            str(sdk.SOURCE_RUN),
            sdk.manifests()["Q"],
        )
        and [physical[key + "_driver"] for key in ("old", "new")]
        == [sdk.content(records[r]["files"])[sdk.DRIVER] for r in ("D", "Q")],
        "unbound source-generated driver/original native qualification",
    )
    return pos, minimum, observer, cost, records


def verify(
    meta,
    archive,
    kernel,
    calibrator,
    observers,
    concurrent_path,
    concurrent_sha,
    *,
    rehearsal=False,
):
    policy = SimpleNamespace(
        git_layout=git_layout,
        reopen_script=packed_watches.reopen_script,
        SOURCES=sdk.SOURCES,
        TREES=sdk.TREES,
    )
    with zipfile.ZipFile(archive) as z:
        # Enter with identity alone, before reading an original PMU or a checked native endpoint.
        position = get(z, "position.json")
        cross = concurrent_hosts(
            sdk.read(HERE / "excluded-hosts.json"),
            meta,
            position,
            concurrent_path,
            concurrent_sha,
        )
        pos, minimum, kernel_binding, cost, records = ingress(
            z, meta, kernel, calibrator, observers, rehearsal
        )
        names = set(z.namelist())
        rows = {a: {} for a in sdk.ARMS}
        bodies = {}
        programs = {}
        clocks = []
        selections = {a: {} for a in sdk.ARMS}
        base_env = None
        allowed = {
            s: set()
            for s in (
                "visit.json",
                "clock.json",
                "kernel.tsv.gz",
                "donor-selected.json",
                "ruff-build-script.json",
                "live-drivers.json.gz",
                "donor-register.json",
            )
        }
        for lane, line, phases in SCHEDULE:
            for arm in pos["order"]:
                top = f"{lane}-{line}-{arm}"
                cert, root = n.active(
                    z, top, arm, records[arm[0]]["files"], manifests=sdk.manifests()
                )
                need(
                    (base_env is None or base_env == cert["env"])
                    and kernel_binding["observer"]
                    == str(root / "kernel-qualification/tools/observe"),
                    "changed command environment",
                )
                base_env = cert["env"]
                for phase in phases:
                    key = f"{lane}/{line}/{phase}"
                    prefix = top + "/" + phase
                    v = n.read_phase(
                        z,
                        prefix,
                        phase,
                        lane,
                        line,
                        arm,
                        cert,
                        root,
                        bodies,
                        packed=policy,
                    )
                    rows[arm][key] = v
                    for name in ("visit.json", "ruff-build-script.json"):
                        allowed[name].add(prefix + "/" + name)
                    if lane == "measured":
                        allowed["clock.json"].add(prefix + "/clock.json")
                        clocks.append((v["start"], v["stop"]))
                    if lane == "structural" and phase in n.TRACED[line]:
                        allowed["kernel.tsv.gz"].add(prefix + "/kernel.tsv.gz")
                        if phase == "X-B":
                            stream = get(z, prefix + "/native-execs.json.gz")
                            cli = [
                                r
                                for r in stream["wild_processes"]
                                if r["rustc_crate"] == "ruff"
                                and re.fullmatch(
                                    r"ruff(-[0-9a-f]{16})?", PurePath(r["output"]).name
                                )
                            ]
                            need(
                                len(cli) == 1,
                                "actual stock Wild did not link the selected CLI",
                            )
                    if v["status"] == 0:
                        changed = (
                            phase == "clean-semantic"
                            or line == "dirty"
                            and phase == "X-B"
                        )
                        for kind in ("cli", "reader"):
                            sha = v[kind]
                            value = (
                                v["native"][kind]["size"],
                                b""
                                if kind == "cli"
                                else gzip.decompress(
                                    z.read(prefix + "/reader-run.stdout.gz")
                                ),
                            )
                            key = (kind, sha, changed if kind == "cli" else None)
                            need(
                                key not in programs or programs[key] == value,
                                "same native program reported conflicting ABI",
                            )
                            programs[key] = value
                if lane == "structural":
                    for name in (
                        "donor-selected.json",
                        "donor-register.json",
                        "live-drivers.json.gz",
                    ):
                        allowed[name].add(top + "/X-B/" + name)
                    selections[arm][line] = packed_donor.replay(
                        z, top, arm, records[arm[0]], root / "work", get
                    )
        for name, registered in allowed.items():
            need(
                {m for m in names if m.endswith("/" + name)} == registered,
                "lost or unregistered " + name,
            )
        need(
            len(clocks) == 14 and all(a[1] < b[0] for a, b in zip(clocks, clocks[1:])),
            "missing, overlapping or reordered PMUs",
        )
        need(
            not n.compare(rows, sdk.ARMS) and get(z, "native-issues.json") == [],
            "warm or across-role clean bytes differ",
        )
        primary = {a: rows[a]["measured/return/X-B"]["instructions"] for a in sdk.ARMS}
        seven = {
            a: sum(rows[a]["measured/return/" + p]["instructions"] for p in n.PHASES)
            for a in sdk.ARMS
        }
        summaries = {
            arm: endpoints.count(
                {p: get(z, f"measured-return-{arm}/{p}/clock.json") for p in n.PHASES}
            )
            for arm in sdk.ARMS
        }
        original_clocks = {arm: {} for arm in sdk.ARMS}
        for arm in sdk.ARMS:
            for phase in n.PHASES:
                native_clock = get(z, f"measured-return-{arm}/{phase}/clock.json")
                original_clocks[arm][phase] = native_clock
                need(
                    native_clock["running"] == native_clock["enabled"] > 0,
                    "multiplexed literal hardware observation",
                )
            for p, clock in summaries[arm]["phases"].items():
                visit = rows[arm]["measured/return/" + p]
                need(
                    all(
                        clock[k] == visit[k]
                        for k in ("instructions", "start", "stop", "status")
                    ),
                    "raw calibrated PMU differs",
                )
            need(
                summaries[arm]["whole7"]["instructions"] == seven[arm],
                "unequal total of seven original commands",
            )
        complete = dict(
            qualified=True,
            position=pos,
            visits=sum(len(r) for r in rows.values()),
            metered=14,
            source=[sdk.D, sdk.Q],
            measured=summaries,
            primary=primary,
            all_seven=seven,
        )
        need(
            get(z, "complete.json") == complete,
            "reported terminal or denominator differs",
        )
        six.check_clocks(original_clocks, summaries)
        histories = [] if rehearsal else get(z, "history-intervals.json")
        if not rehearsal:
            six.history_order(pos["position"], histories, summaries)
        traced = len(allowed["kernel.tsv.gz"])
        need(traced == 16, "incomplete per-phase physical coverage")
        native = execute(z, programs)
        keep = (
            "status",
            "allocated",
            "table_bytes",
            "retained_sessions",
            "graph",
            "dirty",
            "cli",
            "reader",
            "instructions",
            "compilers",
            "full_units",
            "link_units",
            "links",
        )
        compact = {
            a: {k: {f: v[f] for f in keep if f in v} for k, v in visits.items()}
            for a, visits in rows.items()
        }
        ratio = Fraction(primary["Don"], primary["Qon"])
        return dict(
            qualified=True,
            official=meta,
            boot=pos["boot"],
            resource=minimum,
            stock_wild_fixture=kernel_binding["stock_wild_schedule"],
            source=sdk.enrolled(),
            counter=cost,
            primary=primary,
            ratio=[ratio.numerator, ratio.denominator],
            all_seven=seven,
            measured=summaries,
            concurrent=cross,
            above_two=ratio > 2,
            visits=complete["visits"],
            selection=selections,
            rows=compact,
            native_replay=native,
            checked_native_bodies=len(bodies),
            storage="quiescent distinct allocated bytes after each command",
            scored_samples=0,  # The cohort decision is made only after all six actual replays.
            raw_clocks=original_clocks,
            histories=histories,
            metered=len(clocks),
            traced=traced,
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for arg in ("zip", "official", "kernel", "calibrator", "observers"):
        ap.add_argument("--" + arg, type=Path, required=True)
    ap.add_argument("--concurrent-admission", type=Path, required=True)
    ap.add_argument("--concurrent-sha256", required=True)
    ap.add_argument("--head", required=True)
    choice = ap.add_mutually_exclusive_group(required=True)
    choice.add_argument("--position", choices=six.POSITIONS)
    choice.add_argument("--rehearsal-contact", action="store_true")
    a = ap.parse_args()
    need(
        subprocess.check_output(
            ["git", "-C", HERE, "rev-parse", "HEAD"], text=True
        ).strip()
        == a.head,
        "different reviewer",
    )
    print(
        json.dumps(
            verify(
                (
                    official_contact(a.official, a.zip, six.CONTACT_HEAD)
                    if a.rehearsal_contact
                    else six.official(a.official, a.zip, a.head, a.position)
                ),
                a.zip,
                a.kernel,
                a.calibrator,
                a.observers,
                a.concurrent_admission,
                a.concurrent_sha256,
                rehearsal=a.rehearsal_contact,
            ),
            sort_keys=True,
        )
    )
