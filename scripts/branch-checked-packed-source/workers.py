"""Activate preverified full SDKs at one absolute rustup path and run the native collision controls."""

import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import corrected
import cargo_guard
import mixed
import oldkit
import prior
import restore_e
from objects import dump, file_sha, need


def switcher(sdk, roles, driver, env):
    names = (driver, "bin/rustdoc")
    identities = {
        role: {"source": source, "driver": manifest[driver][0], "rustdoc": manifest["bin/rustdoc"][0]}
        for role, (source, manifest, paths) in roles.items()
    }
    stable = {name: rec for name, rec in roles["old"][1].items() if name not in names}
    need(
        len(stable) == 79
        and all(
            {p: v for p, v in manifest.items() if p not in names} == stable
            for _, manifest, _ in roles.values()
        ),
        "different shared SDK members",
    )

    def activate(role):
        _, manifest, paths = roles[role]
        for name in names:
            target = sdk / name
            donor = paths[name].resolve(strict=True)
            if not target.samefile(donor):
                temp = target.with_name(target.name + ".collision-switch")
                os.link(donor, temp)
                os.replace(temp, target)
            s = target.stat()
            need(
                target.samefile(donor)
                and [file_sha(target), s.st_size, s.st_mode & 0o7777] == manifest[name],
                "different installed compiler role",
            )
        actual = subprocess.check_output(
            ["rustup", "which", "--toolchain", "ohm", "rustc"], env=env, text=True
        ).strip()
        need(Path(actual).samefile(sdk / "bin/rustc"), "different proxy SDK")
        return identities[role]["source"]

    return activate, identities


def run(root, log, sdk, files, before, k, transfer, env):
    import mixed_shadow

    base = log / "collision"
    base.mkdir()
    previous = corrected.ORIGINAL_ARTIFACT
    capsule = root / "previous-E-transfer"
    oldkit.verify(root / "old-e-media", capsule)
    old_manifest = json.loads((capsule / "manifest.json").read_bytes())
    old_dir = root / "genuine-previous-E"
    f_dir = root / "genuine-F"
    old_record = restore_e.restore(
        transfer,
        capsule,
        old_dir,
        previous["head"],
        previous["run"],
        "1",
        previous["qualified"]["manifest"],
    )
    o = corrected.K_ORIGIN
    f_record = prior.old.restore(transfer, f_dir, "F", o["head"], str(o["run"]), "1", o["manifest"])
    driver = k["driver"]
    names = (driver, "bin/rustdoc")
    roles = {
        "old": (corrected.PREVIOUS, old_manifest["files"], {n: old_dir / n for n in names}),
        "F": (k["roles"]["F"]["commit"], k["files"]["F"], {n: f_dir / n for n in names}),
        "corrected": (corrected.SHA, before, {n: files[Path(n)] for n in names}),
    }
    activate, ids = switcher(sdk, roles, driver, env)
    need(len({r["driver"] for r in ids.values()}) == 3, "not three distinct genuine compilers")
    dump(base / "roles.json", {"roles": ids, "old": old_record, "F": f_record, "official": previous})
    for role, policy in (("old", "original"), ("corrected", "reject")):
        activate(role)
        cargo_guard.experiment(
            base / ("cargo-" + role),
            root,
            sdk,
            Path(env["RUSTUP_HOME"]),
            roles[role][1],
            ids[role]["source"],
            driver,
            policy,
            env["PATH"],
        )
        mixed_shadow.trial(
            root, base / ("writer-old-reader-" + role), env, sdk, driver, activate, ids, role
        )
        trial_dir = root / ("natural-writer-" + role)
        trial_dir.mkdir()
        mixed.trial(trial_dir, base / ("natural-" + role), env, sdk, driver, activate, ids, role)
    activate("corrected")
    from read_collision import from_directory, verify

    with from_directory(base) as getter:
        result = verify(getter, ids)
    dump(base / "complete.json", result)
    return {
        "collision": file_sha(base / "complete.json"),
        "legacy_sdk": previous["qualified"]["manifest"],
    }
