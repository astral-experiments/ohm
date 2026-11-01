"""Offline reconstruction from both downloaded original Actions artifacts."""

import hashlib
import gzip
import json
from pathlib import Path
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jobserver
import products


def member(archive, suffix):
    names = [n for n in archive.namelist() if n == suffix or n.endswith("/" + suffix)]
    products.need(len(names) == 1, "missing or duplicate member " + suffix)
    return names[0]


def blob(archive, suffix):
    return archive.read(member(archive, suffix))


def read(archive, suffix):
    return json.loads(blob(archive, suffix))


def original_inputs(original):
    prefix = "archives/original/"
    seed = read(original, prefix + "seed.json")
    name = member(original, prefix + "before-B-source-and-A-session.tar.gz")
    size = original.getinfo(name).file_size
    with original.open(name) as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    products.need(
        [size, digest] == [seed["complete_archive"][k] for k in ("size", "sha256")], "corrupt seed archive"
    )
    inventory = read(original, prefix + "before-B-source-and-A-session.tar.inventory.json")
    import capture

    products.need(
        capture.projection(inventory["entries"]) == seed["normalized"], "different original full source/workspace"
    )
    seen = set()
    with original.open(name) as stream, tarfile.open(fileobj=stream, mode="r|gz") as tar:
        for item in tar:
            products.need(
                item.name in inventory["entries"] and item.name not in seen, "foreign original seed member"
            )
            row = inventory["entries"][item.name]
            seen.add(item.name)
            products.need(item.mode == row["mode"], "original file mode")
            if item.isfile():
                with tar.extractfile(item) as f:
                    actual = hashlib.file_digest(f, "sha256").hexdigest()
                products.need(item.size == row["size"] and actual == row["sha256"], "corrupt original seed bytes")
            elif item.islnk():
                target = inventory["entries"][item.linkname]
                products.need(
                    item.linkname in seen and (row["dev"], row["ino"]) == (target["dev"], target["ino"]),
                    "foreign hardlinked seed",
                )
            else:
                products.need(
                    (row["type"] == "dir" and item.isdir()) or (item.issym() and row["target"] == item.linkname),
                    "bad seed type",
                )
    products.need(seen == set(inventory["entries"]), "incomplete original seed")
    return seed


def libraries(archive, prefix):
    reported = read(archive, prefix + "/members.json")
    paths = reported["paths"]
    bodies = [blob(archive, prefix + "/" + Path(name).name) for name in paths]
    actual = products.archive(*bodies) | {"paths": paths}
    products.need(actual == reported, "cannot reproduce raw native archives/members/metadata")
    return reported, bodies[0]


def natural_evidence(original, first, seed, library):
    import capture
    from identity import HEALTHY_A, PATCHED_B
    from intake import BIND

    roots = sorted(
        {n.rsplit("/", 1)[0] for n in original.namelist() if "/events/" in n and n.endswith("/before.json")}
    )
    stages = []
    for prefix in roots:
        before, during, after = (
            read(original, prefix + "/" + phase + ".json") for phase in ("before", "running", "after")
        )
        products.need(
            before["wrapper"] == during["wrapper"] == after["wrapper"] == int(prefix.rsplit("/", 1)[1])
            and before["pid"] == 0
            and after["pid"] == during["pid"] > 0
            and after["code"] == 0,
            "natural compiler lifecycle mismatch",
        )
        products.need(
            all(before[k] == after[k] for k in ("source_sha256", "source", "incremental", "argv", "cwd"))
            and before["source_sha256"] == {"A": HEALTHY_A, "B": PATCHED_B}[before["source"]]
            and [during["process"][k] for k in ("size", "sha256")] == BIND["tools"]["rustc"],
            "natural compiler or source mismatch",
        )
        signatures = {
            "default_" + v + "_" + str(after["pid"]) + ".profraw"
            for v in BIND["prior_evidence"]["runtime_profile_signatures"]
        }
        products.need(signatures <= after["profile_files"].keys(), "missing natural instrumented module")
        for name, (size, sha) in after["profile_files"].items():
            entry = member(original, "focused/native-profiles/" + name)
            with original.open(entry) as f:
                products.need(
                    original.getinfo(entry).file_size == size
                    and hashlib.file_digest(f, "sha256").hexdigest() == sha,
                    "changed natural runtime module",
                )
        stages.append((before, after, prefix))
    stages.sort(key=lambda s: s[0]["monotonic_ns"])
    shape = [(b["source"], b["incremental"]) for b, _, _ in stages]
    products.need(
        shape in ([("A", False), ("A", True), ("B", True)], [("A", False), ("A", True), ("A", True), ("B", True)]),
        "different natural native compiler sequence",
    )
    before, after, prefix = stages[-1]
    products.need(
        before == first["before"]
        and after["pid"] == first["native_pid"]
        and len(before["graphs"]) == 1
        and stages[-2][1]["graphs"] == before["graphs"]
        and stages[-2][1]["outputs"] == seed["initial_outputs"],
        "B seed differs from real preceding A writer",
    )
    products.need(
        after["outputs"]
        == dict(
            zip(
                (Path(p).name for p in library["paths"]),
                (library["archive"], library["standalone_metadata"]),
                strict=True,
            )
        ),
        "natural B hashes differ from returned physical products",
    )
    stderr = blob(original, prefix + "/rustc.stderr")
    capture.emitted(before["argv"], stderr)
    products.need(
        b"failed to connect to jobserver" not in stderr
        and read(original, "focused/natural.json") == first["collector"],
        "different natural collector or jobserver verdict",
    )


def check(original, replays):
    import capture
    from intake import BIND

    seed = original_inputs(original)
    first = read(original, "archives/original/completed.json")
    workflow = read(original, "archives/original/workflow.json")
    previous = json.loads((HERE / "previous.json").read_bytes())
    products.need(
        workflow["GITHUB_REPOSITORY"] == previous["repository"]
        and workflow["GITHUB_REF"] == "refs/heads/" + previous["trial_branch"]
        and workflow["GITHUB_RUN_ATTEMPT"] == "1"
        and workflow["RUNNER_OS"] == "macOS"
        and workflow["RUNNER_ARCH"] == "ARM64",
        "wrong original native worker",
    )
    products.need(all(first[k] == BIND["tools"][k] for k in ("rustc", "driver", "cargo")), "wrong source toolchain")
    natural, raw = libraries(original, "archives/original/natural-B")
    natural_evidence(original, first, seed, natural)
    libs = {"natural": natural}
    bodies = {"natural": raw}
    prior_inodes = set()
    r = first["before"]
    handoff = read(replays, "replays/claimed.json")
    products.need(
        jobserver.identity(first["natural_jobserver"]["descriptors"]) == jobserver.identity(handoff["claim"]),
        "different kernel endpoints",
    )
    for role in ("ordinary-1", "ordinary-2", "loaded", "cold", "closed-fds"):
        prefix = "replays/" + role + "/"
        inc = read(replays, prefix + "incoming.json")
        start = read(replays, prefix + "exec.json")
        done = read(replays, prefix + "complete.json")
        active = read(replays, prefix + "actual-process.json")
        data, bodies[role] = libraries(replays, prefix + "products")
        libs[role] = data
        inputs = json.loads(gzip.decompress(blob(replays, prefix + "incoming-files.json.gz")))
        products.need(
            capture.projection(inputs) == seed["normalized"], "different pristine input bytes or topology"
        )
        ids = {(v["dev"], v["ino"]) for v in inputs.values() if v["type"] == "file"}
        products.need(ids and not prior_inodes.intersection(ids), "pristine inputs alias a previous turn")
        prior_inodes.update(ids)
        products.need(
            inc["normalized"] == seed["normalized"]
            and inc["original_outputs"] == seed["initial_outputs"]
            and bool(inc["cold_unit_reset"]) == (role == "cold"),
            "different initial unit products/session",
        )
        products.need(
            start["argv"]
            == done["argv"]
            == r["argv"] + (["-Zassert-incr-state=loaded"] if role == "loaded" else [])
            and start["env"] == r["environment"]
            and start["cwd"] == r["cwd"] == done["cwd"] == inc["cwd"],
            "different real command",
        )
        products.need(
            done["pid"] == active["pid"] == start["pid"]
            and active["code"] == 0
            and active["physical"]["kernel"]["sha256"] == first["rustc"][1],
            "unattributed reader",
        )
        if role == "closed-fds":
            products.need(start["fds"] is None, "closed control retained the pipe")
        else:
            products.need(
                jobserver.identity(start["fds"]) == jobserver.identity(handoff["claim"]),
                "direct pipe identity mismatch",
            )
        products.need(
            (b"failed to connect to jobserver" in blob(replays, prefix + "stderr"))
            == done["bad_jobserver_warning"]
            == (role == "closed-fds"),
            "incorrect jobserver diagnostic",
        )
        expected = {
            "default_" + v + "_" + str(done["pid"]) + ".profraw"
            for v in BIND["prior_evidence"]["runtime_profile_signatures"]
        }
        products.need(expected <= done["profiles"].keys(), "missing an instrumented PID/module")
        capture.emitted(start["argv"], blob(replays, prefix + "stderr"))
        for name, (size, sha) in done["profiles"].items():
            entry = member(replays, prefix + "profiles/" + name)
            with replays.open(entry) as f:
                products.need(
                    replays.getinfo(entry).file_size == size
                    and hashlib.file_digest(f, "sha256").hexdigest() == sha,
                    "wrong physical module",
                )
        products.need(
            [data["archive"], data["standalone_metadata"]] == [done["archive"], done["metadata"]],
            "different returned bodies",
        )
    comparisons = {
        a + " vs " + b: products.compare(x, libs[b])
        for i, (a, x) in enumerate(libs.items())
        for b in list(libs)[i + 1 :]
    }
    products.need(comparisons == read(replays, "replays/comparison.json"), "raw comparison differs")
    proof = {
        a + " vs " + b: products.suffix_proof(bodies[a], bodies[b], x, libs[b])
        for i, (a, x) in enumerate(libs.items())
        for b in list(libs)[i + 1 :]
    }
    products.need(proof == read(replays, "replays/name-proof.json"), "literal reconstruction differs")
    return {
        "workflow": workflow,
        "complete_original_seed": seed["normalized"],
        "all_disjoint_regular_inputs": len(prior_inodes),
        "libraries": {k: [v["archive"], v["standalone_metadata"]] for k, v in libs.items()},
        "comparisons": comparisons,
        "name_proof": proof,
    }


if __name__ == "__main__":
    with zipfile.ZipFile(sys.argv[1]) as original, zipfile.ZipFile(sys.argv[2]) as replays:
        print(json.dumps(check(original, replays), indent=2, sort_keys=True))
