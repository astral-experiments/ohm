"""Compare physical rustc profiler outcomes on one hardware host; keep every attempt."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess as sp
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ruff-foreign-span-observer"))
sys.path.insert(0, str(HERE.parent / "ruff-original-ty-instructions/owner-buckets"))
import fixture
from kit import acquire
import worker as w

REG = json.loads((HERE / "registration.json").read_bytes())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(name, data):
    with name.open("x") as stream:
        print(json.dumps(data, indent=2, sort_keys=True), file=stream)


def observe(args, env, wd, out, sdk, driver):
    names = set()
    correct_exe = False
    mappings = []
    with (out / "stdout").open("xb") as so, (out / "stderr").open("xb") as se:
        child = sp.Popen(args, cwd=wd, env=env, stdout=so, stderr=se)
        pid = Path("/proc") / str(child.pid)
        while child.poll() is None:
            try:
                correct_exe |= (pid / "exe").samefile(sdk / "bin/rustc")
                if not mappings:
                    for line in (pid / "maps").read_text().splitlines():
                        fields = line.split(maxsplit=5)
                        if len(fields) == 6 and fields[5] == str(driver):
                            mappings.append(line)
                for thread in (pid / "task").iterdir():
                    try:
                        names.add((thread / "comm").read_text().strip())
                    except (FileNotFoundError, ProcessLookupError):
                        pass
            except (FileNotFoundError, ProcessLookupError):
                pass
            time.sleep(0.004)
        return {"pid": child.pid, "code": child.returncode, "executable_matched": correct_exe,
                "mapped_driver": mappings, "thread_names": sorted(names)}


def one(role, sdk, driver, mode, threads, counter, attempt, source, client, expected):
    w.guard()
    label = f"{role}-{mode}-t{threads}-{counter.replace(':','_')}-{attempt}"
    td = w.proof / "runs" / label
    td.mkdir(parents=True)
    wd = w.root / "fixture-work" / label
    wd.mkdir(parents=True)
    env = {k: os.environ[k] for k in ("HOME", "PATH", "LANG") if k in os.environ}
    env.update(RUST_BACKTRACE="1", LC_ALL="C")
    if role == "stock":
        env["RUSTC_BOOTSTRAP"] = "counter_fixture"
    emit = "metadata" if mode == "check" else "dep-info,metadata,link"
    args = [str(sdk/"bin/rustc"), str(source), "--crate-name", "counter_fixture", "--crate-type=rlib",
            "--edition=2024", "--emit=" + emit, "-Copt-level=1", "-Clto=off", "-Cembed-bitcode=no",
            "-Cdebuginfo=line-tables-only", "-Cdebug-assertions=on", "-Ccodegen-units=32",
            "-Cincremental=" + str(wd/"inc"), f"-Zthreads={threads}", "--out-dir", str(wd)]
    if counter != "ordinary":
        args += ["-Zself-profile=" + str(td/"profile"), "-Zself-profile-counter=" + counter,
                 "-Zself-profile-events=" + REG["events"]]
    save(td/"invocation.json", {"argv": args, "cwd": str(wd), "rustc_bootstrap": env.get("RUSTC_BOOTSTRAP")})
    result = observe(args, env, wd, td, sdk, driver)
    stderr = (td/"stderr").read_text(errors="replace")
    result["first_panic"] = next((s for s in stderr.splitlines() if "panicked at" in s), None)
    top = stderr.split("stack backtrace:", 1)[-1].split("note:", 1)[0]
    result["raw_start_end"] = "assertion failed: start <= end" in stderr
    first = result["first_panic"] or ""
    result["matched_opt_interval"] = result["raw_start_end"] and first.startswith("thread 'opt ") and "measureme-" in first and "/src/raw_event.rs:" in first and "TimingGuard" in top and ("rustc_codegen_llvm::back::write" in top or "rustc_codegen_ssa::back::write" in top)
    result["profile_files"] = {}
    for current in td.rglob("*.mm_profdata"):
        with current.open("rb") as handle:
            magic = handle.read(8).hex()
        result["profile_files"][str(current.relative_to(td))] = [current.stat().st_size, digest(current), magic]
    result["native"] = None
    if result["code"] == 0 and mode == "build":
        lib = wd/"libcounter_fixture.rlib"
        ar = sp.check_output(["ar", "t", str(lib)], text=True)
        (td/"archive-members.txt").write_text(ar)
        native_args = [str(sdk/"bin/rustc"), str(client), "--edition=2024", "--extern",
                       "counter_fixture=" + str(lib), "-o", str(wd/"native")]
        save(td/"native-argv.json", native_args)
        with (td/"link.stderr").open("xb") as err:
            rc = sp.run(native_args, cwd=wd, env={k:v for k,v in env.items() if k!="RUSTC_BOOTSTRAP"}, stderr=err).returncode
        if rc == 0:
            test = sp.run([str(wd/"native")], cwd=wd, env=env, capture_output=True)
            (td/"native.stdout").write_bytes(test.stdout)
            (td/"native.stderr").write_bytes(test.stderr)
            result["native"] = {"archive_sha256": digest(lib), "elf_sha256": digest(wd/"native"),
                                "objects": sum(n.endswith(".o") for n in ar.splitlines()),
                                "ok": test.returncode == 0 and test.stdout == expected.encode() and not test.stderr}
            for file in (lib, wd/"native"):
                dest = w.proof/"objects"/digest(file)
                if not dest.exists():
                    shutil.copyfile(file, dest)
        result["link_exit"] = rc
    save(td/"result.json", result)
    print(label, result["code"], result["matched_opt_interval"], result["first_panic"], flush=True)
    return result


def main():
    if os.environ["GITHUB_SHA"] != os.environ["REVIEWED_HEAD"] or os.environ["GITHUB_REF_NAME"] != REG["branch"] or os.environ["GITHUB_RUN_ATTEMPT"] != "1":
        raise ValueError("unregistered dispatch")
    w.guard()
    token = os.environ["OHM_SDK_READ_TOKEN"]
    w.install()
    cfg = json.loads((HERE.parent/"ruff-original-ty-instructions/owner-buckets/binding.json").read_bytes())
    assert cfg["run"] == REG["factory"]
    roots = acquire(w, cfg, token)
    del token
    sp.run(["rustup", "toolchain", "install", "1.99.0", "--profile", "minimal"], check=True, timeout=600)
    stock = Path(sp.check_output(["rustup", "which", "--toolchain", "1.99.0", "rustc"], text=True).strip()).resolve().parent.parent
    sdks = {"stock": stock, "signed23": w.sdk, "pr329": roots["C"]}
    source, client, expected = fixture.values()
    (w.proof/"fixture.rs").write_text(source)
    (w.proof/"client.rs").write_text(client)
    (w.proof/"expected.txt").write_text(expected)
    (w.proof/"objects").mkdir()
    save(w.proof/"machine.json", {"kernel": os.uname().release, "machine": os.uname().machine,
         "cpu": sp.check_output(["lscpu"], text=True), "allowed_cpus": sorted(os.sched_getaffinity(0)),
         "perf_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip(),
         "target": os.environ["RUNNER_NAME"], "sha": os.environ["GITHUB_SHA"], "source": digest(w.proof/"fixture.rs")})
    drivers = {}
    for role, sdk in sdks.items():
        driver, = (sdk/"lib").glob("librustc_driver-*.so")
        expected_commit, exe_sha, driver_sha = REG["roles"][role]
        actual = [digest(sdk/"bin/rustc"), digest(driver)]
        assert actual == [exe_sha, driver_sha], (role, actual)
        vv = sp.check_output([str(sdk/"bin/rustc"), "-vV"], text=True)
        assert expected_commit in vv or (role == "pr329" and expected_commit == cfg["source"]["C"] and "release: 1.99.0-dev" in vv)
        elf_id = sp.check_output(["readelf", "-n", str(driver)], text=True)
        found_id = re.findall(r"Build ID: (\w+)", elf_id)
        expected_ids = {"stock": [], "signed23": ["13d77347e7b9583b23105b596b85d283cd70af08"],
                        "pr329": ["3fddb018801dfd1844f2ce5f4b21268ecf66f355"]}
        assert found_id == expected_ids[role], (role, found_id)
        (w.proof/(role+"-elf-notes.txt")).write_text(elf_id)
        save(w.proof/(role+"-sdk.json"), {"source": expected_commit, "version": vv, "driver": str(driver),
             "rustc_sha256": exe_sha, "driver_sha256": driver_sha, "build_ids": found_id})
        drivers[role] = driver
    rows = {}
    for role in sdks:
        for mode, threads_set in [("check", [1]), ("build", [8, 1])]:
            for threads in threads_set:
                for counter in ["ordinary", "wall-time", "instructions:u"]:
                    attempts = 3 if mode == "build" and counter == "instructions:u" else 1
                    for i in range(attempts):
                        name = (role, mode, threads, counter, i)
                        rows[name] = one(role, sdks[role], drivers[role], mode, threads, counter, i,
                                         w.proof/"fixture.rs", w.proof/"client.rs", expected)
    controls = [(k,v) for k,v in rows.items() if k[3] != "instructions:u" or k[1] == "check"]
    state = {"count": len(rows), "controls": len(controls),
             "controls_ok": all(v["code"]==0 and (k[1]=="check" or v["native"] and v["native"]["ok"] and v["native"]["objects"]>=8) for k,v in controls),
             "physical": all(r["executable_matched"] and r["mapped_driver"] for r in rows.values()),
             "successful_profiles_recorded": all(len(v["profile_files"]) == 1 and all(size>32 and magic.startswith("4d4d5044") for size,_,magic in v["profile_files"].values()) for k,v in rows.items() if k[3]!="ordinary" and v["code"] == 0),
             "all_successful_native_oracles": all(v["native"] and v["native"]["ok"] for k,v in rows.items() if k[1]=="build" and v["code"]==0),
             "stock_matched": sum(v["matched_opt_interval"] for k,v in rows.items() if k[0]=="stock"),
             "outcomes": [[list(k),v["code"],v["matched_opt_interval"]] for k,v in rows.items()]}
    save(w.proof/"completed.json", state)
    if not (state["controls_ok"] and state["physical"] and state["successful_profiles_recorded"] and state["all_successful_native_oracles"]):
        raise ValueError("a physical or ordinary/control admission failed; preserve all rows")


if __name__ == "__main__":
    main()
