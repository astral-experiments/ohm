"""Check that a signed release and a candidate reject each other's incremental cache."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def check(old, new, work, old_version, new_version):
    work.mkdir()
    cache = work / "cache"
    payload = work / "payload.bin"
    binary = work / "probe"
    (work / "main.rs").write_text('fn main() { println!("{}", include_bytes!("payload.bin")[35000]); }\n')
    outcomes = []

    def graphs(root):
        found = {}
        for graph in root.glob("*/s-*/dep-graph.bin"):
            with graph.open("rb") as stream:
                header = stream.read(6)
            assert len(header) == 6 and header[:4] == b"RSIC", graph
            found[str(graph.relative_to(root))] = int.from_bytes(header[4:], "little")
        assert found, root
        return found

    def compile_with(sdk, state, version, expected):
        command = [sdk / "bin/rustc", "--sysroot", sdk, "main.rs", "-C", "incremental=cache",
                   "-Zassert-incr-state=" + state, "-o", binary]
        subprocess.run(command, cwd=work, env=dict(os.environ, RUSTC_BOOTSTRAP="1"), check=True)
        value = int(subprocess.check_output([binary], cwd=work))
        headers = graphs(cache)
        assert value == expected and version in headers.values(), (value, expected, headers)
        outcomes.append(dict(compiler=str(sdk), state=state, result=value, graphs=headers))
        return headers

    def snapshot(name, version):
        headers = graphs(cache)
        assert set(headers.values()) == {version}
        namespaces = {Path(path).parts[0] for path in headers}
        assert len(namespaces) == 1, namespaces
        dest = work / name
        cache.rename(dest)
        return dest / namespaces.pop()

    def seed(source, dest_namespace, version):
        # Give rustc exactly one cache to inspect, under the name it has already used.
        cache.mkdir()
        shutil.copytree(source, cache / dest_namespace)
        found = graphs(cache)
        assert set(found.values()) == {version}, found
        outcomes.append(dict(seeded_from=source.name, seeded_as=dest_namespace, graphs=found))

    payload.write_bytes(bytes([17]) * 70000)
    compile_with(old, "not-loaded", old_version, 17)
    compile_with(old, "loaded", old_version, 17)
    signed_cache = snapshot("signed", old_version)
    compile_with(new, "not-loaded", new_version, 17)
    compile_with(new, "loaded", new_version, 17)
    candidate_cache = snapshot("candidate", new_version)
    payload.write_bytes(bytes([29]) * 70000)
    seed(signed_cache, candidate_cache.name, old_version)
    compile_with(new, "not-loaded", new_version, 29)
    compile_with(new, "loaded", new_version, 29)
    payload.write_bytes(bytes([41]) * 70000)
    compile_with(new, "loaded", new_version, 41)
    cache.rename(work / "after-upgrade")
    seed(candidate_cache, signed_cache.name, new_version)
    compile_with(old, "not-loaded", old_version, 41)
    compile_with(old, "loaded", old_version, 41)
    return outcomes


if __name__ == "__main__":
    signed, candidate, work, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(check(signed, candidate, work, 26655, 57124), indent=2) + "\n")
