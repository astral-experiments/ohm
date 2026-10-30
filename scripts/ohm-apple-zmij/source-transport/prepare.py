"""Reconstruct the original parent and candidate Git objects from public Rust."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


PACKET = Path(__file__).resolve().parent
SOURCE = json.loads((PACKET / "source.json").read_text())
BUNDLE = PACKET / "ohm-rust.bundle"
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GH_", "GITHUB_"))}
ENV.pop("SSH_AUTH_SOCK", None)
ENV.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")


def git(repository, *args):
    return subprocess.check_output(
        ["git", "-C", repository, "-c", "credential.helper=", "-c", "gc.auto=0", *args],
        env=ENV, text=True,
    ).strip()


def require(actual, expected, name):
    if actual != expected:
        raise SystemExit(f"{name} differs: expected {expected!r}, got {actual!r}")


def prepare(destination):
    bundle_data = BUNDLE.read_bytes()
    require(len(bundle_data), SOURCE["bundle_size"], "bundle length")
    require(hashlib.sha256(bundle_data).hexdigest(), SOURCE["bundle_sha256"], "bundle SHA-256")
    destination.mkdir()
    git(destination, "init", "--template=", "-q", "-b", "ohm-qa-candidate")
    base = SOURCE["public_revision"]
    parent = SOURCE["parent_revision"]
    candidate = SOURCE["candidate_revision"]
    git(destination, "fetch", "--no-tags", "--no-recurse-submodules", f"--depth={SOURCE['public_depth']}",
        SOURCE["public_repository"], f"{base}:refs/heads/ohm-public-seed")
    require(git(destination, "rev-parse", "ohm-public-seed^{tree}"), SOURCE["public_tree"], "public tree")
    require(git(destination, "bundle", "list-heads", BUNDLE), f"{candidate} {SOURCE['ref']}", "bundle ref")
    git(destination, "bundle", "verify", BUNDLE)
    git(destination, "fetch", "--no-tags", "--no-recurse-submodules", BUNDLE,
        f"{SOURCE['ref']}:refs/remotes/qualification/candidate")
    git(destination, "checkout", "--quiet", "-B", "ohm-qa-candidate", candidate)
    require(git(destination, "rev-parse", "HEAD^"), parent, "candidate parent")
    require(git(destination, "rev-list", "--count", f"{base}..HEAD"), str(SOURCE["fork_commits"]), "fork commits")
    for revision, name in [(parent, "parent"), (candidate, "candidate")]:
        require(git(destination, "rev-parse", f"{revision}^{{tree}}"), SOURCE[f"{name}_tree"], f"{name} tree")
        rows = git(destination, "ls-tree", "-r", revision).splitlines()
        links = {r.split("\t")[1]: r.split()[2] for r in rows if r.startswith("160000 ")}
        require(links, SOURCE["gitlinks"], f"{name} gitlinks")
        # Bootstrap's non-upstream mode locates the upstream LLVM artifact via the merge bot.
        upstream = git(destination, "rev-list", "--author-date-order", "--author=bors@rust-lang\\.org", "-n1", revision)
        require(upstream, base, f"{name} upstream")
        llvm = git(destination, "rev-list", "--first-parent", "-n1", upstream, "--author=bors@rust-lang\\.org",
                   "--", *SOURCE["llvm_inputs"])
        require(llvm, SOURCE["llvm_upstream"], f"{name} LLVM key")
        git(destination, "diff", "--exit-code", "--quiet", llvm, revision, "--", *SOURCE["llvm_inputs"])
    backtrace = "library/backtrace"
    require(git(destination, "config", "-f", ".gitmodules", "--get", "submodule.library/backtrace.url"),
            SOURCE["backtrace_repository"], "backtrace URL")
    git(destination, "submodule", "update", "--init", "--depth", "1", "--", backtrace)
    require(git(destination / backtrace, "rev-parse", "HEAD", "HEAD^{tree}"),
            SOURCE["gitlinks"][backtrace] + "\n" + SOURCE["backtrace_tree"], "backtrace checkout")
    require(git(destination, "status", "--porcelain=v1", "--ignore-submodules=none"), "", "checkout")
    if (destination / ".git/objects/info/alternates").exists():
        raise SystemExit("Checkout unexpectedly uses an external object store")
    print(json.dumps({
        "parent": parent, "candidate": candidate, "public_base": base,
        "llvm_key": SOURCE["llvm_upstream"], "backtrace": SOURCE["gitlinks"][backtrace],
        "gitlinks": len(SOURCE["gitlinks"]), "fork_commits": SOURCE["fork_commits"],
        "bundle_sha256": SOURCE["bundle_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepare.py NEW-COMPILER-SOURCE-DIRECTORY")
    prepare(Path(sys.argv[1]).resolve())
