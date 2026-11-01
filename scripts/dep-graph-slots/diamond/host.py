"""Run the same nominal diamond against the actual published SDK and the matched native stage1."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import qualify
import release_smoke
sys.path.insert(0, str(HERE))
import run
import reopen

PUBLISHED_RUSTDOC = {
    "x86_64-unknown-linux-gnu": "063827efd67fb2a3fb56ffcb360b8f8fac6d20ee0d0614dc42cc25ae755b4725",
    "aarch64-apple-darwin": "1a263c511a4f9f9fb822d8dd72b27d97dd6da3b9b849218ce41469d5504cb5c4",
}
need = qualify.need


def data(path):
    return json.loads(path.read_bytes())


def main():
    w, repo, reports, tmp, host = qualify.guard()
    qualify.verify_live(repo)
    native = data(reports / "slot-run-make.json")
    log = reports / "slot-run-make.log"
    need(native["exit"] == 0 and len(native["named"]) == 1 and native["sha256"] == qualify.checksum(log)
         and native["argv"][-1] == qualify.TEST, "missing native stage1 run-make")
    folder = reports / "slot-diamond"
    folder.mkdir()
    published = tmp / "slot-published-22/sdk"
    public = data(reports / "slot-published-22/complete.json")
    links = data(reports / "slot-link-smoke/complete.json")
    need(public["host"] == links["host"] == host and links["qualified"]
         and public["versions"]["rustdoc"]["sha256"] == PUBLISHED_RUSTDOC[host], "wrong published SDK")
    stage = repo / "build" / host / "stage1"
    # The named run-make builds rustdoc and its compiler as one native stage.
    # Darwin's instrumented stage2 is independently tested by the original release PGO.
    paths = {k:stage / "bin" / k for k in ("rustc", "rustdoc")}
    (paths["driver"],) = (stage / "lib").glob("librustc_driver-*")
    (paths["std"],) = (stage / "lib/rustlib" / host / "lib").glob("libstd-*.rlib")
    candidate_cargo = (tmp / "release-link-smoke/sdk/bin/cargo").resolve(strict=True)
    hashes = {k:qualify.checksum(p) for k,p in paths.items()}
    need(qualify.checksum(candidate_cargo) == links["results"]["rebased"]["versions"]["cargo"]["sha256"],
         "different tested Cargo")
    if host.startswith("x86_64"):
        need(hashes["rustc"] == links["results"]["rebased"]["versions"]["rustc"]["sha256"] and
             hashes["driver"] == links["results"]["rebased"]["versions"]["driver"]["sha256"],
             "different tested GNU stage1")
    need(shutil.disk_usage(tmp).free > (4 << 30) + (512 << 20), "insufficient private headroom")
    with tempfile.TemporaryDirectory(dir=tmp, prefix="native-diamond-") as name:
        scratch = Path(name)
        proxy = scratch / "launchers"
        launchers = release_smoke.named_proxies(proxy, shutil.which("rustup"))
        doc_launcher = Path(shutil.which("rustup")).absolute().with_name("rustdoc")
        need(doc_launcher.is_file() and os.access(doc_launcher, os.X_OK), "missing installed rustdoc launcher")
        (proxy / "rustdoc").symlink_to(doc_launcher)
        launchers["rustdoc"] = {"path":str(doc_launcher), "resolved":str(doc_launcher.resolve()),
                                "sha256":qualify.checksum(doc_launcher)}
        wild = published / "lib/rustlib" / host / "bin/wild-ld/ld.bfd" if host.startswith("x86_64") else None
        candidate = scratch / "native-stage1"
        release_smoke.toolchain(candidate, stage, candidate_cargo, host, wild)
        need((candidate / "bin/rustdoc").samefile(paths["rustdoc"]), "different rustdoc from the native stage")
        positive = {}
        expected = {}
        pkg = qualify.BIND
        for label, sdk, actors, rust_rev, cargo_rev in (
            ("published-22", published, {k:public["versions"][k]["sha256"] for k in ("cargo","rustc","rustdoc")},
             pkg["parent"], pkg["shipped_cargo"]),
            ("corrected", candidate, {"cargo":qualify.checksum(candidate_cargo),"rustc":hashes["rustc"],
                                      "rustdoc":hashes["rustdoc"]}, qualify.CHILD, pkg["trees"]["src/tools/cargo"]),
        ):
            expected[label] = dict(actors, host=host, rust_commit=rust_rev, cargo_commit=cargo_rev)
            project = scratch / "fixed-path"
            run.run_role(project, folder / label, sdk, proxy, label, expected[label], host)
            positive[label] = reopen.reopen(folder / label, expected[label], run.BIND, True)
            need(project.is_dir() and not project.is_symlink() and project.parent == scratch,
                 "different private source root")
            shutil.rmtree(project)
        need(positive["published-22"]["source_path"] == positive["corrected"]["source_path"],
             "different registered Cargo paths")
    need(all(qualify.checksum(p) == hashes[k] for k,p in paths.items()), "native stage changed during test")
    qualify.save(folder / "complete.json", {"host":host, "run":os.environ["GITHUB_RUN_ID"],
        "qa":os.environ["GITHUB_SHA"], "source":qualify.CHILD, "candidate_cargo":pkg["trees"]["src/tools/cargo"],
        "run_make_log":native["sha256"],
        "rustdoc_build_log_group":"Building stage1 rustdoc_tool_binary" in log.read_text(errors="replace"), "stage1":{k:{"path":str(p),"sha256":hashes[k]} for k,p in paths.items()},
        "expected":expected, "launchers":launchers, "reopened":positive})


if __name__ == "__main__":
    main()
