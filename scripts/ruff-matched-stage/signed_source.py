"""Install the four official -23 Git snapshots over the verified precursor in this disposable worker."""

import hashlib
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
COORDINATOR = "9c2397d36f033900a0864484714d526788d1dc77"
NAMES = ("rust", "cargo", "clippy", "rustfmt")


def need(ok, why):
    if not ok:
        raise ValueError(why)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "--no-lazy-fetch", "-C", repo, *args], text=True).strip()


def install(repo, role, pin):
    before, after = pin["before"], pin["after"]
    need(git(repo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() == [before, pin["before_tree"]], role)
    folder = HERE / "canonical-pins"
    packet = folder / (role + ".pack")
    need(pin["pack"] == packet.name and packet.stat().st_size == pin["bytes"] and digest(packet) == pin["sha256"], packet)
    with packet.open("rb", buffering=0) as src:
        header = src.read(12)
        need(header[:8] == b"PACK\0\0\0\2" and int.from_bytes(header[8:], "big") == pin["object_count"], header)
        src.seek(0)
        written = subprocess.check_output(["git", "--no-lazy-fetch", "-C", repo, "index-pack", "--stdin"],
                                          stdin=src, text=True).split()
    need(len(written) == 2 and written[0] == "pack" and written[1] == pin["git_pack_sha1"], written)
    index = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects/pack/pack-" + written[1] + ".idx"))
    with index.open("rb") as inp:
        ids = [row.split()[1] for row in subprocess.check_output(["git", "show-index"], stdin=inp, text=True).splitlines()]
    roster = folder / (role + ".objects.json")
    need(roster.name == pin["objects"] and digest(roster) == pin["objects_sha256"], roster)
    objects = json.loads(roster.read_bytes())["objects"]
    need(ids == [row[0] for row in objects] and len(ids) == pin["object_count"], "different indexed pack objects")
    typed = subprocess.check_output(["git", "--no-lazy-fetch", "-C", repo, "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                                    input="".join(oid + "\n" for oid in ids), text=True)
    need([r.split() for r in typed.splitlines()] == objects, "different object type")
    gitlinks = folder / (role + ".gitlinks.json")
    need(gitlinks.name == pin["gitlinks"] and digest(gitlinks) == pin["gitlinks_sha256"], gitlinks)
    links = json.loads(gitlinks.read_bytes())
    for side, revision in (("before", before), ("after", after)):
        lines = git(repo, "ls-tree", "-r", revision).splitlines()
        gitlink = [line.split("\t", 1) for line in lines if line.startswith("160000 commit ")]
        need([[path, header.split()[2]] for header, path in gitlink] == links[side], "different gitlink set")
    need(git(repo, "rev-parse", after + "^{commit}", after + "^{tree}").splitlines() == [after, pin["tree"]], role)
    commit = git(repo, "cat-file", "-p", after).split("\n\n", 1)[0]
    parents = re.findall(r"^parent ([0-9a-f]{40})$", commit, re.MULTILINE)
    need(parents and parents == pin["after_parents"], "different original parent header")
    shallow = any(subprocess.run(["git", "--no-lazy-fetch", "-C", repo, "cat-file", "-e", p + "^{commit}"],
                                 stderr=subprocess.DEVNULL).returncode != 0 for p in parents)
    if shallow:
        path = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-path", "shallow"))
        workspace = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
        need(path.resolve().is_relative_to(workspace), "shallow boundary escaped the disposable checkout")
        prior = path.read_text().splitlines() if path.exists() else []
        need(all(re.fullmatch("[0-9a-f]{40}", p) for p in prior), path)
        if after not in prior:
            with path.open("a") as refs:
                refs.write(after + "\n")
    return {"before": before, "after": after, "tree": pin["tree"], "parents": parents, "shallow": shallow,
            "sha256": pin["sha256"], "objects": pin["object_count"]}


def main():
    work = Path(os.environ["GITHUB_WORKSPACE"]).resolve()
    root = Path(os.environ["RUNNER_TEMP"]) / "ohm-branch-object-qa/logs"
    qa = work / "qa-code"
    need(os.environ["GITHUB_REPOSITORY"] == "astral-experiments/ohm" and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
         and os.environ["GITHUB_SHA"] == os.environ["REVIEWED_HEAD"] == git(qa, "rev-parse", "HEAD")
         and HERE == qa / "scripts/ruff-matched-stage", "wrong QA checkout")
    stage = json.loads((root / "source-precursor.json").read_bytes())
    need(stage["qa"] == os.environ["GITHUB_SHA"] and stage["run"] == os.environ["GITHUB_RUN_ID"], "wrong precursor")
    official = work / "signed-coordinator"
    need(git(official, "rev-parse", "HEAD") == COORDINATOR, "wrong release coordinator")
    manifest = official / "toolchains/1.99.0/23.json"
    releases = json.loads(manifest.read_bytes())
    need(releases["status"] == "pinned" and releases["release"]["toolchain_name"] == "ohm-1.99.0-23", manifest)
    registered = HERE / "canonical-pins/pins.json"
    need(digest(registered) == "5bd733f3963697b8f78ec1495b82ec0ee700894d347afe73a2131379292b226f", "different signed source registration")
    pins = json.loads(registered.read_bytes())
    need(set(pins) == set(NAMES) == set(releases["sources"]), "unexpected release sources")
    rust = work / "source/rust"
    repos = {"rust":rust, **{n:rust / "src/tools" / n for n in NAMES[1:]}}
    report = {}
    for name, repo in repos.items():
        need(stage["source"][name] == pins[name]["before"] and releases["sources"][name]["revision"] == pins[name]["after"], name)
        report[name] = install(repo, name, pins[name])
    # Clippy and rustfmt replace tracked outer source directories on Ohm's release checkout.
    for name in ("clippy", "rustfmt"):
        repos[name].rename(rust.parent / ("signed-donor-" + name))
    git(rust, "restore", "--source=HEAD", "--worktree", "--", "src/tools/clippy", "src/tools/rustfmt")
    git(rust, "checkout", "--no-recurse-submodules", "--quiet", "--detach", pins["rust"]["after"])
    for name in ("clippy", "rustfmt"):
        repos[name].rename(rust.parent / ("signed-outer-" + name))
        (rust.parent / ("signed-donor-" + name)).rename(repos[name])
    for name in NAMES[1:]:
        git(repos[name], "checkout", "--no-recurse-submodules", "--quiet", "--detach", pins[name]["after"])
    path = work / "legacy/scripts/dep-graph-slots/layout.py"
    module = importlib.util.spec_from_file_location("checked_layout", path)
    layout = importlib.util.module_from_spec(module)
    module.loader.exec_module(layout)
    subs = {"src/tools/" + n:(pins[n]["after"], pins[n]["tree"]) for n in ("clippy", "rustfmt")}
    actual = layout.checked(rust, pins["rust"]["after"], pins["rust"]["tree"], subs)
    need(len(actual["gitlinks"]) == 12 and actual["gitlinks"]["src/tools/cargo"]["commit"] == pins["cargo"]["after"],
         "different enrolled Cargo or gitlink set")
    verified = subprocess.check_output([official / "scripts/verify-release-sources.sh", manifest, *repos.values()], text=True)
    source = {n:git(repos[n], "rev-parse", "HEAD") for n in NAMES}
    with (root / "source.json").open("x") as stream:
        print(json.dumps({"source":source, "layout":actual, "qa":stage["qa"], "run":stage["run"], "coordinator":COORDINATOR,
                          "manifest_sha256":digest(manifest), "source_verifier":verified, "install":report,
                          "precursor_sha256":digest(root / "source-precursor.json"), "attempt":os.environ["GITHUB_RUN_ATTEMPT"]},
                         sort_keys=True, indent=2), file=stream)


if __name__ == "__main__":
    main()
