"""Install the published -22 bytes privately as the native comparison."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from qualify import BIND, checksum, guard, need, save
from release_smoke import WILD, identities, named_proxies

REPO = "astral-experiments/ohm"
TAG = "ohm-1.99.0-22"
REGISTER = json.loads((HERE / "release-22/published-assets.json").read_bytes())


def api(path):
    return json.loads(subprocess.check_output(["gh", "api", "repos/" + REPO + "/" + path]))


def admit(live, tag, host):
    need(
        live["id"] == REGISTER["id"] == 430629054
        and live["tag_name"] == TAG
        and not live["draft"]
        and live["published_at"] == REGISTER["published_at"],
        "different published release",
    )
    commit = BIND["release_coordinator"]
    need(
        live["target_commitish"] == commit
        and tag["ref"] == "refs/tags/" + TAG
        and tag["object"]["type"] == "commit"
        and tag["object"]["sha"] == commit,
        "different published source",
    )
    names = [
        "ohm-installer.sh",
        TAG + ".json",
        TAG + "-" + host + "-provenance.json",
        TAG + "-" + host + ".tar.gz",
        TAG + "-" + host + ".tar.gz.sha256",
    ]
    found = {}
    for n in names:
        (row,) = [v for v in live["assets"] if v["name"] == n]
        (admitted,) = [v for v in REGISTER["assets"] if v["name"] == n]
        need(
            all(row[k] == admitted[k] for k in ("id", "name", "size", "digest"))
            and row["state"] == "uploaded",
            "different published asset: " + n,
        )
        found[n] = admitted
    return found


def install(work, out, host):
    work.mkdir()
    out.mkdir()
    need(shutil.disk_usage(work).free > 10 << 30, "less than 10 GiB for published native install")
    live = api("releases/tags/" + TAG)
    tag = api("git/ref/tags/" + TAG)
    selected = admit(live, tag, host)
    save(
        out / "origin.json",
        {"release": live["id"], "published": live["published_at"], "tag": tag, "assets": selected},
    )
    sdk = work / "sdk"
    alias = work / "private-rustup"
    env = {
        "HOME": str(work),
        "RUSTUP_HOME": str(alias),
        "RUSTUP_AUTO_INSTALL": "0",
        "CARGO_HOME": str(work / "registry"),
        "OHM_INSTALL_DIR": str(sdk),
    }
    proxy = work / "proxies"
    save(out / "launchers.json", named_proxies(proxy, shutil.which("rustup")))
    env["PATH"] = str(proxy) + os.pathsep + os.environ["PATH"]
    with tempfile.TemporaryDirectory(dir=work, prefix="immutable-asset-") as td:
        files = Path(td).resolve()
        for name, row in selected.items():
            dest = files / name
            with dest.open("xb") as fd:
                subprocess.run(
                    [
                        "gh",
                        "api",
                        "repos/" + REPO + "/releases/assets/" + str(row["id"]),
                        "-H",
                        "Accept: application/octet-stream",
                    ],
                    stdout=fd,
                    check=True,
                )
            need(
                dest.stat().st_size == row["size"] and "sha256:" + checksum(dest) == row["digest"],
                "mismatched release bytes " + name,
            )
            if not name.endswith(".tar.gz"):
                shutil.copyfile(dest, out / name)
        manifest = json.loads((files / (TAG + ".json")).read_bytes())
        origin = json.loads((files / (TAG + "-" + host + "-provenance.json")).read_bytes())
        need(
            (files / (TAG + ".json")).read_bytes() == (HERE / "release-22/22.json").read_bytes()
            and origin["coordinator"] == {"repository": REPO, "revision": BIND["release_coordinator"]}
            and origin["toolchain"] == TAG
            and origin["target"] == host
            and origin["sources"]
            == {k: {"revision": v["revision"]} for k, v in manifest["sources"].items()},
            "different release source provenance",
        )
        tar = TAG + "-" + host + ".tar.gz"
        need(
            (files / (tar + ".sha256")).read_text().split()
            == [selected[tar]["digest"].split(":")[1], tar],
            "wrong native archive checksum file",
        )
        env["OHM_DOWNLOAD_URL"] = files.as_uri()
        with (out / "installer.log").open("xb") as log:
            subprocess.run(
                ["sh", files / "ohm-installer.sh"],
                cwd=work,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
    need(
        (alias / "toolchains/ohm").samefile(sdk) and (alias / "toolchains" / TAG).samefile(sdk),
        "installer did not select the original",
    )
    v = identities(
        sdk, sdk, sdk / "bin/cargo", BIND["parent"], BIND["shipped_cargo"], host, env, out / "identity"
    )
    need(TAG in v["rustc"]["version"].splitlines()[0], "different native release description")
    for name in ("cargo-clippy", "clippy-driver", "rustfmt", "cargo-fmt", "rustdoc"):
        p = sdk / "bin" / name
        need(p.is_file() and os.access(p, os.X_OK), "missing published component " + name)
        v[name] = {"path": str(p), "sha256": checksum(p)}
    if host.startswith("x86_64"):
        p = sdk / "lib/rustlib" / host / "bin/wild-ld/ld.bfd"
        need(checksum(p) == WILD, "different published Wild")
        v["wild"] = {"path": str(p), "sha256": WILD}
    save(
        out / "complete.json",
        {"host": host, "tag": TAG, "release_id": live["id"], "assets": selected, "versions": v},
    )


if __name__ == "__main__":
    _, _, reports, tmp, host = guard()
    install(tmp / "slot-published-22", reports / "slot-published-22", host)
