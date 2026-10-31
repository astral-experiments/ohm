"""Reopen the held distribution and the separately built, byte-pinned four-fix native Cargo."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native import CARGO_SHA, HOST, need, save, sha


def main(w):
    archived = Path(os.environ["GITHUB_WORKSPACE"]) / "native-reader"
    head = subprocess.check_output(["git", "-C", archived, "rev-parse", "HEAD"], text=True).strip()
    need(head == "69af8fd3bf8ef6ddb49aa801f25016c6af5171a9", "different official reader")
    sys.path.insert(0, str(archived / "scripts/rc22-complete-smoke"))
    import media
    import focused
    import installed
    import replay_static
    import static_cargo

    (w / "media").mkdir(parents=True)
    (w / "receipts").mkdir(exist_ok=True)
    archives = [media.fetch(w, media.CFG["global"], "Retain global release assets"),
                media.fetch(w, media.CFG["targets"][HOST]["platform"], "Retain distribution artifacts")]
    media.release(w, HOST, *archives)
    installed.catalog(w, HOST)
    evidence = w / "receipts/original-package"
    evidence.mkdir()
    _, prefix, _ = focused.installation(w, HOST, "native-baseline", evidence)
    (w / "baseline").symlink_to(prefix, target_is_directory=True)
    jid, _, aid, size, checksum = replay_static.IDS[HOST]
    api = "repos/" + media.REPO + "/actions/"
    def command(suffix):
        return ["gh", "api", api + suffix]
    run, job, art = [json.loads(subprocess.check_output(command(suffix)))
                     for suffix in [f"runs/{replay_static.RUN}", f"jobs/{jid}", f"artifacts/{aid}"]]
    replay_static.official(run, job, art, HOST)
    native_zip = w / "media/fourfix.zip"
    with native_zip.open("xb") as out:
        subprocess.run(command(f"artifacts/{aid}/zip"), stdout=out, check=True)
    need(native_zip.stat().st_size == size and sha(native_zip) == checksum, "different native static archive")
    with zipfile.ZipFile(native_zip) as z:
        for name in ("static-product.json", "static-cargo.zst"):
            need(z.namelist().count(name) == 1, ("wrong native member", name))
            dst = w / ("receipts" if name.endswith(".json") else "media") / name
            with z.open(name) as fd, dst.open("xb") as out:
                shutil.copyfileobj(fd, out)
    origin = static_cargo.verify_product(receipt=w / "receipts/static-product.json")
    need(origin["sha256"] == CARGO_SHA, "unexpected linked Cargo")
    new = w / "fourfix"
    subprocess.run(["zstd", "-dq", w / "media/static-cargo.zst", "-o", new], check=True)
    new.chmod(0o755)
    need(sha(new) == CARGO_SHA, "wrong decoded Cargo")
    save(w / "receipts/static-origin.json", {"run": run, "job": job, "artifact": art, "cargo": sha(new)})
    binary = prefix / "bin/cargo"
    need(sha(binary) == media.CFG["targets"][HOST]["cargo_sha256"], "different original packaged Cargo")
    binary.rename(prefix / "bin/cargo.original")
    shutil.copy2(new, binary)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
