"""Verify the immutable official SDK and the private, source-matched GNU build artifacts."""

from pathlib import PurePosixPath
import shutil
from zipfile import ZipFile

import release_intake as sdk
import service as s


def official(donor, proof, temp):
    release = s.lock["signed_release"]
    tag = release["tag"]
    metadata = donor.gh_json("api", "repos/" + sdk.REPO + "/releases/tags/" + tag)
    s.m.save(proof / "published.json", metadata)
    assert metadata["immutable"] and not metadata["draft"] and not metadata["prerelease"]
    assert metadata["id"] == release["release_id"] and metadata["target_commitish"] == release["coordinator"]
    assets = {row["name"]: row for row in metadata["assets"]}
    assert len(assets) == len(metadata["assets"]) == 9
    need = release["asset"]
    actual = assets[need["name"]]
    assert all(actual[key] == need[key] for key in ("id", "size", "name", "digest"))
    assert need["digest"] == "sha256:" + release["sha256"]
    archive = temp / need["name"]
    assert archive.parent == temp and archive.name.endswith("-x86_64-unknown-linux-gnu.tar.gz")
    donor.gh_bytes(f"repos/{sdk.REPO}/releases/assets/{need['id']}", archive, need["size"], release["sha256"])
    proof_args = ("--repo", sdk.REPO, "--format", "json")
    for command, argv in (("verify", ()), ("verify-asset", (str(archive),))):
        result = donor.gh_json("release", command, tag, *argv, *proof_args)["verificationResult"]
        s.m.save(proof / (command + ".json"), result)
        assert result["signature"]["certificate"]["subjectAlternativeName"] == "https://dotcom.releases.github.com"
        statement = result["statement"]
        assert statement["predicateType"] == "https://in-toto.io/attestation/release/v0.2"
        predicate = statement["predicate"]
        assert predicate["repository"] == sdk.REPO and predicate["tag"] == tag
        assert int(predicate["databaseId"]) == release["release_id"]
        named = {x["name"]: x["digest"]["sha256"] for x in statement["subject"] if "name" in x}
        tagged = [x for x in statement["subject"] if "uri" in x]
        assert len(statement["subject"]) == 10 and named.keys() == assets.keys()
        assert all(assets[name]["digest"] == "sha256:" + digest for name, digest in named.items())
        assert tagged == [{"uri": f"pkg:github/{sdk.REPO}@{tag}", "digest": {"sha1": release["coordinator"]}}]
        assert named[tag + ".json"] == release["manifest_sha256"]
    assert s.m.read(proof / "verify.json")["statement"] == s.m.read(proof / "verify-asset.json")["statement"]
    return archive


def production(role, donor, proof, temp):
    expected = s.lock["builders"][role]
    source = s.SOURCES[role]
    assert expected["sdk"]["name"] == "rc23-22958-sdk-" + expected["role"]
    assert expected["qa"]["name"] == "rc23-22958-qa-" + expected["role"] + "-attempt-1"
    route = f"repos/{sdk.REPO}/actions/runs/{expected['run']}"
    run = donor.gh_json("api", route)
    jobs = donor.gh_json("api", route + "/attempts/1/jobs?per_page=100")
    artifacts = donor.gh_json("api", route + "/artifacts?per_page=100")
    for name, row in (("run", run), ("jobs", jobs), ("artifacts", artifacts)):
        s.m.save(proof / (name + ".json"), row)
    assert run["id"] == expected["run"] and run["head_sha"] == expected["head"]
    assert run["head_branch"] == expected["branch"] and run["event"] == "workflow_dispatch"
    assert run["run_attempt"] == 1 and run["status"] == "completed" and run["conclusion"] == "success"
    assert run["repository"]["id"] == run["head_repository"]["id"] == 1319437234
    assert jobs["total_count"] == len(jobs["jobs"])
    job, = [row for row in jobs["jobs"] if row["id"] == expected["job"]]
    assert job["run_id"] == run["id"] and job["head_sha"] == run["head_sha"] and job["run_attempt"] == 1
    assert job["status"] == "completed" and job["conclusion"] == "success"
    by_name = {row["name"]: row for row in artifacts["artifacts"]}
    assert len(by_name) == artifacts["total_count"] == len(artifacts["artifacts"])
    archive = temp / (role + "-compiler.tar.gz")
    for kind in ("qa", "sdk"):
        spec = expected[kind]
        actual = by_name[spec["name"]]
        assert all(actual[key] == spec[key] for key in ("id", "name", "size_in_bytes", "digest"))
        assert actual["digest"].startswith("sha256:") and not actual["expired"]
        origin = actual["workflow_run"]
        assert origin["id"] == run["id"] and origin["head_sha"] == run["head_sha"]
        assert origin["repository_id"] == origin["head_repository_id"] == 1319437234
        dst = temp / (role + "-" + kind + ".zip")
        donor.gh_bytes(f"repos/{sdk.REPO}/actions/artifacts/{actual['id']}/zip", dst,
                       actual["size_in_bytes"], actual["digest"][7:])
        if kind == "qa":
            continue
        members = expected["sdk_members"]
        assert set(members) == {"source.json", "role.json", "sdk-inventory.json", "component-inventory.json", "SHA256SUMS"}
        with ZipFile(dst) as z:
            files = [q for q in z.infolist() if not q.is_dir()]
            assert len(files) == 6 and {q.filename for q in files} == {*members, "ohm.tar.gz"}
            for member in files:
                name = member.filename
                assert PurePosixPath(name).name == name
                with z.open(member) as stream:
                    if name == "ohm.tar.gz":
                        assert member.file_size == expected["archive_bytes"]
                        sdk.copy_checked(stream, archive, member.file_size, expected["archive_sha256"])
                    else:
                        assert member.file_size < 32 << 20
                        sdk.copy_checked(stream, proof / name, member.file_size, members[name])
    checksums = {}
    for line in (proof / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert name not in checksums
        checksums[name] = digest
    assert checksums == {**{n: digest for n, digest in members.items() if n != "SHA256SUMS"},
                         "ohm.tar.gz": expected["archive_sha256"]}
    origin = s.m.read(proof / "source.json")
    material = origin["source"]
    native = s.m.read(proof / "role.json")
    assert origin["reviewed_head"] == expected["head"]
    assert origin["original_release"] == s.lock["signed_release"]["coordinator"]
    assert origin["qualified_parent"] == "dd1135def2413a18eb5894ca11d5f1f8d842b1fd"
    recipe = origin["release_files"]
    assert recipe["scripts/build-optimized-dist.sh"]["oid"] == "c5e690b7569c3f1ace17bfb3f2fb0ff6fa1ca414"
    assert recipe["release/rustc-perf-relocated-dependencies.patch"]["oid"] == "4e3627ebe0d56449e523fc4005041647b0678034"
    assert recipe["toolchains/1.99.0/23.json"]["sha256"] == s.lock["signed_release"]["manifest_sha256"]
    assert native["release_recipe"] == recipe and native["relocated_dependencies"] is True
    assert native["native_unit_and_runmake"] and native["installed_runmake"]
    assert all(material[key] == value for key, value in source.items())
    assert material["parent"] == s.lock["signed_release"]["rustc"]
    assert native["source_commit"] == source["commit"] and native["source_tree"] == source["tree"]
    assert native["epoch"] == source["epoch"] and native["metadata_epoch"] == source["metadata_epoch"]
    assert native["role"] == expected["role"] and native["bolt_note"] is True and native["execution_pgo"]
    assert native["effective_benchmark_cargo_sha256"] == s.lock["signed_cargo"]
    assert native["archive_sha256"] == expected["archive_sha256"] and native["archive_bytes"] == archive.stat().st_size
    assert s.m.read(proof / "sdk-inventory.json") == s.lock["raw"][role]
    return archive


def admit():
    workspace, tempdir, _ = s.host()
    out = workspace / "trait-results"
    proof = out / "intake"
    temp = tempdir / "release-22958-incoming"
    pool = tempdir / "uv22958-release-sdks"
    for directory in (proof, temp, pool):
        directory.mkdir()
    donor = sdk.transport()
    sdk.latest(proof / "latest.json")
    signed = official(donor, proof, temp)
    cargo = sdk.signed_cargo(signed, temp / "signed-23-cargo")
    installed = {}
    for role in s.ROLES:
        if role == "R":
            archive = signed
        else:
            role_proof = proof / ("production-" + role)
            role_proof.mkdir()
            archive = production(role, donor, role_proof, temp)
        root = pool / role
        sdk.install_archive(archive, root, role)
        assert s.m.filesha(root / "bin/cargo") == s.lock["raw"][role]["bin/cargo"]["sha256"]
        shutil.copy2(cargo, root / "bin/cargo")
        installed[role] = sdk.role_sdk(role, root, proof / "role-material" / role)
    s.m.save(out / "intake.json", {"installed": installed, "signed_cargo_sha256": s.lock["signed_cargo"],
                                    "release_lock": s.m.filesha(s.LOCK_PATH)})
