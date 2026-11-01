"""Compare the native programs that will run with their packaged component members."""

import hashlib
from pathlib import Path, PurePosixPath
import stat
import tarfile
from materialize import need, sha

TOOLS = {
    "rustc": "rustc",
    "rustdoc": "rustc",
    "cargo": "cargo",
    "rustfmt": "rustfmt-preview",
    "cargo-fmt": "rustfmt-preview",
    "cargo-clippy": "clippy-preview",
    "clippy-driver": "clippy-preview",
}


def files(sdk, host):
    paths = {n: (c, Path("bin") / n) for n, c in TOOLS.items()}
    (driver,) = (sdk / "lib").glob("librustc_driver-*")
    libdir = Path("lib/rustlib") / host / "lib"
    (std,) = (sdk / libdir).glob("libstd-*.rlib")
    paths.update(driver=("rustc", driver.relative_to(sdk)), std=("rust-std-" + host, std.relative_to(sdk)))
    if host == "x86_64-unknown-linux-gnu":
        paths["wild"] = ("rustc", libdir.parent / "bin/wild-ld/ld.bfd")
    return paths


def compare(archive, sdk, host):
    name = "ohm-1.99.0-23-" + host + ".tar.gz"
    need(archive.name == name and archive.is_file() and not archive.is_symlink(), "wrong staged archive")
    digest = sha(archive)
    need(Path(str(archive) + ".sha256").read_text().split() == [digest, name], "bad staged archive checksum")
    paths = files(sdk, host)
    prefix = PurePosixPath("rust-1.99.0-dev-" + host)
    wanted = {str(prefix / c / str(relative)): n for n, (c, relative) in paths.items()}
    actors = {}
    with tarfile.open(archive, "r|gz") as tar:
        for entry in tar:
            if entry.name not in wanted:
                continue
            n = wanted[entry.name]
            need(n not in actors and entry.isreg() and entry.size > 0, ("duplicate/nonregular actor", n))
            local = sdk / paths[n][1]
            st = local.lstat()
            need(stat.S_ISREG(st.st_mode) and st.st_size == entry.size, ("foreign installed file", n))
            with tar.extractfile(entry) as stream:
                h = hashlib.file_digest(stream, "sha256").hexdigest()
            need(h == sha(local), ("installed/staged bytes differ", n))
            with local.open("rb") as f:
                magic = f.read(8)
            native = magic[:4] == (b"\x7fELF" if host.startswith("x86_64") else b"\xcf\xfa\xed\xfe")
            need(magic == b"!<arch>\n" if n == "std" else native, ("foreign native format", n, magic))
            actors[n] = {
                "path": str(local),
                "member": entry.name,
                "sha256": h,
                "bytes": entry.size,
                "mode": stat.S_IMODE(st.st_mode),
                "archive_mode": entry.mode,
            }
    need(set(actors) == set(paths), "missing native package actors")
    return {
        "archive": archive.name,
        "sha256": digest,
        "bytes": archive.stat().st_size,
        "host": host,
        "actors": actors,
    }
