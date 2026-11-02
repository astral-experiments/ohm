"""Admit two exact private compiler outputs built with the same recipe in separate jobs."""

from pathlib import Path
import json, os, re, shutil, subprocess, sys
import core as c
import enroll as e

m = c.m
PLAN = m.read(c.HERE / "pair.json")
C, G = PLAN["roles"]
REPO = "astral-experiments/ohm"
REPO_ID = 1319437234


def stamps(label, run, jobs, art):
    q = PLAN["arms"][label]
    head = q["head"]
    rid = q["rid"]
    branch = q["branch"]
    srv = q["artifact"]
    c.guard(
        all(
            run[k]["id"] == REPO_ID
            and run[k]["full_name"] == REPO
            and run[k]["private"] is True
            for k in ("repository", "head_repository")
        ),
        "run owner",
    )
    c.guard(
        (
            run["id"],
            run["head_sha"],
            run["head_branch"],
            run["path"],
            run["event"],
            run["run_attempt"],
            run["status"],
            run["conclusion"],
        )
        == (
            rid,
            head,
            branch,
            ".github/workflows/ci.yml",
            "workflow_dispatch",
            1,
            "completed",
            "success",
        ),
        "unregistered compiler producer",
    )
    c.guard(
        jobs["total_count"]
        == len(jobs["jobs"])
        == art["total_count"]
        == len(art["artifacts"])
        == 1,
        "extra or missing producer outputs",
    )
    (job,) = [j for j in jobs["jobs"] if j["id"] == q["job_id"]]
    (a,) = [a for a in art["artifacts"] if a["id"] == srv["id"]]
    c.guard(
        (
            job["run_id"],
            job["run_attempt"],
            job["head_sha"],
            job["name"],
            job["status"],
            job["conclusion"],
        )
        == (rid, 1, head, q["job_name"], "completed", "success"),
        "different or failed producer",
    )
    v = a["workflow_run"]
    c.guard(
        not a["expired"]
        and (
            v["id"],
            v["head_sha"],
            v["head_branch"],
            v["repository_id"],
            v["head_repository_id"],
        )
        == (rid, head, branch, REPO_ID, REPO_ID),
        "foreign artifact provenance",
    )
    c.guard(
        (a["name"], a["size_in_bytes"], a["digest"])
        == (q["artifact_name"], srv["bytes"], "sha256:" + srv["sha256"])
        and 30 << 20 < srv["bytes"] < 1060 << 20,
        "unbound SDK bytes",
    )
    c.guard(
        {s["name"] for s in job["steps"] if s["conclusion"] == "success"}
        >= set(q["required_steps"]),
        "missing real build or original native suites",
    )


def admit():
    w, tmp = c.host()
    opening, prev = m.check_sources(w)
    old = m.load("signed_sdk_authority", prev / "intake.py")
    out = w / "trait-results"
    proof = out / "intake"
    proof.mkdir()
    scratch = tmp / "inventory-sdk-install"
    scratch.mkdir()
    pool = tmp / "ctfe22-root-sdks"
    pool.mkdir()
    meta = proof / "role-material"
    meta.mkdir()
    old.released(scratch, proof)
    (archive,) = (scratch / "signed").glob("*.tar.gz")
    fixed = e.signed(scratch / "fixed", archive)
    result = {}
    for role in PLAN["roles"]:
        q = PLAN["arms"][role]
        here = proof / role
        here.mkdir()
        server = {}
        for name, tail in [
            ("run", ""),
            ("jobs", "/attempts/1/jobs?per_page=100"),
            ("artifacts", "/artifacts?per_page=100"),
        ]:
            server[name] = old.gh_json(
                "api",
                "--method",
                "GET",
                f"repos/{REPO}/actions/runs/" + str(q["rid"]) + tail,
            )
            m.save(here / (name + ".json"), server[name])
        stamps(role, server["run"], server["jobs"], server["artifacts"])
        builder = w / q["checkout"]
        h = builder / q["scripts"]
        c.guard(
            m.sha_git(builder, "rev-parse", "HEAD").decode().strip() == q["head"],
            "wrong builder snapshot",
        )
        c.guard(
            all(m.filesha(builder / p) == v for p, v in q["checked_files"].items()),
            "changed authenticated builder scripts",
        )
        sys.path.insert(0, str(h))
        stage = m.load("admitted_stage_" + role, h / "stage.py")
        bundle = stage.file_map()
        ref = "refs/heads/" + q["branch"]
        parents = [
            r[7:].decode()
            for r in m.sha_git(builder, "cat-file", "commit", "HEAD")
            .split(b"\n\n", 1)[0]
            .splitlines()
            if r.startswith(b"parent ")
        ]
        c.guard(parents == [q["parent"]], "unauthenticated builder parent")
        ctx = {
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_SHA": q["head"],
            "GITHUB_REF": ref,
            "GITHUB_WORKFLOW_REF": REPO + "/.github/workflows/ci.yml@" + ref,
            "GITHUB_RUN_ID": str(q["rid"]),
            "GITHUB_RUN_ATTEMPT": "1",
        }
        srv = q["artifact"]
        arc = scratch / (role + ".zip")
        old.gh_bytes(
            f"repos/{REPO}/actions/artifacts/{srv['id']}/zip",
            arc,
            srv["bytes"],
            srv["sha256"],
        )
        e.ROLES = ("unused", role)
        origin = scratch / role
        import domain_control
        domain_control.unpack(e,arc,origin,role)
        ident = e.check_archive(role, origin, stage, ctx, bundle)
        sdk = pool / role
        inv = e.extract(origin, sdk)
        dest = meta / role
        dest.mkdir()
        for f in origin.iterdir():
            if f.name != "sdk.tar.zst":
                shutil.copyfile(
                    f,
                    dest
                    / (
                        "built-sdk-inventory.json"
                        if f.name == "sdk-inventory.json"
                        else f.name
                    ),
                )
        for rel, src in fixed.items():
            f = sdk / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            c.guard(not f.is_symlink(), "symlink helper")
            shutil.copy2(src, f)
            inv[rel] = {
                "sha256": m.filesha(f),
                "bytes": f.stat().st_size,
                "mode": 0o755,
            }
        c.guard(
            ident["rustc_sha256"] == inv["bin/rustc"]["sha256"]
            and ident["driver_sha256"]
            == q["driver"]
            == inv["lib/" + ident["driver"]]["sha256"]
            and inv["bin/cargo"]["sha256"] == m.P["signed_cargo_sha256"],
            "wrong effective compiler/Cargo",
        )
        c.guard(
            stage.S["arms"][role]["commit"] == q["source"]["commit"]
            and stage.S["arms"][role]["tree"] == q["source"]["tree"]
            and stage.S["arms"][role]["epoch"] == q["source"]["epoch"],
            "incorrect source shape",
        )
        m.save(dest / "sdk-inventory.json", inv)
        env = {"PATH": "/usr/bin:/bin", "HOME": str(scratch), "LC_ALL": "C.UTF-8"}
        proc = lambda *a: subprocess.check_output(
            [str(i) for i in a], env=env, text=True
        )
        c.guard(
            proc(sdk / "bin/rustc", "-vV") == ident["rustc_vV"]
            and Path(proc(sdk / "bin/rustc", "--print", "sysroot").strip()).resolve()
            == sdk
            and "commit-hash: " + m.P["signed_cargo_commit"] + "\n"
            in proc(sdk / "bin/cargo", "-Vv"),
            "unexpected installed ABI",
        )
        libs = proc("ldd", sdk / "bin/rustc")
        mapped = {n: Path(v) for n, v in re.findall(r"(?m)^\s*(\S+) => (\S+)", libs)}
        c.guard(
            "not found" not in libs
            and all(
                mapped[n].samefile(sdk / "lib" / n)
                for n in [ident["driver"], *ident["resolved_llvm"]]
            ),
            "driver/LLVM escaped its source sysroot",
        )
        runtime = {
            k: inv[k]["sha256"]
            for k in [
                "bin/cargo",
                "bin/rustc",
                "bin/rustdoc",
                *["lib/" + n for n in [ident["driver"], *ident["resolved_llvm"]]],
            ]
        }
        c.guard(
            m.filesha(origin / "bootstrap.toml") == PLAN["bootstrap_sha256"]
            and m.read(origin / "commands.json")["build"] == PLAN["actual_build"]
            and m.filesha(origin / "commands.json") == q["command_log"],
            "build flags/host recipe changed",
        )
        result[role] = {
            "runtime": runtime,
            "server": srv,
            "source": q["source"],
            "stage1_archive": m.filesha(origin / "sdk.tar.zst"),
        }
    m.save(
        out / "intake.json",
        {
            "installed": result,
            "sdk_lock_sha256": m.filesha(c.HERE / "pair.json"),
            "signed_cargo_sha256": m.P["signed_cargo_sha256"],
        },
    )


def migration():
    import foreign
    foreign.gate()
