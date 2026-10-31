"""Hold the declared input fixed and replace an additional, Rust-declared archive in place."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys


root = Path(sys.argv[2]).resolve()
role = sys.argv[1]
assert role in ("225", "328")
assert role == "225"
lane = root / f"mixed-declared-{role}"
lane.mkdir()
project = lane / "reader"
project.mkdir()
original = Path(sys.argv[4]).resolve()
for f in ("Cargo.toml", "build.rs", "count-links"):
    shutil.copy2(original / f, project / f)
shutil.copytree(original / "engine/src", project / "engine/src")
shutil.copy2(original / "engine/Cargo.toml", project / "engine/Cargo.toml")
(project / "src/bin").mkdir(parents=True)
(project / "native").mkdir()
for name in ("first", "second"):
    (project / f"src/bin/{name}.rs").write_text(
        'extern "C" { fn answer() -> i32; }\n'
        '#[link(name="extra", kind="static", modifiers="-bundle")]\n'
        'extern "C" { fn extra() -> i32; }\n'
        'fn main() { println!("{}:{}", engine::register(unsafe { answer() } as usize), unsafe { extra() }); }\n')
env = {k: v for k, v in os.environ.items() if not k.startswith(("CARGO_", "RUST", "OHM_", "LLVM_"))}
env.update(CARGO_HOME=str(lane / "cargo-home"), RUSTUP_HOME=sys.argv[3],
           TMPDIR=str(lane / "tmp"), CARGO_INCREMENTAL="1",
           CARGO_TARGET_DIR=str(project / "target"), CARGO_BUILD_BUILD_DIR=str(project / "build"),
           **{"CARGO_TARGET_" + sys.argv[5].upper().replace("-", "_") + "_LINKER":str(project / "count-links")})
for d in ("tmp", "cargo-home", "members"):
    (lane / d).mkdir()
records = []


def contents(name, value):
    stage = lane / "members" / f"{name}-{value}"
    stage.mkdir()
    subprocess.run(["cc", "-x", "c", "-c", "-o", name + ".o", "-"], cwd=stage,
                   input=f"int {name}(void) {{ return {value}; }}\n".encode(), check=True)
    subprocess.run(["ar", "rcs", "output.a", name + ".o"], cwd=stage, check=True)
    return (stage / "output.a").read_bytes()


def snapshot(path):
    st = path.stat()
    return {"dev": st.st_dev, "ino": st.st_ino, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def run(name):
    stage = lane / name
    stage.mkdir()
    links = stage / "links"
    links.write_bytes(b"")
    env["OHM_SMOKE_LINK_LOG"] = str(links)
    with (stage / "build.log").open("xb") as out:
        rc = subprocess.run(["cargo", "+ohm-native-proof", "build", "--bins", "--offline", "-vv"],
                            cwd=project, env=env, stdout=out, stderr=subprocess.STDOUT).returncode
    values = [] if rc else [subprocess.check_output([project / "target/debug" / f], text=True).strip()
                             for f in ("first", "second")]
    records.append({"stage": name, "code": rc, "calls": len(links.read_text().splitlines()), "values": values})


declared = project / "native/libanswer.a"
hidden = project / "native/libextra.a"
declared.write_bytes(contents("answer", 17))
hidden.write_bytes(contents("extra", 3))
declared_before, hidden_before = snapshot(declared), snapshot(hidden)
run("initial")
run("unchanged")
replacement = contents("extra", 9)
assert len(replacement) == hidden_before["size"] and replacement != hidden.read_bytes()
st = hidden.stat()
with hidden.open("r+b") as f:
    f.write(replacement)
    f.flush()
    os.fsync(f.fileno())
os.utime(hidden, ns=(st.st_atime_ns, st.st_mtime_ns))
hidden_after = snapshot(hidden)
assert all(hidden_before[k] == hidden_after[k] for k in ("ino", "dev", "size", "mtime_ns"))
assert hidden_before["sha256"] != hidden_after["sha256"] and snapshot(declared) == declared_before
run("replace-hidden")
run("repeat-hidden")
(project / "target").rename(project / "retained-warm-target")
(project / "build").rename(project / "retained-warm-build")
run("clean-reference")
assert records[0]["values"] == ["17:3"] * 2 and records[-1]["values"] == ["17:9"] * 2
expected = "17:9" if role == "225" else "17:3"
assert records[2]["values"] == [expected] * 2, records
result = {"role": role, "source": "One script-declared archive plus one #[link] archive in the same directory.",
          "declared": declared_before, "hidden_before": hidden_before, "hidden_after": hidden_after, "records": records}
(lane / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(records)
