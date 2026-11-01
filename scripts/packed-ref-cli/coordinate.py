"""Bind six original jobs, then reopen their complete identities before any outcome on the coordinator."""

import argparse
import base64
import binascii
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import packed_confirmation as six
import packed_sdk as sdk

OSS = Path.home() / "code/oss"
DATA = Path.home() / ".cache"
PREVIOUS = DATA / "ohm-donor-integration-xb-six-20261101"
EXCLUDED_SIX = PREVIOUS / "41321959762/boot-admission.json"
EXCLUDED_SHA = "eb7aa0c79de4d207bd6ceb334b275d069bc3a435832d5ce0a558c87efee39c86"
MEDIA_SOURCE = "67310ecf410e38140a96b2cdff390b625f1e52077c2770934c7e86298b5a514e"
CWD = HERE.parents[1]
REPO = "astral-experiments/ohm"
FLOOR = 512 << 20
need, load = sdk.need, sdk.read


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def prior_media(root):
    path = PREVIOUS / "intake.py"
    need(sha(path.read_bytes()) == MEDIA_SOURCE, "changed six-host media receiver")
    checkout = OSS / "ohm-package-qa-donor-integration-xb-six-20261101"
    need(
        subprocess.check_output(
            ["git", "-C", checkout, "rev-parse", "HEAD"], text=True
        ).strip()
        == "80fd9f30b0a75f0421389ed5a192d3e2b6789bbe"
        and not subprocess.check_output(
            ["git", "--no-optional-locks", "-C", checkout, "status", "--porcelain"]
        ),
        "changed inherited media source checkout",
    )
    spec = importlib.util.spec_from_file_location("registered_six_media", path)
    media = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(media)
    media.ROOT, media.Q = root, CWD
    return media


def write(path, data):
    if path.exists():
        need(path.read_bytes() == data, "different immutable receipt " + str(path))
        return
    while shutil.disk_usage(path.parent).free <= FLOOR + len(data) + 65536:
        print(
            "Waiting for enough HOME space to retain this receipt without crossing 512 MiB",
            path.name,
            flush=True,
        )
        time.sleep(60)
    with path.open("xb") as f:
        f.write(data)
    path.chmod(0o444)


def save(path, record):
    write(path, (json.dumps(record, sort_keys=True, indent=2) + "\n").encode())


def wait_floor(media, extra=0):
    while True:
        try:
            media.floor(extra)
            return
        except RuntimeError as e:
            if "coordinator floor" not in str(e):
                raise
            print("Waiting for registered real coordinator capacity", e, flush=True)
            time.sleep(60)


def metadata(media, rid, head):
    run = media.ax(f"runs/{rid}")
    need(
        (
            run["id"],
            run["event"],
            run["run_attempt"],
            run["head_branch"],
            run["head_sha"],
            run["path"],
        )
        == (rid, "workflow_dispatch", 1, six.BRANCH, head, ".github/workflows/ci.yml")
        and run["repository"]["full_name"]
        == run["head_repository"]["full_name"]
        == REPO,
        "wrong registered run",
    )
    return (
        run,
        media.ax(f"runs/{rid}/attempts/1/jobs?per_page=100"),
        media.ax(f"runs/{rid}/artifacts?per_page=100"),
    )


def bind(media, folder, rid, head):
    for _ in range(150):
        run, jobs, assets = metadata(media, rid, head)
        need(
            assets["total_count"] == 0
            and jobs["total_count"] <= 6
            and all(j["conclusion"] is None for j in jobs["jobs"]),
            "late or substituted enrollment",
        )
        if jobs["total_count"] == 6:
            break
        time.sleep(3)
    else:
        raise ValueError("original six job ids did not appear")
    prior = six.frozen()
    positions = {}
    for slot in six.POSITIONS:
        (j,) = [r for r in jobs["jobs"] if r["name"] == six.LABEL + slot]
        need(
            (j["run_id"], j["head_sha"], j["run_attempt"], j["labels"])
            == (rid, head, 1, ["namespace-profile-ubuntu-24-04-16"])
            and j["id"] not in prior["jobs"],
            "other executor",
        )
        positions[slot] = {"job": j["id"], "order": list(six.order(slot))}
    need(len({v["job"] for v in positions.values()}) == 6, "duplicate enrolled job")
    for name, obj in (
        ("initial-run", run),
        ("initial-jobs", jobs),
        ("initial-artifacts", assets),
    ):
        save(folder / (name + ".json"), obj)
    rec = dict(
        utc=media.utc(),
        run=rid,
        head=head,
        attempt=1,
        assets=0,
        positions=positions,
        outcome_members_opened=0,
    )
    save(folder / "pre-outcome.json", rec)
    print("Bound all six original jobs, none completed", positions, flush=True)


def transfer(media, folder, asset, run, head, phase, slot, visit):
    location = folder / "authenticated" / slot / phase
    while True:
        wait_floor(media, asset["size_in_bytes"] + (600 << 20))
        try:
            with media.media(asset, run, head, location) as raw:
                return visit(raw)
        except RuntimeError as e:
            if "coordinator floor" not in str(e):
                raise
        except IOError:
            partial = list(location.glob("incomplete-*.json"))
            if not partial or len(partial) > 2:
                raise
            print(
                "Retrying transport of the same official original",
                slot,
                phase,
                len(partial),
                flush=True,
            )
            time.sleep(15)


def position(raw, slot, job, asset):
    with zipfile.ZipFile(raw) as z:
        names = z.namelist()
        need(
            len(names) == len(set(names))
            and all(
                not Path(n).is_absolute() and ".." not in Path(n).parts for n in names
            ),
            "ambiguous ZIP paths",
        )
        need(z.getinfo("position.json").file_size <= 32768, "oversized position")
        body = z.read("position.json")
        actual = json.loads(body)
    row = dict(
        position=slot,
        run=job["run_id"],
        head=job["head_sha"],
        order=list(six.order(slot)),
        job=job["id"],
        runner=job["runner_name"],
        runner_id=job["runner_id"],
        boot=actual["boot"],
        artifact=asset["id"],
        sha256=asset["digest"].removeprefix("sha256:"),
        bytes=asset["size_in_bytes"],
        position_sha256=sha(body),
    )
    six.position_record(actual, row)
    return {"meta": row, "position": actual, "outcome_members_opened": 0}


def physical_sources(directory):
    """Restore the same three source-only shallow checkouts used for the contact reader."""
    refs = {
        "kernel": (
            "fb816a6c4165b01775fa2b7b643668abc4defd85",
            ("scripts/branch-return-execstop", "scripts/branch-return-pmu"),
        ),
        "calibrator": (
            "2f413ca94b84af2dbd6d6231bcf8d860c97ebee8",
            ("scripts/gnu-renderer-pfc-hardware",),
        ),
        "observers": (
            "8a659140df8ab27fd6a8cc61f5eb38717b3f8bbc",
            ("scripts/gnu-example-ceiling", "scripts/gnu-renderer-library-workers"),
        ),
    }
    env = os.environ | {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    args = []
    for name, (ref, paths) in refs.items():
        p = directory / name
        p.mkdir()

        def git(*given):
            return subprocess.check_output(["git", "-C", p, *given], env=env)

        git("init", "-q")
        (p / ".git/objects/info/alternates").write_text(
            "".join(
                str(OSS / v / ".git/objects") + "\n"
                for v in (
                    "ohm-benchmarks-1.99.0-6",
                    "ohm-package-qa-strict-unicode-cost-20261031",
                )
            )
        )
        (p / ".git/shallow").write_text(ref + "\n")
        git("sparse-checkout", "set", "--cone", *paths)
        git("checkout", "--quiet", "--detach", ref)
        need(
            git("rev-parse", "HEAD").strip().decode() == ref
            and not git("remote").strip(),
            "wrong native reviewer source",
        )
        args.extend(("--" + name, str(p)))
    return args


def reopen(raw, folder, head, sources, selection):
    need(
        sha(EXCLUDED_SIX.read_bytes()) == EXCLUDED_SHA,
        "wrong earlier six-boot protected input",
    )
    cmd = [
        sys.executable,
        "-IB",
        str(HERE / "review.py"),
        "--head",
        head,
        "--official",
        str(folder),
        "--zip",
        str(raw),
        "--concurrent-admission",
        str(EXCLUDED_SIX),
        "--concurrent-sha256",
        EXCLUDED_SHA,
        *sources,
        *selection,
    ]
    fd = int(raw.name)
    p = subprocess.run(cmd, cwd=CWD, pass_fds=(fd,), capture_output=True, timeout=1200)
    need(
        p.returncode == 0,
        (
            "original native receiver refused",
            p.stderr[-12000:].decode(errors="replace"),
        ),
    )
    need(0 < len(p.stdout) < (1 << 20), "unexpected native projection shape")
    return json.loads(p.stdout)


def compact(raw, identity):
    """Only retain bounded originals from the closed visit, disk, PMU and donor evidence."""
    fields = {
        "visit.json",
        "clock.json",
        "source.json",
        "source-before.json",
        "source-after.json",
        "native.json.gz",
        "ruff-build-script.json",
        "donor-register.json",
        "donor-opens.json",
        "donor-selected.json",
        "live-drivers.json.gz",
        "pyi009.json",
        "storage.json",
        "table-storage.json",
        "cargo.json.gz",
        "reader-run.json.gz",
        "layout-64.json.gz",
        "layout-56.json.gz",
    }
    roots = {
        "position.json",
        "PLAN.md",
        "complete.json",
        "history-intervals.json",
        "meter-ready.json",
        "git-layout.json",
        "resource/resources.json",
        "calibration/admitted.json",
        "sdk/D.json",
        "sdk/Q.json",
        "sdk/q-source-slot.json",
        "sdk/q-native-source.json",
        "sdk/q-official.json",
        "sdk/q-published-source.json",
        "kernel-qualification/fixtures/group-v2/qualified.json",
    }
    paths = {}
    bodies = {}
    index = {}
    size = 0
    with zipfile.ZipFile(raw) as z:
        for f in z.infolist():
            n = f.filename
            s = n.split("/")
            need(n not in index, "duplicate portable input")
            index[n] = [f.file_size, f.compress_size, f.CRC]
            keep = (
                n in roots
                or len(s) == 2
                and s[0].endswith(("-Don", "-Qon"))
                and s[1] in ("arm.json", "catalog.json", "loader.json")
                or len(s) == 3
                and s[0].endswith(("-Don", "-Qon"))
                and (
                    s[2] in fields
                    or s[0].startswith("structural-")
                    and s[1] == "X-B"
                    and s[2]
                    in (
                        "kernel.tsv.gz",
                        "native-execs.json.gz",
                        "lifecycle.json",
                        "wild-helpers.json",
                    )
                )
            )
            if not keep:
                continue
            size += f.file_size
            need(
                f.file_size <= 2 << 20 and size <= 12 << 20,
                "unregistered extra compact input",
            )
            b = z.read(n)
            digest = sha(b)
            need(
                len(b) == f.file_size and binascii.crc32(b) == f.CRC,
                "corrupt compact input",
            )
            paths[n] = digest
            bodies.setdefault(digest, base64.b64encode(b).decode("ascii"))
    need(
        sum(k.endswith("/clock.json") for k in paths) == 14
        and sum(k.endswith("/visit.json") for k in paths) == 46,
        "wrong compact denominator",
    )
    val = dict(original=identity, sha256_members=paths, bodies=bodies, central=index)
    result = gzip.compress(
        (json.dumps(val, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        mtime=0,
    )
    need(len(result) <= 4 << 20, "compact shape exceeds frozen cap")
    for name, h in json.loads(gzip.decompress(result))["sha256_members"].items():
        b = base64.b64decode(bodies[h], validate=True)
        need(
            sha(b) == h
            and len(b) == index[name][0]
            and binascii.crc32(b) == index[name][2],
            "unrestorable source projection",
        )
    return result


def collect(media, folder, rid, head):
    early = load(folder / "pre-outcome.json")
    need(
        early["run"] == rid
        and early["head"] == head
        and early["assets"] == early["outcome_members_opened"] == 0
        and set(early["positions"]) == set(six.POSITIONS),
        "wrong initial six original slots",
    )
    for name in (
        "authenticated",
        "machines",
        "ids",
        "independent",
        "compact",
        "refused",
    ):
        (folder / name).mkdir(exist_ok=True)
    while True:
        run, jobs, assets = metadata(media, rid, head)
        need(
            jobs["total_count"] == 6 and assets["total_count"] <= 6,
            "changed matrix size",
        )
        js = {}
        ars = {}
        for slot in six.POSITIONS:
            (j,) = [row for row in jobs["jobs"] if row["name"] == six.LABEL + slot]
            js[slot] = j
            need(
                early["positions"][slot]
                == dict(job=j["id"], order=list(six.order(slot))),
                "replaced job",
            )
            if j["runner_name"] and j["runner_id"]:
                save(
                    folder / "machines" / (slot + ".json"),
                    dict(
                        job=j["id"],
                        runner=j["runner_name"],
                        runner_id=j["runner_id"],
                        run=rid,
                        head=head,
                    ),
                )
            links = [a for a in assets["artifacts"] if a["name"] == six.ARTIFACT + slot]
            need(len(links) <= 1, "duplicate official asset")
            if not links:
                continue
            a = ars[slot] = links[0]
            target = folder / "ids" / (slot + ".json")
            err = folder / "refused" / (slot + "-identity.json")
            if j["status"] != "completed" or target.exists() or err.exists():
                continue
            try:
                record = transfer(
                    media,
                    folder,
                    a,
                    rid,
                    head,
                    "identity",
                    slot,
                    lambda raw: position(raw, slot, j, a),
                )
                save(target, record)
                print(
                    "Sealed original position", slot, record["meta"]["boot"], flush=True
                )
            except Exception as e:
                save(
                    err,
                    dict(error=repr(e), id=a["id"], sha256=a["digest"], no_score=True),
                )
        need(len(ars) == assets["total_count"], "unregistered original")
        if run["status"] == "completed" and all(
            j["status"] == "completed" for j in js.values()
        ):
            break
        time.sleep(65)
    for n, x in (("run", run), ("jobs", jobs), ("artifacts", assets)):
        save(folder / (n + ".json"), x)
    hs = {
        p: load(folder / "ids" / (p + ".json"))["meta"]
        for p in six.POSITIONS
        if (folder / "ids" / (p + ".json")).exists()
    }
    try:
        six.check_hosts(hs)
        reason = None
    except (ValueError, KeyError) as e:
        reason = repr(e)
    admission = dict(
        head=head,
        run=rid,
        admitted=reason is None,
        reason=reason,
        hosts=hs,
        missing=sorted(set(six.POSITIONS) - set(hs)),
        outcomes_opened=0,
    )
    save(folder / "boot-admission.json", admission)
    print(
        "All six original identities",
        admission["admitted"],
        len(hs),
        sha((folder / "boot-admission.json").read_bytes()),
        flush=True,
    )
    reports = {}
    errors = {}
    with tempfile.TemporaryDirectory(
        prefix="sorted-ref-six-reader-", dir="/dev/shm"
    ) as temp:
        sources = physical_sources(Path(temp)) if reason is None else []
        for slot, a in sorted(ars.items()):
            out = folder / "independent" / (slot + ".json.gz")
            if out.exists():
                reports[slot] = json.loads(gzip.decompress(out.read_bytes()))
                continue

            def inspect(raw):
                if reason is not None or js[slot]["conclusion"] != "success":
                    with zipfile.ZipFile(raw) as z:
                        names = z.namelist()
                        refusal = (
                            z.read("failure.txt").decode(errors="replace")[-10000:]
                            if "failure.txt" in names
                            and z.getinfo("failure.txt").file_size < 1 << 20
                            else None
                        )
                        save(
                            folder / "refused" / (slot + "-worker.json"),
                            dict(
                                id=a["id"],
                                sha256=a["digest"],
                                reason=refusal,
                                visit_files=sum(
                                    n.endswith("/visit.json") for n in names
                                ),
                                clock_files=sum(
                                    n.endswith("/clock.json") for n in names
                                ),
                                outcomes_scored=0,
                            ),
                        )
                    raise ValueError("six-boot or worker refused")
                report = reopen(raw, folder, head, sources, ["--position", slot])
                need(
                    report["qualified"]
                    and report["official"] == dict(hs[slot], attempt=1)
                    and report["metered"] == 14
                    and report["visits"] == 46
                    and report["boot"] == hs[slot]["boot"],
                    "partial replay",
                )
                savepath = folder / "compact" / (slot + ".json.gz")
                write(savepath, compact(raw, hs[slot]))
                write(
                    out,
                    gzip.compress(json.dumps(report, sort_keys=True).encode(), mtime=0),
                )
                return report

            try:
                reports[slot] = transfer(
                    media, folder, a, rid, head, "native", slot, inspect
                )
            except Exception as e:
                errors[slot] = repr(e)
                save(
                    folder / "refused" / (slot + "-read.json"),
                    dict(error=repr(e), no_claim=True),
                )
    verdict = (
        six.evaluate(reports, hs)
        if len(reports) == 6 and run["conclusion"] == "success" and not errors
        else None
    )
    final = dict(
        run=rid,
        head=head,
        denominator=6,
        obtained=len(ars),
        admitted=len(hs),
        independent=len(reports),
        conclusion=run["conclusion"],
        boot_admission_sha256=sha((folder / "boot-admission.json").read_bytes()),
        errors=errors,
        primary=verdict,
        input_sha256={
            p: sha((folder / "independent" / (p + ".json.gz")).read_bytes())
            for p in reports
        },
        compact_sha256={
            p: sha((folder / "compact" / (p + ".json.gz")).read_bytes())
            for p in reports
        },
    )
    save(folder / "final.json", final)
    print(
        "TERMINAL",
        sha((folder / "final.json").read_bytes()),
        json.dumps(verdict),
        flush=True,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("bind", "collect", "rehearse"))
    ap.add_argument("--run", required=True, type=int)
    ap.add_argument("--head", required=True)
    ap.add_argument("--root", required=True, type=Path)
    args = ap.parse_args()
    root = args.root.resolve(strict=True)
    need(
        root.parent == DATA and shutil.disk_usage(root).free > FLOOR + 65536,
        "outside enrolled destination or insufficient space",
    )
    need(
        subprocess.check_output(
            ["git", "-C", CWD, "rev-parse", "HEAD"], text=True
        ).strip()
        == args.head,
        "wrong local coordinator source",
    )
    six.frozen()
    media = prior_media(root)
    if args.action == "rehearse":
        need(args.run == six.CONTACT, "not the one excluded original")
        original = (
            DATA / "ohm-sorted-packed-ref-cli-contact-20261101" / str(six.CONTACT)
        )
        (asset,) = load(original / "artifacts.json")["artifacts"]
        need(
            asset["digest"] == "sha256:" + six.CONTACT_ORIGINAL
            and sha((original / "independent.json").read_bytes()) == six.CONTACT_REPLAY,
            "different pilot",
        )
        with tempfile.TemporaryDirectory(
            prefix="sorted-ref-six-rehearsal-", dir="/dev/shm"
        ) as t:
            src = physical_sources(Path(t))
            with media.media(
                asset, six.CONTACT, six.CONTACT_HEAD, root / "preflight-original"
            ) as raw:
                result = reopen(raw, original, args.head, src, ["--rehearsal-contact"])
                old = load(original / "independent.json")
                need(
                    all(result[k] == v for k, v in old.items()),
                    "changed source admission in previous complete original",
                )
                try:
                    six.official(original, raw, args.head, "01")
                except (ValueError, FileNotFoundError):
                    pass
                else:
                    raise ValueError("pilot incorrectly enrolled as confirmation")
                summary = dict(
                    qa=args.head,
                    official=old["official"],
                    original_fields_equal=len(old),
                    native_bodies=result["checked_native_bodies"],
                    visits=result["visits"],
                    raw_clocks=sum(map(len, result["raw_clocks"].values())),
                    traced=result["traced"],
                    prior_rejected_as_confirmation=True,
                )
                save(root / "rehearsal-result.json", summary)
                print(summary)
        return
    folder = root / str(args.run)
    folder.mkdir(exist_ok=True)
    if args.action == "bind":
        bind(media, folder, args.run, args.head)
    else:
        collect(media, folder, args.run, args.head)


if __name__ == "__main__":
    main()
