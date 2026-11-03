"""Check on-disk cache upgrades against a signed compiler and the candidate."""
import json
import os
from pathlib import Path
import subprocess


def check(old, new, work, old_version, new_version):
    work.mkdir()
    cache = work / "cache"
    payload = work / "payload.bin"
    source = work / "main.rs"
    binary = work / "probe"
    source.write_text('fn main() { println!("{}", include_bytes!("payload.bin")[35000]); }\n')
    outcomes = []

    def compile_with(sdk, state, version, expected):
        command = [sdk / "bin/rustc", "--sysroot", sdk, "main.rs", "-C", "incremental=cache",
                   "-Zassert-incr-state=" + state, "-o", binary]
        subprocess.run(command, cwd=work, env=dict(os.environ, RUSTC_BOOTSTRAP="1"), check=True)
        value = int(subprocess.check_output([binary], cwd=work))
        assert value == expected, (value, expected)
        graphs = list(cache.glob("*/s-*/dep-graph.bin"))
        assert graphs, cache
        actual = []
        for graph in graphs:
            with graph.open("rb") as stream:
                header = stream.read(6)
            assert header[:4] == b"RSIC", (graph, header)
            actual.append(int.from_bytes(header[4:], "little"))
        assert version in actual, (version, actual)
        outcomes.append(dict(compiler=str(sdk), state=state, result=value, cache_headers=actual))

    payload.write_bytes(bytes([17]) * 70000)
    compile_with(old, "not-loaded", old_version, 17)
    compile_with(old, "loaded", old_version, 17)
    compile_with(new, "not-loaded", new_version, 17)
    compile_with(new, "loaded", new_version, 17)
    payload.write_bytes(bytes([29]) * 70000)
    compile_with(new, "loaded", new_version, 29)
    compile_with(old, "not-loaded", old_version, 29)
    compile_with(old, "loaded", old_version, 29)
    return outcomes


if __name__ == "__main__":
    import sys
    signed, candidate, work, output = map(Path, sys.argv[1:])
    result = check(signed, candidate, work, 26655, 57124)
    output.write_text(json.dumps(result, indent=2) + "\n")
