"""Bind the three repair commands to the source-qualified schema-3 Linux observer."""

import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile

import contact
import evidence as ev

HEAD = "19f9a67b032cce44cea1e3bb7e324558cd9abd0a"
MANIFEST = "dd9079b8bbe00593142dde1def8862a2d1f5d2cb04e6445e2f056f56dbff3292"
READER = "99ce628b4cd2e422857f9b4ac9dd59b135cd6c306848b09b0cbdfe7a6d856b41"
SOURCE = "3e859dbcd5456d8a1cac6fcd320dcff9540e07c9e5ccf766b5c43b4a7087ede1"


def package(repo):
    repo = repo.resolve(strict=True)
    sub = repo / "scripts/branch-return-execstop"
    expected = {
        "scripts/branch-return-execstop": "48bbd7a7ce2b03b1192f052204bd075f5bf49ffa",
        "scripts/branch-return-pmu": "8036cb549845a905ab83882f5b01766229e0e636",
    }

    def git(*args):
        return subprocess.check_output(["git", "--no-optional-locks", "-C", repo, *args], text=True).strip()

    ev.need(
        git("rev-parse", "HEAD") == HEAD
        and all(
            git("rev-parse", "HEAD:" + path) == tree and not git("status", "--porcelain", "--", path)
            for path, tree in expected.items()
        ),
        "incorrect observer source checkout",
    )
    ev.need(
        ev.sha(sub / "SHA256SUMS") == MANIFEST
        and ev.sha(sub / "kernel/read_events.py") == READER
        and ev.sha(sub / "kernel/observe.c") == SOURCE,
        "different schema-3 implementation",
    )
    subprocess.run(["sha256sum", "--strict", "--check", "--status", "SHA256SUMS"], check=True, cwd=sub)
    return sub


def decoder(sub):
    path = sub / "kernel/read_events.py"
    ev.need(ev.sha(path) == READER, "untrusted positive ledger reader")
    spec = importlib.util.spec_from_file_location("repair_positive_kernel_reader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualify(repo, tools, fixtures, wild, boot):
    sub = package(repo)
    subprocess.run(
        [sys.executable, "-IB", sub / "group_fixtures.py", "run", tools, fixtures, wild], check=True
    )
    receipt = json.loads(
        subprocess.check_output([sys.executable, "-IB", sub / "group_fixtures.py", "reopen", fixtures])
    )
    ev.need(
        receipt["qualified"]
        and receipt["schema"] == 3
        and receipt["boot"] == boot
        and receipt["observer_sha256"] == ev.sha(tools / "observe") == ev.sha(fixtures / "observe.elf")
        and receipt["stock_wild_sha256"] == ev.sha(wild),
        "unqualified native group observer",
    )
    return receipt


def reopen_fixtures(z, repo):
    sub = package(repo)
    prefix = "kernel-fixtures/"
    members = [i for i in z.infolist() if i.filename.startswith(prefix) and not i.is_dir()]
    ev.need(
        1 <= len(members) <= 144
        and sum(i.file_size for i in members) <= 12 << 20
        and len({i.filename for i in members}) == len(members),
        "unbounded or duplicate native fixtures",
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in members:
            name = i.filename[len(prefix) :]
            ev.need(
                all(p not in ("", ".", "..") for p in name.split("/"))
                and not PurePosixPath(name).is_absolute()
                and i.file_size <= 4 << 20
                and stat.S_IFMT(i.external_attr >> 16) in (0, stat.S_IFREG),
                "untrusted fixture path/type",
            )
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as src, dest.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        out = subprocess.check_output(
            [sys.executable, "-IB", sub / "group_fixtures.py", "reopen", root], timeout=180
        )
        ev.need(out == (root / "group-v2/qualified.json").read_bytes(), "different reopened fixture result")
    return json.loads(out)


def catalog(sdk, proxy, notifier):
    names = [*(sdk / f for f in contact.ROLES.values()), proxy / "cargo", *map(Path, contact.AUX)]
    if notifier:
        names.append(Path(notifier))
    out = {}
    for p in names:
        dest = p.resolve(strict=True)
        s = p.stat()
        ev.need(p.is_absolute() and stat.S_ISREG(s.st_mode) and s.st_size >= 64, "invalid executable input")
        out[str(p)] = [
            str(dest),
            [
                ev.sha(dest),
                s.st_dev,
                s.st_ino,
                stat.S_IMODE(s.st_mode),
                s.st_size,
                s.st_mtime_ns,
                s.st_ctime_ns,
            ],
        ]
    return out


def timestamp_ns(text):
    seconds, fraction = text.split(".")
    return int(seconds) * 10**9 + int(fraction)


def signature(image):
    return [
        image["sha256"],
        image["dev"],
        image["ino"],
        stat.S_IMODE(image["mode"]),
        image["size"],
        timestamp_ns(image["mtime"]),
        timestamp_ns(image["ctime"]),
    ]


def topology(reader, raw, cat, files, sdk, proxy, command, units, cwd, *, captured=None, notifier=None):
    data = reader.parse(raw, expected_code=0, expected_schema=3)
    proxy_path = str(proxy / "cargo")
    paths = {str(sdk / f): role for role, f in contact.ROLES.items()}
    roles = paths | {proxy_path: "proxy", contact.AUX[0]: "cc", contact.AUX[1]: "collect2"}
    if notifier:
        roles[notifier[0]] = "notifier"
    ev.need(
        set(cat) == set(roles)
        and len({tuple(v[1][1:3]) for v in cat.values()}) == len(roles)
        and all(cat[p][1] == files[contact.ROLES[r]] for p, r in paths.items()),
        "foreign physical executable catalog",
    )
    projected = []
    ancestors = {1: ()}
    # Intentionally assign the parent's image at birth, before any later re-exec.
    last = {}
    groups = []
    for line in raw.splitlines():
        row = line.split(b"\t")
        if row[0] == b"N":
            ancestors[int(row[4])] = ancestors[int(row[1])]
        elif row[0] == b"H":
            groups.append(int(row[4]))
        elif row[0] == b"E":
            order, g = int(row[1]), int(row[2])
            e = data["execs"][order - 1]
            path, im = e["execfn"], e["image"]
            ev.need(
                path in cat and cat[path] == [e["exe"], signature(im)],
                "installed image differs from enrolled file",
            )
            role = roles[path]
            parents = [r for _, r in ancestors[g]]
            prefix = ["notifier"] if notifier else []
            if role == "notifier":
                expected = []
            else:
                expected = (
                    prefix
                    + {
                        "proxy": [],
                        "cargo": ["proxy"],
                        "rustc": ["proxy", "cargo"],
                        "cc": ["proxy", "cargo", "rustc"],
                        "collect2": ["proxy", "cargo", "rustc", "cc"],
                        "wild": ["proxy", "cargo", "rustc", "cc", "collect2"],
                    }[role]
                )
            ev.need(parents == expected, ("unexpected physical lineage", role, parents))
            if role in ("notifier", "proxy", "cargo"):
                ev.need(e["cwd"] == str(cwd), "wrong root command cwd")
            if role == "wild":
                caller = data["execs"][dict((r, i) for i, r in ancestors[g])["rustc"] - 1]["argv"]
                ev.need(
                    caller.count("--crate-type") == 1 and caller[caller.index("--crate-type") + 1] == "bin",
                    "stock linker did not descend from the binary compiler",
                )
            ancestors[g] = (*ancestors[g], (order, role))
            last[order] = role
            projected.append([e["pid"], path, e["argv"]])
    topo = contact.topology_rows(
        projected, sdk, proxy, command, units, captured=captured, notifier=notifier
    )
    return topo | {
        "kernel": {k: data[k] for k in ("schema", "code", "sha256", "lifetimes", "reaped", "displaced")}
        | {
            "images": len(projected),
            "installed_compiler_group_exits": sum(last[i] == "rustc" for i in groups),
        }
    }
