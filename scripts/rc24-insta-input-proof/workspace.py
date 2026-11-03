"""Price all 55 ordinary Ruff default members with the matched Cargo pair, keeping the real links."""

import collections
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ws = Path(os.environ["GITHUB_WORKSPACE"])
ref = ws / "reference/scripts/ruff-original-ty-instructions"
ing = ws / "sdk-ingress/scripts/ron-ordinary-backend"
sys.path.insert(0, str(ing))
import ordinary as intake

b = intake.b
w = b.w
plan = json.loads((HERE / "workspace-enrollment.json").read_bytes())
bind = json.loads((HERE / "pricing.json").read_bytes())
source = json.loads((HERE / "registration.json").read_bytes())
report = w.proof


def git(c, *a):
    return subprocess.check_output(["git", *a], cwd=c, text=True).strip()


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(p):
    return json.loads(
        gzip.decompress(p.read_bytes()) if p.suffix == ".gz" else p.read_bytes()
    )


def pair():
    asset = bind["pair_asset"]
    ep = "repos/astral-experiments/ohm/actions/artifacts/" + str(asset)
    env = {
        "HOME": os.environ["HOME"],
        "PATH": os.environ["PATH"],
        "GH_TOKEN": os.environ.pop("OHM_PAIR_READ_TOKEN"),
    }
    item = json.loads(subprocess.check_output(["gh", "api", ep], env=env))
    assert (
        item["digest"] == "sha256:" + bind["pair_zip"]
        and item["workflow_run"]["id"] == bind["producer_run"]
    )
    pkg = w.root / "matched.zip"
    with pkg.open("xb") as f:
        subprocess.run(["gh", "api", ep + "/zip"], env=env, stdout=f, check=True)
    assert sha(pkg) == bind["pair_zip"] and pkg.stat().st_size == item["size_in_bytes"]
    roles = {}
    with zipfile.ZipFile(pkg) as z:
        assert z.testzip() is None and sorted(
            x.filename for x in z.infolist() if not x.is_dir()
        ) == ["build.json", "candidate/cargo", "parent/cargo"]
        record = json.loads(z.read("build.json"))
        assert (
            int(record["run"]) == bind["producer_run"]
            and record["qa"] == bind["producer_head"]
            and record["sdk_sha256"] == source["release_sha256"]
            and record["rustc"] == source["rust"]
        )
        for role in ("parent", "candidate"):
            p = w.root / ("cargo-" + role)
            with z.open(role + "/cargo") as f, p.open("xb") as out:
                shutil.copyfileobj(f, out)
            p.chmod(0o755)
            assert (
                sha(p) == record["cargo"][role]["sha256"] == bind["cargo"][role]
                and record["cargo"][role]["source"] == source[role]
            )
            roles[role] = p
    b.write(report / "matched-source.json", record)
    return roles


def clean():
    # These are the three worker-owned disposable build directories. Native witnesses live outside them.
    for f in (w.target, w.shared, w.home):
        assert f.parent == w.root and f.is_dir() and not f.is_symlink()
        shutil.rmtree(f)
    b.PHYSICAL.clear()


def census(role, phase, env, graph):
    try:
        return b.inventory(phase, env, graph, "census"), None
    except Exception as ex:
        # Finish collecting the real error/repair/empty controls before rejecting an incomplete census.
        note = {"type": type(ex).__name__, "error": str(ex)[:4000]}
        b.write(b.PROOF / (phase + "-refused.json"), note)
        return None, note


def runrole(role, binary, env):
    assert all(not f.exists() for f in (w.target, w.shared, w.home))
    b.PROOF = report / role
    b.PROOF.mkdir()
    dst = w.sdk / "bin/cargo"
    tmp = dst.with_name("cargo.next")
    shutil.copyfile(binary, tmp)
    tmp.chmod(0o755)
    os.replace(tmp, dst)
    assert sha(dst) == bind["cargo"][role] and source[role] in subprocess.check_output(
        ["cargo", "+ohm", "-vV"], cwd=w.work, env=env, text=True
    )
    b.select(b.OLD)
    archives = b.inputs(env)
    b.write(b.PROOF / "registry.json.gz", archives)
    graph = json.loads(
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
    b.write(b.PROOF / "metadata.json.gz", graph)
    assert (
        sorted(graph["workspace_members"]) == sorted(graph["workspace_default_members"])
        and len(graph["workspace_default_members"]) == 55
    )
    assert (
        sorted(
            x["name"]
            for x in graph["packages"]
            if x["id"] in graph["workspace_default_members"]
        )
        == b.SPEC["default_members"]
    )

    def visit(label):
        return b.inventory(label, env, graph)

    def native(inv, name, rc):
        return b.verdict(w.root / inv["binary"], name, env, rc)

    old = visit("old")
    names = native(old, "old-native", 0)
    oldexe = w.root / ("retained-old-" + role)
    shutil.copy2(w.root / old["binary"], oldexe)
    assert sha(oldexe) == old["executables"][old["binary"]]["elf"]["sha256"]
    b.select(b.NEW)
    assert b.verdict(oldexe, "old-on-edit", env, 101) == names
    edited = visit("edit")
    assert native(edited, "edit-native", 0) == names
    first = visit("first-unchanged")
    second = visit("second-unchanged")
    obs, problem = census(role, "separate-unchanged-observed", env, graph)
    assert native(second, "settled-native", 0) == names
    src = w.work / "crates/ty_server/src/session.rs"
    orig = src.read_bytes()
    assert (
        subprocess.check_output(
            ["git", "show", b.NEW + ":crates/ty_server/src/session.rs"], cwd=w.work
        )
        == orig
    )
    try:
        src.write_bytes(orig + b'\nconst _: u8 = "invalid workspace build";\n')
        for phase in ("invalid", "invalid-again"):
            td = b.PROOF / phase
            td.mkdir()
            b.run(b.CMD, env, td, 101)
            msgs = [
                json.loads(l)
                for l in (td / "stdout.jsonl").read_bytes().splitlines()
                if l.startswith(b"{")
            ]
            assert msgs[-1] == {"reason": "build-finished", "success": False} and any(
                m["reason"] == "compiler-message"
                and (m["message"].get("code") or {}).get("code") == "E0308"
                and any(
                    x["is_primary"]
                    and x["file_name"].endswith("ty_server/src/session.rs")
                    for x in m["message"]["spans"]
                )
                for m in msgs
            )
            assert not any(
                m["reason"] == "compiler-artifact"
                and "ty_server" in m["package_id"]
                and m["target"]["kind"] == ["test"]
                and m["target"]["name"] == "e2e"
                for m in msgs
            )
    finally:
        src.write_bytes(orig)
    repaired = visit("repair")
    assert native(repaired, "repair-native", 0) == names
    clean()
    assert b.inputs(env) == archives
    independent = visit("independent-empty")
    assert native(independent, "empty-native", 0) == names
    leaves = {
        "old": old,
        "edit": edited,
        "first-unchanged": first,
        "second-unchanged": second,
        "repair": repaired,
        "independent-empty": independent,
    }
    if obs:
        leaves["separate-unchanged-observed"] = obs

    def digest(inv):
        return inv["executables"][inv["binary"]]["elf"]["sha256"]

    verdict = {
        "natives": {k: digest(i) for k, i in leaves.items()},
        "units": {k: len(i["units"]) for k, i in leaves.items()},
        "products": {k: len(i["executables"]) for k, i in leaves.items()},
        "names": names,
        "census_refusal": problem,
    }
    expected = set(independent["executables"])
    assert all(set(i["executables"]) == expected for i in leaves.values())
    verdict["whole"] = {
        k: read(b.PROOF / k / "hardware.json")["instructions"]
        for k in leaves
        if k != "separate-unchanged-observed"
    }
    verdict["changed_executables_vs_clean"] = {
        k: sorted(
            n
            for n in expected
            if i["executables"][n]["elf"]["sha256"]
            != independent["executables"][n]["elf"]["sha256"]
        )
        for k, i in leaves.items()
    }
    verdict["e2e_exact"] = all(
        digest(i) == digest(independent) for k, i in leaves.items() if k != "old"
    ) and digest(old) != digest(independent)
    if obs:
        epochs = read(b.PROOF / "separate-unchanged-observed/owner-census.json.gz")[
            "roles"
        ]
        real = [r for r in epochs if r["trigger"] == "exec"]
        linkers = [r for r in real if r["mode"] == "Wild"]
        verdict["execs"] = dict(collections.Counter(r["mode"] for r in real))
        verdict["full"] = sorted(
            r["crate"]
            for r in real
            if r["mode"] in ("full", "metadata", "test") and r.get("crate")
        )
        verdict["link_only"] = len([r for r in real if r["mode"] == "link-only"])
        verdict["wild"] = len(linkers)
        assert all(r.get("owning_rustc_epoch") is not None for r in linkers)
    b.write(b.PROOF / "complete.json", verdict)
    clean()
    return verdict


def main():
    assert sha(Path(__file__).resolve()) == plan["reviewed_worker_sha256"]
    assert (
        os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"]
        and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
        and git(HERE, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"]
    )
    assert (
        git(ref, "rev-parse", "HEAD") == plan["reference_qa"]
        and git(ing, "rev-parse", "HEAD") == plan["sdk_ingress_qa"]
        and b.CMD == source["normal_workspace"]["command"]
        and (b.OLD, b.NEW)
        == (source["normal_workspace"]["old"], source["normal_workspace"]["new"])
    )
    assert (
        sha(ref / "workspace29697.py") == plan["reference_reader"]
        and sha(ing / "ordinary.py") == plan["sdk_ingress"]
    )
    order = plan["orders"][os.environ["PRICE_BLOCK"]]
    assert shutil.disk_usage(w.root).free > 45 * 2**30
    b.write(
        report / "admission.json",
        dict(
            study=plan,
            order=order,
            boot=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            cpus=sorted(os.sched_getaffinity(0)),
            head=os.environ["GITHUB_SHA"],
            run=os.environ["GITHUB_RUN_ID"],
        ),
    )
    roles = pair()
    env = intake.install()
    os.replace(w.sdk / "bin/cargo", w.root / "original-cargo-preserved-for-this-job")
    for exe in ("whole_count", "exec_count"):
        subprocess.run(
            [
                "cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                str(ref / (exe + ".c")),
                "-o",
                str(w.root / exe),
            ],
            check=True,
        )
    subprocess.run(
        ["cc", "-O2", str(HERE / "calibrate.c"), "-o", str(w.root / "calibrate")],
        check=True,
    )
    readings = {}
    for variant in ("single", "fork"):
        file = report / ("calibration-" + variant + ".json")
        subprocess.run(
            [
                w.root / "whole_count",
                file,
                w.root / "calibrate",
                w.root / "calibrate",
                variant,
            ],
            check=True,
        )
        r = read(file)
        assert r["status"] == 0 and r["enabled"] == r["running"] > 0
        readings[variant] = r["instructions"]
    assert 1.99 < readings["fork"] / readings["single"] < 2.01
    results = {r: runrole(r, roles[r], dict(env)) for r in order}
    b.write(report / "result.json", results)
    assert all(
        v["e2e_exact"]
        and not v["census_refusal"]
        and set(v["units"].values()) == {623}
        and set(v["products"].values()) == {102}
        for v in results.values()
    ), (
        "withhold whole-workspace qualification; inspect original native bodies or census"
    )


if __name__ == "__main__":
    main()
