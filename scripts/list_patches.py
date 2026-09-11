#!/usr/bin/env python3
"""Print the component commits included by an Ohm release manifest."""

import argparse
import json
from pathlib import Path
import re
import subprocess


def api(endpoint):
    return json.loads(subprocess.check_output(["gh-auto", "api", endpoint], text=True))


def commits(repository, base, head):
    """Read the full comparison and reject a base outside the release ancestry."""
    result = []
    page = 1
    while True:
        comparison = api(
            f"repos/{repository}/compare/{base}...{head}?per_page=100&page={page}"
        )
        if comparison["behind_by"] or comparison["base_commit"]["sha"] != base:
            raise ValueError(f"{repository}: upstream revision is not an ancestor")
        result.extend(comparison["commits"])
        if len(result) >= comparison["total_commits"]:
            if len(result) != comparison["total_commits"] or len(
                {c["sha"] for c in result}
            ) != len(result):
                raise ValueError(f"{repository}: inconsistent paginated comparison")
            return result
        if not comparison["commits"]:
            raise ValueError(f"{repository}: incomplete comparison")
        page += 1


def subtree_base(repository, head, tree):
    """Clippy and rustfmt are vendored trees, not Rust Git submodules."""
    page = 1
    while True:
        history = api(f"repos/{repository}/commits?sha={head}&per_page=100&page={page}")
        for commit in history:
            if commit["commit"]["tree"]["sha"] == tree:
                return commit["sha"]
        if not history:
            raise ValueError(
                f"{repository}: no ancestor matches the upstream source tree"
            )
        page += 1


def inventory(manifest):
    version = manifest["release"]["upstream_rust_version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid upstream Rust version")
    rust = api(f"repos/rust-lang/rust/commits/{version}")["sha"]
    tools = api(f"repos/rust-lang/rust/contents/src/tools?ref={rust}")
    bases = {item["name"]: item for item in tools}
    bases["rust"] = {"sha": rust, "type": "file"}
    sections = [f"# Patches in {manifest['release']['toolchain_name']}"]
    for component, source in manifest["sources"].items():
        repository = source["repository"].removeprefix("https://github.com/")
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository) or not re.fullmatch(
            r"[0-9a-f]{40}", source["revision"]
        ):
            raise ValueError("Expected a GitHub repository and pinned source commit")
        upstream, head = bases[component], source["revision"]
        base = upstream["sha"]
        if upstream["type"] == "dir":
            base = subtree_base(repository, head, base)
        patches = commits(repository, base, head)
        sections.append(
            f"## {repository}\n\n[{base[:12]}…{head[:12]}](https://github.com/{repository}/compare/{base}...{head}) — {len(patches)} commits\n"
        )
        for commit in patches:
            title = (
                commit["commit"]["message"]
                .splitlines()[0]
                .replace("[", r"\[")
                .replace("]", r"\]")
            )
            sections.append(
                f"- [{commit['sha'][:8]}: {title}](https://github.com/{repository}/commit/{commit['sha']})"
            )
    return "\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(inventory(json.loads(args.manifest.read_text())), end="")


if __name__ == "__main__":
    main()
