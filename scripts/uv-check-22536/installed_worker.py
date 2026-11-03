"""Run the existing #22536 acquisition on a physically enrolled, isolated, single-host installation."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import release23


def latest(path, signed):
    executable = "gh" if os.environ.get("GITHUB_ACTIONS") == "true" else "/home/dev-user/.local/bin/gh-auto"
    data = subprocess.check_output([executable, "api", "--method", "GET", "-H", "Cache-Control: no-cache",
                                   "repos/astral-experiments/ohm/releases/latest"])
    with path.open("xb") as output:
        output.write(data)
    return release23.publication(json.loads(data),signed)


def run(argv):
    assert __debug__
    active = release23.lock()
    from basis import Env, setup, read, filehash, write
    from managed_sdk import Managed
    from session import W, main, calibrate
    from science import checked_opening
    from compatibility import qualify
    import native_reader, score
    if argv[0] == "config":
        if len(argv) != 7:
            raise SystemExit("config FRESH-WORK FRESH-RESULTS GENUINE-UV-DONOR VERIFIED-CARGO-HOME SDK-POOL NEW-CONFIG")
        work, results, donor, cargo, pool, output = (Path(arg).resolve() for arg in argv[1:])
        assert pool == work.parent / "ctfe22-root-sdks" and donor.is_dir() and (cargo/"registry/cache").is_dir()
        assert pool.is_dir() and set(p.name for p in pool.iterdir()) == set(active["roles"])
        assert work != results and not work.exists() and not results.exists() and not output.exists()
        assert work.parent.is_dir() and results.parent.is_dir() and not results.is_relative_to(work)
        work.mkdir();results.mkdir()
        write(output,{"root":str(work),"results":str(results),"source_donor":str(donor),"cargo_home":str(cargo),
                      "sdks":{r:str(pool/r) for r in active["roles"]},"fresh_private_sdk_pool":str(pool),
                      "control_candidate_source_inputs":filehash(release23.H/"release23-inputs.json"),"require_source_tag":True,
                      "excluded_boots":sorted(active["excluded"])})
        return
    action, config = argv
    cfg = read(config)
    assert cfg["control_candidate_source_inputs"] == filehash(release23.H / "release23-inputs.json")
    assert set(cfg["sdks"]) == set(active["roles"]) and cfg["require_source_tag"] is True
    assert sorted(cfg["excluded_boots"]) == sorted(active["excluded"])
    assert not cfg.get("local_full_signed")
    root = Path(cfg["root"]).resolve()
    results = Path(cfg["results"]).resolve()
    if action == "read":
        print(json.dumps({"native": native_reader.affirm(results), "counts_and_walls": score.replay(results)}, sort_keys=True))
        return
    assert action == "run"
    current = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    assert current not in active["excluded"] and len(active["excluded"]) == len(set(active["excluded"])) > 28
    assert root.is_dir() and results.is_dir() and not any(root.iterdir()) and not any(results.iterdir())
    assert min(shutil.disk_usage(root).free,shutil.disk_usage(results).free) >= 80<<30
    # The initial fetch uses the true service API before science. Keep the native
    # setup guard literal: the first record goes outside the still-empty results.
    first = root.parent / "release23-pre-opening.json"
    latest(first,active["release"])
    setup(Env(cfg))
    assert list(sorted(f.name for f in results.iterdir())) == ["actual-inputs.json","source-registry.json"]
    shutil.copy2(first, results / first.name)
    e = Managed(cfg)
    cores=W["physical_cores"]()
    assert len(cores)==8
    os.sched_setaffinity(0,cores)
    try:
        calibrate(e)
        e.home()
        checked_opening(e)
        e.home()
        prove=release23.confirm_native(results,release23.H,active)
        write(results/"release23-selection.json", prove)
        qualify(e)
        latest(results/"fresh-publication.json",active["release"])
        main(cfg,e)
        latest(results/"fresh-publication-after.json",active["release"])
    finally:
        e.home()
    release23.publication_pair(results,active["release"])
    native_reader.affirm(results)
    write(results/"result.json",score.replay(results))


if __name__=="__main__":
    run(sys.argv[1:])
