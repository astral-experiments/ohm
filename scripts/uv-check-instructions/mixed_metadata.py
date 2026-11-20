"""Compare a public-hash consumer against fresh checks as upstream metadata changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

rustc = Path(sys.argv[1]).resolve()
work = Path(sys.argv[2]).resolve()
consumer = """
use bridge::{Item, Pick};

pub fn pick(item: &Item) -> u32 { item.pick() }
pub const COUNT: usize = bridge::count();
pub const VALUE: [u8; COUNT] = [5; bridge::LIMIT];
pub async fn make() -> impl Pick { Item }
"""

def provider(ty, count, limit, attr):
    return f"""
pub trait Pick {{
    type Value;
    fn pick(&self) -> Self::Value;
}}
pub struct Item;
impl Pick for Item {{
    type Value = {ty};
    fn pick(&self) -> Self::Value {{ 5 }}
}}
pub const LIMIT: usize = {limit};
const fn inner() -> usize {{ {count} }}
{attr}
pub const fn count() -> usize {{ inner() }}
"""


# Keep each provider's crate identity fixed as its metadata format switches.
cases = [
    # provider hash, bridge hash, associated type, function body, limit, deprecation
    (False, False, "u32", 2, 2, False),
    (False, False, "u32", 2, 2, False),
    (False, False, "u8",  2, 2, False),
    (False, False, "u32", 3, 3, False),
    (False, False, "u32", 4, 3, False),
    (False, False, "u32", 4, 4, False),
    (False, False, "u32", 4, 4, True),
    (False, True,  "u32", 4, 4, True),
    (False, True,  "u8",  4, 4, True),
    (False, True,  "u32", 5, 5, False),
    (True,  True,  "u32", 5, 5, False),
    (True,  True,  "u32", 6, 5, False),
    (True,  True,  "u32", 6, 6, True),
    (True,  False, "u32", 6, 6, True),
    (True,  False, "u32", 7, 7, False),
    (True,  False, "u8",  7, 7, False),
    (True,  False, "u32", 8, 8, False),
    (False, False, "u32", 8, 8, False),
    (False, False, "u32", 9, 8, True),
    (False, False, "u32", 9, 9, True),
    (False, False, "u32", 2, 2, False),
]

def compile_crate(name, public, deps=(), extra=(), salt="fixed"):
    command = [rustc, name + ".rs", "--crate-type=lib", "--edition=2024", "--emit=metadata",
               "-Zohm-shared-stages", "-Zpublic-api-hash=" + ("yes" if public else "no"),
               "-Cmetadata=" + salt, "-Ldependency=.", *extra]
    for dep in deps:
        command.extend(["--extern", f"{dep}=lib{dep}.rmeta"])
    env = dict(os.environ, CARGO_PKG_VERSION="1.0.0", CARGO_PKG_NAME=name, RUSTC_BOOTSTRAP="1")
    result = subprocess.run(command, cwd=work, env=env, capture_output=True)
    if name != "consumer":
        assert result.returncode == 0, result.stderr.decode()
    return result

def observe(threads, rotate, i, warm):
    cache = "warm" if warm else "fresh"
    state = "loaded" if warm and i else "not-loaded"
    options = [f"-Zthreads={threads}", f"-Cincremental={cache}", f"-Zassert-incr-state={state}"]
    salt = str(i) if rotate else "fixed"
    result = compile_crate("consumer", True, ["bridge"], options, salt)
    obs = {"exit": result.returncode, "diagnostics": result.stderr.decode()}
    if result.returncode == 0:
        data = (work / "libconsumer.rmeta").read_bytes()
        obs.update(metadata=hashlib.sha256(data).hexdigest(), private=data[24:40].hex(),
                   public=data[40:56].hex())
    if not warm:
        shutil.rmtree(work / cache)
    return obs

def exercise(threads, rotate):
    work.mkdir()
    (work / "consumer.rs").write_text(consumer)
    (work / "bridge.rs").write_text("pub use provider::*;")
    for i, (public, bridge_public, ty, count, limit, deprecated) in enumerate(cases):
        attr = '#[deprecated(note="old count")]' if deprecated else ""
        (work / "provider.rs").write_text(provider(ty, count, limit, attr))
        compile_crate("provider", public)
        compile_crate("bridge", bridge_public, ["provider"])
        warm = observe(threads, rotate, i, True)
        fresh = observe(threads, rotate, i, False)
        row = dict(threads=threads, rotate=rotate, edit=i, public=public,
                   bridge_public=bridge_public, ty=ty, count=count, limit=limit,
                   deprecated=deprecated, warm=warm, fresh=fresh)
        assert warm["exit"] == int(ty != "u32" or limit != count), row
        assert ("error[E0308]" in warm["diagnostics"]) == bool(warm["exit"]), row
        assert ("old count" in warm["diagnostics"]) == deprecated, row
        print(json.dumps(row), flush=True)
    shutil.rmtree(work)

for threads in (1, 8):
    for rotate in (False, True):
        exercise(threads, rotate)
