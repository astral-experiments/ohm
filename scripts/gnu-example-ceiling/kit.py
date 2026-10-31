"""Construct the signed GNU SDK with only its Cargo replaced by the enrolled original ELF."""

from __future__ import annotations
import gzip, hashlib, io, json, os, shutil, stat, subprocess, sys, tarfile, zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
ROLES = json.loads((HERE / "roles.json").read_bytes())
RUST = "c79998a5cd143c445a4b2528f20953b176a65c5d"
RUST_ELF = "f7663fb7dec7e5c7ea613a85ff1d6e4c00bf97b8c50534f17e5c95cd599712b9"
DRIVER = "dae4f8dc64b2b2ac9dc04dfe2cfad633d6af1a87da2dfc532e757ffe758680e3"
WILD = "0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5"
CARGO = ROLES["cargo_sha256"]
SIGNED = "4695ab8e260ba4d6363e42b785c8f410dd79d9255f0313dab6c19e978878f43e"
WILD_PATH = "lib/rustlib/x86_64-unknown-linux-gnu/bin/wild-ld/ld.bfd"
TOOLCARGO = "c18e91b514b2c4e4966c9ab03232c804af3e1b57"
ARTS = json.loads((HERE / "cargo-files.json").read_bytes())


def sha(p):
    with Path(p).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def H(b):
    return hashlib.sha256(b).hexdigest()


def save(p, d):
    with p.open("x") as f:
        json.dump(d, f, sort_keys=True, indent=2)
        f.write("\n")


def stable(p):
    v = p.stat()
    return [v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, stat.S_IMODE(v.st_mode)]


def acquire_cargo(dest):
    g = os.environ.get("CEILING_GH", "gh")
    api = "repos/astral-experiments/ohm/actions/artifacts/"
    receipts = {}
    origin = None
    for role in ("product", "records"):
        ix, sz, digest, files = ARTS[role]
        meta = json.loads(subprocess.check_output([g, "api", api + str(ix)]))
        assert [
            meta["expired"],
            meta["workflow_run"]["id"],
            meta["workflow_run"]["head_sha"],
            meta["digest"],
            meta["size_in_bytes"],
        ] == [
            False,
            41081958994,
            "78801e0c551576349aa36eaf39a4f8afbd291b7f",
            "sha256:" + digest,
            sz,
        ]
        raw = subprocess.check_output([g, "api", api + str(ix) + "/zip"])
        assert len(raw) == sz and H(raw) == digest
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            assert sorted(n for n in z.namelist() if not n.endswith("/")) == sorted(files)
            for n, (h, size) in files.items():
                b = z.read(n)
                assert (H(b), len(b)) == (h, size)
                if role == "product" and n == "cargo":
                    assert h == CARGO and size == 50945080
                    bpath = dest / "cargo-301"
                    bpath.write_bytes(b)
                    bpath.chmod(0o755)
                if role == "product" and n == "product.json":
                    origin = json.loads(b)
                    (dest / "cargo-product.json").write_bytes(b)
        receipts[role] = [ix, sz, digest]
    assert (
        origin
        and origin["git"] == TOOLCARGO
        and origin["cargo_sha256"] == CARGO
        and origin["native_trace"]
        == "9a9e8b5fce22a78e9ae96b85019fdd5aeeb348ed7642a0bd795baebe50dbdfc4"
        and origin["mode"] == 0o755
        and origin["features"] == "ohm-defaults,all-static"
        and origin["tree"] == "bf643fa158734642bfee4a2aa8eff4d98bd8a09c"
    )
    return {
        "originals": receipts,
        "product": H((dest / "cargo-product.json").read_bytes()),
        "archive_features": origin["features"],
        "source": origin["git"],
        "source_tree": origin["tree"],
    }


def acquire(root, received, pinned):
    sys.path.insert(0, str(pinned / "scripts/packaged-release-workspace"))
    import packages

    assert (
        subprocess.check_output(["git", "-C", pinned, "rev-parse", "HEAD"], text=True).strip()
        == "f40b16cdb9c041c941a5e339f816111a80a84bdf"
    )
    inbox = root / "sealed"
    inbox.mkdir()
    caps = packages.actual_release("21", "x86_64-unknown-linux-gnu", inbox)
    ref = json.loads((HERE / "signed-members.json").read_bytes())
    asset, _, prov = caps["assets"]
    assert (asset["id"], asset["bytes"], asset["sha256"]) == (
        ref["asset_id"],
        ref["bytes"],
        ref["sha256"],
    )
    assert (inbox / (asset["name"] + ".sha256")).read_text().split() == [
        asset["sha256"],
        asset["name"],
    ]
    pdoc = json.loads((inbox / prov["name"]).read_bytes())
    assert (
        pdoc["manifest"]["sha256"] == sha(pinned / "scripts/packaged-release-workspace/21.json")
        and pdoc["sources"]["rust"]["revision"] == RUST
        and pdoc["sources"]["cargo"]["revision"] == "2d44bd4aa68b9ba32cacb5a384ecc18fa5e7553c"
    )
    dest = root / "donor"
    dest.mkdir()
    members = {}
    links = []
    inventory = {}
    total = 0
    with tarfile.open(inbox / asset["name"], "r|gz") as ar:
        for m in ar:
            q = PurePosixPath(m.name)
            parts = q.parts
            assert (
                not q.is_absolute()
                and ".." not in parts
                and parts[0] == "rust-1.99.0-dev-x86_64-unknown-linux-gnu"
            )
            if len(parts) < 2:
                continue
            inventory[parts[1]] = inventory.get(parts[1], 0) + 1
            if (
                parts[1]
                not in {
                    "rustc",
                    "cargo",
                    "rust-std-x86_64-unknown-linux-gnu",
                    "rust-src",
                    "wild",
                    "ohm-wild",
                }
                or len(parts) < 3
                or parts[2] not in {"bin", "lib", "libexec"}
                or m.isdir()
            ):
                continue
            rel = str(Path(*parts[2:]))
            p = dest / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            assert p.is_relative_to(dest) and not p.exists() and not p.is_symlink()
            if m.issym() or m.islnk():
                links.append([rel, m.linkname, "symlink" if m.issym() else "hardlink"])
                continue
            assert (
                m.isfile()
                and rel not in members
                and m.size < 800 * 2**20
                and total + m.size < 2**30
            )
            with p.open("xb") as f:
                shutil.copyfileobj(ar.extractfile(m), f, 1024 * 1024)
            p.chmod(0o755 if m.mode & 0o111 else 0o644)
            members[rel] = [sha(p), p.stat().st_size, stat.S_IMODE(p.stat().st_mode)]
            assert m.size == members[rel][1]
            total += m.size
    for rel, name, kind in links:
        p = dest / rel
        assert not Path(name).is_absolute()
        parts = Path(name).parts
        if kind == "symlink":
            target = (p.parent / name).resolve(strict=True)
            assert target.is_relative_to(dest)
            p.symlink_to(name)
        else:
            target = (
                dest / Path(*parts if parts[0] in ("bin", "lib", "libexec") else parts[2:])
            ).resolve(strict=True)
            assert target.is_relative_to(dest)
            os.link(target, p)
    assert (
        len(members) == ref["regular_files"] == 3768
        and total == ref["regular_bytes"] == 625529948
        and inventory == ref["top"]
        and links == ref["links"]
    )
    assert all(
        (dest / n).stat().st_size == size and sha(dest / n) == h
        for n, (size, h) in ref["tools"].items()
    )
    (driver,) = (dest / "lib").glob("librustc_driver-*.so")
    assert [sha(t) for t in [dest / "bin/rustc", driver, dest / WILD_PATH, dest / "bin/cargo"]] == [
        RUST_ELF,
        DRIVER,
        WILD,
        SIGNED,
    ] and os.access(dest / "bin/rustdoc", os.X_OK)
    save(
        received / "signed.json",
        {"release": caps, "members": members, "links": links, "provenance": pdoc},
    )
    save(received / "cargo.json", acquire_cargo(received))
    return dest


def activate(root, donor, cargo):
    sdk = root / "sdk"
    assert not sdk.exists() and not sdk.is_symlink()
    shutil.copytree(donor, sdk, copy_function=os.link, symlinks=True)
    (sdk / "bin/cargo").unlink()
    os.link(cargo, sdk / "bin/cargo")
    same = 0
    for p in sorted(donor.rglob("*")):
        rel = p.relative_to(donor)
        q = sdk / rel
        if p.is_symlink():
            assert q.is_symlink() and os.readlink(p) == os.readlink(q)
        elif p.is_file():
            actual = cargo if rel == Path("bin/cargo") else p
            assert q.samefile(actual) and stable(q) == stable(actual)
            same += 1
    assert same >= 3768
    return {
        "files": same,
        "same_paths": True,
        "SDK_inode": stable(sdk)[:2],
        "operational_tools": {
            str(p.relative_to(sdk)): [stable(p), sha(p)]
            for p in [
                sdk / "bin/rustc",
                sdk / "bin/rustdoc",
                sdk / "bin/cargo",
                sdk / WILD_PATH,
                *list((sdk / "lib").glob("librustc_driver-*.so")),
            ]
        },
    }
