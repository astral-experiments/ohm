"""Run only on the reviewed private measurement at the same immutable head for all contrasts."""

from pathlib import Path
import os, sys, subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common, media, placement
from common import HERE, read, save, sha, require


def payload():
    entries = (HERE / "SHA256SUMS").read_text().splitlines()
    found = set()
    for ln in entries:
        h, name = ln.split("  ", 1)
        require(
            name not in found and Path(name).name == name and sha(HERE / name) == h,
            "modified payload " + name,
        )
        found.add(name)
    expected = {p.name for p in HERE.iterdir() if p.is_file()} - {"SHA256SUMS", "G-qualified-lock.json"}
    require(found == expected, "unsealed source")


def release(out, which):
    lock = read(HERE.parent / "uv-client-22958/signed-23-split-lock.json")
    official = lock["signed_release"]
    raw = media.Transport.gh_json("api", "repos/" + media.REPO + "/releases/latest")
    require(
        raw["id"] == official["release_id"]
        and raw["tag_name"] == official["tag"]
        and raw["immutable"]
        and not raw["draft"]
        and not raw["prerelease"],
        "canonical signed release changed",
    )
    (asset,) = [a for a in raw["assets"] if a["id"] == official["asset"]["id"]]
    require(
        asset["digest"] == official["asset"]["digest"] and asset["size"] == official["asset"]["size"],
        "release archive differs",
    )
    save(out / ("latest-" + which + ".json"), raw)


def current(out):
    d = read(out / "placement.json")
    e = os.environ
    require(
        d["head"] == e["REVIEWED_HEAD"]
        and d["series"] == e["SERIES"]
        and d["G_lock"] == e["G_LOCK"]
        and d["run"] == int(e["GITHUB_RUN_ID"])
        and d["boot"] == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and d["boot"] not in d["excluded"],
        "alien placement",
    )
    return d


def proper(w, tmp):
    os.environ.setdefault("UV_22958_CONTRAST", "signed")
    sys.path.insert(0, str(HERE.parent / "uv-client-22958"))
    import service

    m = service.m
    m.host = lambda: (w, tmp)
    import scoped

    scoped.c.host = lambda: (w, tmp)
    return m, scoped


def pin(out):
    boot = current(out)["boot"]
    c = read(out / "calibration.json")
    mask = set(c["ready"]["affinity"])
    require(
        c["ready"]["boot"] == boot
        and c["unmultiplexed_calibration_clocks"] == 28
        and len(mask) == 8
        and mask <= os.sched_getaffinity(0),
        "noncomparable counter/affinity",
    )
    os.sched_setaffinity(0, mask)
    return sorted(mask)


def clock(out, stage, mask):
    d = out / ("blocking-clock-" + stage)
    subprocess.run([sys.executable, "-ISBu", HERE.parent / "uv-client-22958/clock-check.py", d], check=True)
    x = read(d / "verified.json")
    require(
        x["eligible_blocking_calibration"] and x["boot"] == current(out)["boot"] and x["affinity"] == mask,
        "blocking timer",
    )
    return sha(d / "verified.json")


def tools(out, tmp):
    c = read(out / "calibration.json")
    lib = tmp / "inventory-rustc-meter/libohm_pmu.so"
    plain = Path(c["ready"]["plain"])
    require(
        sha(lib) == sha(out / "per-rustc-calibration/libohm_pmu.so") and sha(plain) == c["plain_sha256"],
        "changed meter",
    )
    return {"library": str(lib), "plain": str(plain), "plain_sha256": sha(plain), "library_sha256": sha(lib)}


def main(mode):
    w, tmp, head = placement.identity()
    out = w / "trait-results"
    payload()
    donor = read(HERE / "donor-tree.json")
    tree = subprocess.check_output(
        ["git", "-C", w / "coordinator", "ls-tree", "-r", head, "--", *donor["directories"]], text=True
    )
    rows = {line.split("\t")[1]: line.split(" ")[2].split("\t")[0] for line in tree.splitlines()}
    require(rows == donor["blobs"], "changed inherited implementations or counter bytes")
    if mode == "start":
        require(not out.exists(), "required-empty result site")
        out.mkdir()
        save(out / "attempt.json", {
            "head": head,
            "run": int(os.environ["GITHUB_RUN_ID"]),
            "runner_name": os.environ["RUNNER_NAME"],
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        })
        placement.attest(out, tmp)
        release(out, "before")
        return
    context = current(out)
    control = "F" if context["series"].startswith("marginal.") else "R"
    m, scoped = proper(w, tmp)
    if mode == "calibrate":
        m.pmu(w, tmp)[0].calibrate()
        mask = pin(out)
        scoped.calibrate()
        blocking = clock(out, "pre", mask)
        save(out / "tools.json", tools(out, tmp))
        save(
            out / "boot-attestation.json",
            dict(
                context,
                placement_sha256=sha(out / "placement.json"),
                inherited=sha(out / "calibration.json"),
                threads=sha(out / "per-rustc-calibration/calibration.json"),
                blocking=blocking,
                affinity=mask,
                tools=tools(out, tmp),
            ),
        )
        return
    mask = pin(out)
    require(tools(out, tmp) == read(out / "tools.json"), "changed meter")
    if mode == "assets":
        media.installed(out, tmp, control, read(HERE / "G-qualified-lock.json"))
        return
    if mode == "study":
        import panel

        panel.main(out, w / "uv-source", tmp / "installed-21134", control, context["series"].split(".")[1])
        return
    require(mode == "finish", "unknown command")
    clock(out, "post", mask)
    release(out, "after")
    import score

    result = score.replay(out)
    save(out / "score.json", result)


if __name__ == "__main__":
    main(sys.argv[1])
