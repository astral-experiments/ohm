"""One unscored native qualification or one half of the pre-registered two-boot screen."""

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tarfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calibration
import evidence
import seed
from ingress import (
    AMENDMENT,
    BRANCH,
    HERE,
    PLAN,
    REPO,
    RUST,
    STUDIES,
    legal,
    need,
    official,
    provenance,
    put,
    registration,
    sha,
)

ROOT = Path("/tmp/ohm-gnu-renderer-pfc-study")
PACKETS = ("adapter", "oracle", "mono", "membership")


def programs(reg, root, phase):
    out = {}
    for name in (*PACKETS, *(("whole_oracle",) if phase == "screen" else ())):
        binding = reg[name]
        folder = root / "packets" / name
        folder.mkdir(parents=True)
        done = {}
        with tarfile.open(HERE / "packets" / binding["file"], "r:gz") as t:
            for m in t:
                need(legal(m.name) and (m.isdir() or m.isfile()), "foreign or linked packet member")
                if m.isdir():
                    continue
                need(
                    m.name not in done and m.name in binding["files"] and m.size <= 16 * 2**20,
                    "extra/large/duplicate packet member",
                )
                dst = folder / m.name
                dst.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(m) as inp, dst.open("xb") as f:
                    shutil.copyfileobj(inp, f)
                done[m.name] = sha(dst)
        need(done == binding["files"], "incomplete or changed " + name + " source")
        out[name] = folder
    if phase == "screen":
        # The tiny additional whole-lane executable shares the exact decoder already used by qualification.
        for member, h in reg["oracle"]["files"].items():
            installed = out["whole_oracle"] / member
            if installed.exists():
                need(sha(installed) == h, "screen overrides qualified native decoder")
            else:
                installed.parent.mkdir(parents=True, exist_ok=True)
                os.link(out["oracle"] / member, installed)
    return out


def logged(log, argv, cwd=None):
    log.mkdir(parents=True, exist_ok=False)
    argv = list(map(str, argv))
    put(log / "argv.json", {"argv": argv, "cwd": str(cwd or Path.cwd())})
    with (log / "stdout").open("xb") as stdout, (log / "stderr").open("xb") as stderr:
        code = subprocess.run(argv, stdout=stdout, stderr=stderr, cwd=cwd, timeout=3600).returncode
    put(log / "exit.json", {"code": code, "stdout": sha(log / "stdout"), "stderr": sha(log / "stderr")})
    if code:
        print((log / "stderr").read_bytes()[-1600:].decode(errors="replace"), file=sys.stderr)
    need(code == 0, ("failed external", str(log), code))


def script(log, path, *args):
    logged(log, [sys.executable, "-IB", path, *args])


def accepted(folder, log, files):
    """Couple each external checker exit to the complete terminal input and output bytes."""
    paths = sorted(set(files))
    need(
        paths and all(p.is_file() and not p.is_symlink() and p != folder / "verified.json" for p in paths),
        "missing external terminal input/output",
    )
    ident = {str(p.relative_to(folder)): sha(p) if p.is_file() else None for p in paths}
    need(evidence.read(log / "exit.json")["code"] == 0, "external checker failed")
    put(
        folder / "verified.json",
        {
            "exit": sha(log / "exit.json"),
            "files": ident,
            "executed_argv": evidence.read(log / "argv.json")["argv"],
        },
    )
    return sha(folder / "verified.json")


def checked_oracle(path, history, roles):
    report = json.loads(gzip.decompress(path.read_bytes()))
    need(
        report.get("accepted") is True
        and not report.get("refusal")
        and report["history"] == history
        and set(report["roles"]) == set(roles),
        "unexpected native semantic verdict",
    )
    if len(roles) > 1:
        need(not report.get("pending"), "unresolved cross-role native or metadata evidence")


def runner_identity(reg, phase, pos, boot):
    e = os.environ
    head = e["GITHUB_SHA"]
    run = int(e["GITHUB_RUN_ID"])
    attempt = int(e["GITHUB_RUN_ATTEMPT"])
    need(
        e["GITHUB_REPOSITORY"] == REPO
        and e["GITHUB_EVENT_NAME"] == "workflow_dispatch"
        and e["GITHUB_REF_NAME"] == BRANCH
        and attempt == 1
        and e["REVIEWED_HEAD"] == head,
        "unreviewed event/enrollment",
    )
    header = official("runs/" + str(run))
    job = official("runs/" + str(run) + "/attempts/1/jobs?per_page=100")
    title = f"GNU renderer {phase} {head}"
    need(
        header["id"] == run
        and header["head_sha"] == head
        and header["head_branch"] == BRANCH
        and header["display_title"] == title
        and header["run_attempt"] == 1
        and header["event"] == "workflow_dispatch",
        "wrong official acquisition",
    )
    # All enrolled positions originate in one dispatch of this exact frozen phase and head.
    others = official("runs?branch=" + BRANCH + "&event=workflow_dispatch&head_sha=" + head + "&per_page=100")
    need(
        others["total_count"] == len(others["workflow_runs"])
        and [w["id"] for w in others["workflow_runs"] if w["display_title"] == title] == [run],
        "duplicate acquisition of this phase",
    )
    name = phase + " (" + pos + ")"
    (jobrow,) = [x for x in job["jobs"] if x["name"] == name]
    allowed = {phase + " (" + v + ")" for v in (["gate"] if phase == "qualify" else ["01", "02"])}
    need(
        set(x["name"] for x in job["jobs"]) == allowed
        and jobrow["head_sha"] == head
        and jobrow.get("runner_name")
        and jobrow["status"] == "in_progress",
        "unknown native host or incomplete matrix",
    )
    return {
        "run": run,
        "attempt": attempt,
        "head": head,
        "job": jobrow["id"],
        "official_job": name,
        "official_runner": jobrow["runner_name"],
        "runner": e["RUNNER_NAME"],
        "host": os.uname().nodename,
        "boot": boot,
        "position": pos,
        "github_url": header["html_url"],
    }


def inspection_tools():
    programs = {}
    for name in ("strace", "c++filt", "readelf", "ar", "git", "zstd", "cc", "rustup"):
        path = shutil.which(name)
        need(path, "missing native tool " + name)
        resolved = Path(path).resolve(strict=True)
        run = subprocess.run([path, "--version"], capture_output=True, check=True)
        programs[name] = {
            "path": path,
            "physical_path": str(resolved),
            "sha256": sha(resolved),
            "stdout": run.stdout.decode(errors="replace"),
            "stderr": run.stderr.decode(errors="replace"),
        }
    programs["python"] = {"path": sys.executable, "sha256": sha(sys.executable), "version": sys.version}
    return programs


def disk(path):
    u = shutil.disk_usage(path)
    return {"total": u.total, "free": u.free}


def retired_sdk(sdk, manifest, role, root):
    """Prove the complete installation again, retain driver + directory identity, then release the common files."""
    expected = manifest["files"].copy()
    expected[manifest["driver"]] = manifest["roles"][role]["driver"]
    actual = {}
    for p in sdk.rglob("*"):
        need(not p.is_symlink(), "unexpected installed SDK symlink")
        if p.is_file():
            actual[p.relative_to(sdk).as_posix()] = [sha(p), p.stat().st_size, p.stat().st_mode & 0o777]
    need(actual == expected, "an installed SDK member changed while serving the ordinary cell")
    save = root / ("finished-sdk-" + role)
    save.mkdir()
    d = sdk / manifest["driver"]
    st = d.stat()
    os.link(d, save / "driver")
    usage = {}
    for p in (sdk, *sdk.rglob("*")):
        physical = p.lstat()
        usage[physical.st_dev, physical.st_ino] = physical.st_blocks * 512
    return {
        "allocated_sdk_bytes": sum(usage.values()),
        "allocated_driver_bytes": st.st_blocks * 512,
        "driver": [st.st_dev, st.st_ino, actual[manifest["driver"]]],
        "files": len(actual),
        "bytes": sum(v[1] for v in actual.values()),
        "root": [sdk.stat().st_dev, sdk.stat().st_ino],
    }


def verify_cell(
    reg, role, hist, lane, root, receipt, packets, work, sdk, ruff, registry, proxies, plain, boot
):
    k = role + "-" + hist
    out = receipt / "cells" / k
    adapter = packets["adapter"]
    logs = receipt / "logs" / k
    cmd = [
        "--role",
        role,
        "--history",
        hist,
        "--lane",
        lane,
        "--work",
        work,
        "--sdk",
        sdk,
        "--manifest",
        root / "transfer/manifest.json",
        "--manifest-sha",
        reg["source"]["manifest_sha256"],
        "--ruff",
        ruff,
        "--registry",
        registry,
        "--proxies",
        proxies,
        "--out",
        out,
    ]
    if lane == "whole":
        cmd += ["--counter", plain, "--counter-sha", sha(plain)]
    need(
        not work.exists() and not out.exists() and disk(root)["free"] >= 5 * 2**30,
        "insufficient scratch or an existing cell",
    )
    script(logs / "arm", adapter / "arm.py", *cmd)
    row = evidence.cell(out, role, hist, lane, plain, boot)
    # Re-execute complete archived client/test ELFs from the original immutable input manifests.
    src = work / "source"
    park = work / "closed-source"
    src.rename(park)
    try:
        flags = ["--upstream-files", "--upstream-work", work] if hist == "source-map" else []
        script(logs / "reopen-arm", adapter / "reopen.py", out, *flags)
    finally:
        need(not os.path.lexists(src) and park.is_dir(), "the escrowed source path was not released")
        park.rename(src)
    if lane == "structural" and hist == "source-map":
        logs_m = receipt / "logs" / ("mono-" + role)
        where = receipt / "mono" / role
        script(
            logs_m / "acquire",
            HERE / "mono.py",
            "--work",
            work,
            "--sdk",
            sdk,
            "--cell",
            out,
            "--adapter",
            adapter,
            "--out",
            where,
            "--proxies",
            proxies,
        )
        # Placement classifier from the separately frozen source parser. No scoring if it rejects.
        for phase in ("old", "edit"):
            script(
                logs_m / ("inspect-" + phase),
                packets["mono"] / "mono.py",
                "--phase",
                phase,
                "--role",
                role,
                "--stdout",
                where / "raw" / phase / "stdout.gz",
                "--out",
                where / (phase + "-placement.json"),
            )
        mono = accepted(
            where,
            logs_m / "inspect-edit",
            [where / "old-placement.json", where / "edit-placement.json", where / "acquired.json"],
        )
    else:
        mono = None
    where = receipt / "external" / k
    where.mkdir(parents=True)
    script(
        logs / "native-oracle",
        packets["oracle"] / "oracle.py" if lane == "structural" else packets["whole_oracle"] / "whole.py",
        "role",
        *(["--structural-root", root / "qualified-cells"] if lane == "whole" else []),
        "--history",
        hist,
        "--cell",
        out,
        "--out",
        where / "oracle.json.gz",
    )
    checked_oracle(where / "oracle.json.gz", hist, [role])
    row["external_oracle"] = accepted(where, logs / "native-oracle", [where / "oracle.json.gz"])
    row["replayed_ordinary"] = sha(logs / "reopen-arm" / "stdout")
    rootids = evidence.read(out / "independent-empty.json")["original"]
    row["initial_storage_inodes"] = {
        k: v for k, v in rootids.items() if k in ("target", "shared", "cargo-home")
    }
    parkwork = root / ("finished-" + k)
    work.rename(parkwork)
    # Pin all earlier roots and their stores while the next arm acquires new inodes under the same logical names.
    return row, mono


def worker(args):
    phase, pos = args.phase, args.position
    reg = registration(phase)
    need(
        (phase == "qualify") == (pos == "gate") and pos in ("gate", "01", "02"), "incompatible phase and host"
    )
    receipt = (
        Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        / ("gnu-renderer-pfc-" + phase + "-" + pos)
        / "receipt"
    )
    receipt.mkdir(parents=True, exist_ok=False)
    shutil.copy2(HERE / "registration.json", receipt / "registration.json")
    shutil.copy2(HERE / "PLAN.md", receipt / "PLAN.md")
    shutil.copy2(HERE / "PLAN-V2.md", receipt / "PLAN-V2.md")
    try:
        ROOT.mkdir(mode=0o700)
        root = ROOT
        need(
            root == root.resolve() and shutil.disk_usage(root).free >= 24 * 2**30,
            "need a fresh canonical worker with 24 GiB scratch",
        )
        boot = calibration.host(args.observers, receipt)
        result = runner_identity(reg, phase, pos, boot)
        result["logical_receipt"] = str(receipt)
        put(receipt / "enrollment.json", result)
        put(receipt / "inspection-tools.json", inspection_tools())
        expected_head = subprocess.check_output(
            ["git", "-C", args.source, "rev-parse", "HEAD"], text=True
        ).strip()
        need(expected_head == reg["source"]["head"], "wrong source SDK restorer checkout")
        src = args.source / "scripts/gnu-renderer-cgu-source"
        inbound = provenance(reg, phase, root, src)
        put(receipt / "official.json", inbound)
        if phase == "screen":
            need(inbound["matched_structural"]["boot"] != boot, "screen reused the qualification boot")
        for key in ("GH_TOKEN", "GITHUB_TOKEN", "PFC_GH"):
            os.environ.pop(key, None)
        import restore

        packets = programs(reg, root, phase)
        restore_role = lambda role, dst: restore.restore(
            root / "transfer",
            dst,
            role,
            reg["source"]["head"],
            reg["source"]["run"],
            reg["source"]["attempt"],
        )
        rawsdk = evidence.read(root / "transfer/manifest.json")
        shutil.copy2(root / "transfer/manifest.json", receipt / "source-manifest.json")
        lane = "structural" if phase == "qualify" else "whole"
        plain = None
        if phase == "screen":
            plain = calibration.setup(args.observers, root, receipt)
        ruff, registry, proxies = seed.prepare(root, receipt, restore_role)
        os.environ["PATH"] = str(proxies) + ":" + os.environ["PATH"]
        result.update(
            schema=1,
            phase=phase,
            source=[
                reg["source"]["run"],
                reg["source"]["head"],
                reg["source"]["attempt"],
                reg["source"]["manifest_sha256"],
            ],
            whole_oracle=reg["whole_oracle"]["sha256"] if phase == "screen" else None,
            plan=PLAN,
            amendment=AMENDMENT,
            packets={k: reg[k]["sha256"] for k in PACKETS},
            cells={},
            mono={},
            cross={},
            membership={},
            storage={},
            sdks={},
        )
        schedule = (
            {"roles": list(RUST), "histories": list(STUDIES)} if phase == "qualify" else reg["positions"][pos]
        )
        result["order"] = schedule
        result["acquisition_order"] = []
        result["storage"]["before"] = disk(root)
        for folder in ("logs", "cells", "external", "membership", "mono"):
            (receipt / folder).mkdir()
        ids = {}
        sdk = root / "sdk"
        work = root / "work"
        for role in schedule["roles"]:
            restore_role(role, sdk)
            if phase == "qualify":
                log = receipt / "logs" / ("membership-" + role)
                where = receipt / "membership" / role
                driver = rawsdk["roles"][role]["driver"][0]
                g = packets["membership"]
                script(
                    log / "run",
                    g / "run.py",
                    "--role",
                    role,
                    "--sdk",
                    sdk,
                    "--driver",
                    driver,
                    "--work",
                    root / "fixture-work",
                    "--out",
                    where,
                )
                script(log / "readback", g / "replay.py", where, role, driver)
                verified = evidence.read(log / "readback/stdout")
                need(
                    [
                        verified["role"],
                        verified["elfs"],
                        verified["native_verdicts"],
                        verified["result_sha256"],
                    ]
                    == [role, 4, 12, sha(where / "result.json")],
                    "native membership readback differs",
                )
                result["membership"][role] = accepted(where, log / "readback", [where / "result.json"])
                (root / "fixture-work").rename(root / ("finished-membership-" + role))
            for hist in schedule["histories"]:
                k = role + "-" + hist
                result["acquisition_order"].append(k)
                put(receipt / "logs" / ("enter-" + k + ".json"), {"next": k, "disk": disk(root)})
                row, mono = verify_cell(
                    reg,
                    role,
                    hist,
                    lane,
                    root,
                    receipt,
                    packets,
                    work,
                    sdk,
                    ruff,
                    registry,
                    proxies,
                    plain,
                    boot,
                )
                ids[k] = set(map(tuple, row["initial_storage_inodes"].values()))
                need(
                    len(ids[k]) == 3 and all(not ids[k] & v for c, v in ids.items() if c != k),
                    "prior arm shares a physical build/store root",
                )
                result["cells"][k] = row
                if mono:
                    result["mono"][role] = mono
                result["storage"][k] = disk(root)
            result["sdks"][role] = retired_sdk(sdk, rawsdk, role, root)
            seed.remove_private(root, sdk)
        need(
            len({tuple(v["driver"][:2]) for v in result["sdks"].values()}) == 3,
            "physical driver identities collided",
        )
        for hist in STUDIES:
            log = receipt / "logs" / ("cross-" + hist)
            out = receipt / "external" / ("cross-" + hist)
            out.mkdir()
            script(
                log,
                packets["oracle"] / "oracle.py"
                if phase == "qualify"
                else packets["whole_oracle"] / "whole.py",
                "compare",
                *(["--structural-root", root / "qualified-cells"] if phase == "screen" else []),
                "--history",
                hist,
                "--parent",
                receipt / "cells" / ("P-" + hist),
                "--role",
                "F=" + str(receipt / "cells" / ("F-" + hist)),
                "--role",
                "C=" + str(receipt / "cells" / ("C-" + hist)),
                "--out",
                out / "oracle.json.gz",
            )
            checked_oracle(out / "oracle.json.gz", hist, RUST)
            result["cross"][hist] = accepted(out, log, [out / "oracle.json.gz"])
            for state in ("edit", "empty"):
                ref = result["cells"]["P-" + hist]["storage"][state]
                for role in ("F", "C"):
                    counts = result["cells"][role + "-" + hist]["storage"][state]
                    need(
                        all(
                            counts[n] <= ref[n]
                            for n in ("rlib_inodes", "session_indices", "saved_link_payloads")
                        ),
                        "extra complete rlib, saved link payload, or session "
                        + state
                        + "/"
                        + role
                        + "/"
                        + hist,
                    )
        evidence.header(result, reg, phase)
        put(receipt / "members.json", evidence.tree_inventory(receipt, {"certificate.json", "members.json"}))
        result["members"] = sha(receipt / "members.json")
        put(receipt / "certificate.json", result)
    except BaseException:
        (receipt / "failed.txt").write_text(traceback.format_exc())
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("phase", choices=["qualify", "screen"])
    p.add_argument("position", choices=["gate", "01", "02"])
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--observers", type=Path, required=True)
    worker(p.parse_args())
