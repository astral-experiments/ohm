"""Re-read Cargo's actual build-script output file using the typed Ruff package/out_dir identity."""

import gzip
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePath
from urllib.parse import unquote, urlsplit

import git_layout


def need(ok, msg):
    if not ok:
        raise ValueError(msg)


def output_location(messages, tree, work, *, invalid):
    expected = str(tree / "crates/ruff")

    def is_ruff(m):
        ident = m.get("package_id", "")
        parsed = urlsplit(ident.removeprefix("path+"))
        return (
            ident.startswith("path+file://")
            and parsed.netloc == ""
            and unquote(parsed.path) == expected
        )

    rows = [
        m for m in messages if is_ruff(m) and m["reason"] == "build-script-executed"
    ]
    if invalid and not rows:
        return None
    need(
        len(rows) == 1, "the real Ruff build script was not uniquely reported by Cargo"
    )
    row = rows[0]
    path = PurePath(row["out_dir"])
    need(
        path.is_absolute()
        and ".." not in path.parts
        and path.is_relative_to(work)
        and re.fullmatch(
            r"target/debug/build/workspaces/[0-9a-f]{16}/v2-[0-9a-f]{16}/ruff/[0-9a-f]{16}/out",
            str(path.relative_to(work)),
        ),
        "unrelated Cargo OUT_DIR",
    )
    if not invalid:
        ids = {
            m["package_id"]
            for m in messages
            if m["reason"] == "compiler-artifact"
            and m["target"]["name"] == "ruff"
            and m["target"]["kind"] == ["bin"]
            and m.get("executable")
        }
        need(
            ids == {row["package_id"]},
            "the producer and acquired Ruff executable disagree",
        )
    return row["package_id"], path.parent / "run/stdout", row["env"]


def verify_raw(body, source, tree, row):
    need(len(body) <= 128 * 1024 and 0 < len(body), "unexpected build-script body")
    package, path, env = row
    # The same physical raw output is consumed by Cargo and its typed build-script-emitted environment.
    parsed = git_layout.build_output(body, tree, source["ref"], source["revision"])
    hashes = [v for k, v in env if k == "RUFF_COMMIT_HASH"]
    need(
        hashes == [source["revision"]],
        "Cargo's actual root build script supplied another Git hash",
    )
    return dict(
        package=package,
        path=str(path),
        raw_sha256=hashlib.sha256(body).hexdigest(),
        validated=parsed,
    )


def file_key(st):
    need(stat.S_ISREG(st.st_mode), "Cargo build-script stdout must be a regular file")
    return [st.st_dev, st.st_ino, st.st_size, st.st_blocks * 512]


def census_file(ledger, path, work, length):
    r = ledger[str(path.relative_to(work))]
    need(
        len(r) == 6 and stat.S_ISREG(r[3]) and r[5] == length > 0,
        "missing physical script stdout",
    )
    return [r[0], r[1], r[5], r[4] * 512]


def script_output(phase, where, source, messages, repo, work, ledger):
    import donor_witness as dw

    row = output_location(messages, repo, work, invalid=phase == "invalid")
    if row is None:
        dw.write(where / "ruff-build-script.json", {"reported": False})
        return
    path = Path(row[1])
    need(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 128 * 1024,
        "wrong build-script output file",
    )
    with path.open("rb") as stream:
        key = file_key(os.fstat(stream.fileno()))
        data = stream.read(128 * 1024 + 1)
        need(
            key
            == file_key(os.fstat(stream.fileno()))
            == file_key(path.lstat())
            == census_file(ledger, path, work, len(data)),
            "build-script stream changed after the quiescent census",
        )
    (where / "ruff-build-script.stdout.gz").write_bytes(gzip.compress(data, mtime=0))
    dw.write(
        where / "ruff-build-script.json",
        {"reported": True, "physical": key, **verify_raw(data, source, repo, row)},
    )


def reopen_script(z, prefix, source, output, root, ledger):
    messages = [json.loads(s) for s in output.splitlines()]
    row = output_location(
        messages, root / "ruff", root / "work", invalid=prefix.endswith("/invalid")
    )
    raw = prefix + "/ruff-build-script.stdout.gz"
    body = json.loads(z.read(prefix + "/ruff-build-script.json"))
    if row is None:
        need(
            raw not in z.NameToInfo and body == {"reported": False},
            "invented build-script event on failed Cargo",
        )
    else:
        need(
            z.getinfo(raw).file_size <= 128 * 1024,
            "oversized saved Cargo script stream",
        )
        data = gzip.decompress(z.read(raw))
        key = census_file(ledger, row[1], root / "work", len(data))
        need(
            body
            == {
                "reported": True,
                "physical": key,
                **verify_raw(data, source, Path(root) / "ruff", row),
            },
            "reported watches are not the named script's original output",
        )
