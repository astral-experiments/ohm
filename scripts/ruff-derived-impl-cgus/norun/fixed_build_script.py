"""Open Cargo's real retained build-script stdout in either supported workspace layout."""
import hashlib
from pathlib import Path
import stat


def collect(roots, commit, watched):
    result = {}
    for root in roots:
        for pattern in ("**/ruff/*/run/stdout", "**/ruff-*/output"):
            for path in root.glob(pattern):
                modern = path.name == "stdout"
                if modern and "workspaces" not in path.relative_to(root).parts:
                    continue
                if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
                    raise ValueError(("out-of-tree build-script stdout", str(path)))
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size < 1024 * 1024:
                    raise ValueError(("unsupported build-script stdout", str(path)))
                data = path.read_bytes()
                lines = data.decode().splitlines()
                hashes = [line.split("=",1)[1] for line in lines if line.startswith(("cargo::rustc-env=RUFF_COMMIT_HASH=", "cargo:rustc-env=RUFF_COMMIT_HASH="))]
                if not hashes:
                    continue
                reruns = [Path(line.split("=",1)[1]).resolve() for line in lines if line.startswith(("cargo:rerun-if-changed=", "cargo::rerun-if-changed="))]
                if hashes != ["RUFF_COMMIT_HASH="+commit] or Path(watched).resolve() not in reruns:
                    raise ValueError(("different real source or watched Git path", str(path), hashes, list(map(str,reruns))))
                result[str(path)] = {"sha256":hashlib.sha256(data).hexdigest(),"device":st.st_dev,"inode":st.st_ino,
                                     "mtime_ns":st.st_mtime_ns,"lines":lines,"workspace_layout":"split" if modern else "legacy"}
    if not result:
        raise ValueError("no genuine Ruff build-script stdout")
    return result
