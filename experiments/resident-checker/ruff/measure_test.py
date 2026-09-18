#!/usr/bin/env python3
"""Measure saving real Ruff source through building and running one exact parser test."""

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

from measure import CASES, clock, compiler, distribution, machine, write_json
from measure_source import build, protocol
from run_tests import COUNT_KEYS, PACKAGE, RESULT, REVISION, archive_ruff

TEST = "string::tests::test_escape_octet"
SOURCE = "src/string.rs"
PHASES = (
    ("baseline", "good", "good", "pass"),
    ("behavior-edit", "good", "behavior", "fail"),
    ("behavior-repair", "behavior", "good", "pass"),
    ("compile-error", "good", "error", "compile_error"),
    ("compile-repair", "error", "good", "pass"),
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def text_variants(workspace):
    case = CASES["parse-octet"]
    good = (workspace / PACKAGE / SOURCE).read_text()
    anchor, expression = case["anchor"], case["expression"]
    require(
        good.count(anchor) == 1, "source anchor missing or non-unique in pinned Ruff"
    )
    return {
        "good": good,
        "behavior": good.replace(anchor, anchor.replace(expression, "'x'")),
        "error": good.replace(anchor, anchor.replace(expression, "0u8")),
    }


def save(workspace, content):
    (workspace / PACKAGE / SOURCE).write_text(content)


def quick_fingerprint(binary):
    if binary is None or not binary.is_file():
        return None
    stat = binary.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def fingerprint(binary):
    if binary is None or not binary.is_file():
        return None
    stat = binary.stat()
    with binary.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    return {"sha256": digest, "size": stat.st_size}


def compiler_command(binary, capture, workspace, output, sysroot):
    """Retain Cargo's actual test-target codegen flags and its already built externs."""
    require(
        "--test" in capture["argv"], "capture is not Cargo's parser unit-test target"
    )
    require(
        any(
            arg.startswith("--emit=") and "link" in arg.split("=", 1)[1].split(",")
            for arg in capture["argv"]
        ),
        "capture does not request link emission",
    )
    original_root = Path(capture["cwd"])
    result = []
    extra = ""
    iterator = iter(capture["argv"][1:])
    for arg in iterator:
        if arg in ("--out-dir", "--sysroot", "-o"):
            next(iterator)
        elif arg == "-C":
            value = next(iterator)
            if value.startswith("extra-filename="):
                extra = value.split("=", 1)[1]
            if not value.startswith("incremental="):
                result.extend((arg, value))
        elif arg.startswith(
            ("-Cincremental=", "-Zthreads=", "-Ztime-passes")
        ) or arg in ("-Zohm-resident-query-graph", "-Zunstable-options"):
            continue
        elif arg.startswith("--json="):
            choices = arg.split("=", 1)[1].split(",")
            result.append("--json=" + ",".join(dict.fromkeys([*choices, "timings"])))
        else:
            if arg == str(original_root / PACKAGE / "src/lib.rs"):
                arg = str(workspace / PACKAGE / "src/lib.rs")
            result.append(arg)
    output.mkdir(parents=True, exist_ok=True)
    result.extend(
        (
            "--out-dir",
            str(output),
            "--sysroot",
            str(sysroot),
            "-Zthreads=1",
            "-Zunstable-options",
            "-Zohm-resident-query-graph",
        )
    )
    env = dict(os.environ, RUSTC_BOOTSTRAP="1", **capture["env"])
    for name in ("CARGO_MAKEFLAGS", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"):
        env.pop(name, None)
    for name in ("CARGO_MANIFEST_DIR", "CARGO_MANIFEST_PATH"):
        if name in env and Path(env[name]).is_relative_to(original_root):
            env[name] = str(workspace / Path(env[name]).relative_to(original_root))
    test_binary = output / (
        "ruff_python_parser" + extra + (".exe" if os.name == "nt" else "")
    )
    return [str(binary), *result], env, test_binary


def source_error_codes(log):
    codes = []
    for line in log.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("reason") == "compiler-message":
            item = item["message"]
        if item.get("level") == "error" and item.get("spans"):
            code = item.get("code")
            if isinstance(code, dict) and code.get("code"):
                codes.append(code["code"])
    return codes


def internal_passes(log):
    starts, elapsed, artifacts = {}, {}, []
    for line in log.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("$message_type") == "section_timing":
            phase, event = item["name"], item["event"]
            if event == "start":
                starts[phase] = item["timestamp"]
            elif event == "end" and phase in starts:
                elapsed[phase] = (item["timestamp"] - starts.pop(phase)) * 1000
        elif item.get("$message_type") == "artifact" and item.get("emit") == "link":
            artifacts.append(item["artifact"])
    return elapsed, artifacts


def write_logs(path, stdout, stderr):
    path.with_suffix(".stdout").write_text(stdout)
    path.with_suffix(".stderr").write_text(stderr)


def run_binary(binary, workspace, output):
    started = clock()
    command = [str(binary), TEST, "--exact", "--nocapture"]
    result = subprocess.run(
        command,
        cwd=workspace / PACKAGE,
        env=dict(os.environ, INSTA_UPDATE="no", CARGO_TERM_COLOR="never"),
        capture_output=True,
        text=True,
        check=False,
    )
    ended = clock()
    write_logs(output, result.stdout, result.stderr)
    matches = list(RESULT.finditer(result.stdout + result.stderr))
    require(len(matches) == 1, f"expected one libtest summary in {output}")
    counts = dict(zip(COUNT_KEYS, map(int, matches[0].groups()), strict=True))
    require(
        counts["passed"] + counts["failed"] == 1
        and not counts["ignored"]
        and not counts["measured"],
        f"did not execute exactly the selected test: {counts}",
    )
    require(TEST in result.stdout + result.stderr, f"test output did not name {TEST}")
    require(
        result.returncode == (101 if counts["failed"] else 0),
        f"unexpected test exit {result.returncode}: {output}",
    )
    return {
        "result": "fail" if counts["failed"] else "pass",
        "returncode": result.returncode,
        "counts": counts,
        "test_ns": ended - started,
        "completed_ns": ended,
    }


class Resident:
    def __init__(self, command, env, workspace, directory):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.stderr_path = directory / "compiler.stderr"
        self.stdout_lines = []
        self.version = 0
        self.process = None
        self.stderr = self.stderr_path.open("w")
        started = clock()
        try:
            self.process = subprocess.Popen(
                command,
                cwd=workspace,
                env=dict(env, OHM_RUFF_SOURCE_MODE="resident-build"),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.stderr,
                text=True,
                bufsize=1,
            )
            pid, analysis = protocol(self.line(), "ready")
            self.pid = int(pid)
            self.startup = {
                "external_ns": clock() - started,
                "analysis_ns": int(analysis),
            }
        except BaseException:
            self.close()
            raise

    def line(self):
        line = self.process.stdout.readline()
        self.stdout_lines.append(line)
        if not line:
            raise RuntimeError(f"resident protocol stopped; inspect {self.stderr_path}")
        return line

    def send(self, request):
        self.process.stdin.write(request + "\n")
        self.process.stdin.flush()

    def check(self, workspace):
        self.version += 1
        self.send(f"check\t{self.version}\t{workspace / PACKAGE / SOURCE}")
        (
            version,
            route,
            reason,
            total,
            analysis,
            errors,
            revision,
            *_source_ranges,
        ) = protocol(self.line(), "result")
        require(
            version == str(self.version), f"incorrect resident check version {version}"
        )
        return {
            "version": self.version,
            "route": route,
            "reason": reason,
            "internal_ns": int(total),
            "analysis_ns": int(analysis),
            "errors": int(errors),
            "revision": int(revision),
        }

    def finish(self):
        started = clock()
        self.send(f"build\t{self.version}")
        version, state, reason = protocol(self.line(), "build")
        reply = clock()
        require(
            version == str(self.version), f"incorrect resident build version {version}"
        )
        remaining = self.process.stdout.read()
        self.stdout_lines.append(remaining)
        code = self.process.wait(timeout=180)
        ended = clock()
        self.stderr.flush()
        raw = self.stderr_path.read_text()
        stdout = "".join(self.stdout_lines)
        (self.directory / "compiler.stdout").write_text(stdout)
        stages = {}
        for line in stdout.splitlines():
            if line.startswith(("build-analysis\t", "build-finished\t")):
                name, revision, elapsed = line.split("\t")
                require(revision == version, f"unexpected timing version: {line}")
                stages[name] = int(elapsed)
        phases, artifacts = internal_passes(raw)
        return {
            "state": state,
            "reason": reason,
            "returncode": code,
            "authorization_ns": reply - started,
            "post_authorization_compile_ns": ended - reply,
            "build_ns": ended - started,
            "completed_ns": ended,
            "error_codes": source_error_codes(raw),
            "compiler_timing_ns": phases,
            "callback_timing_ns": stages,
            "link_artifacts": artifacts,
        }

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            for pipe in (self.process.stdin, self.process.stdout):
                if pipe:
                    pipe.close()
        self.stderr.close()


def resident_transaction(command, env, workspace, binary, contents, phase, output):
    name, before, after, expected = phase
    output.mkdir(parents=True, exist_ok=True)
    previous = fingerprint(binary)
    previous_quick = quick_fingerprint(binary)
    save(workspace, contents["good"])
    resident = Resident(command, env, workspace, output)
    try:
        warm = resident.startup
        precondition = None
        if before != "good":
            began = clock()
            save(workspace, contents[before])
            precondition = resident.check(workspace)
            precondition["external_ns"] = clock() - began
            require(
                precondition["route"] == "resident"
                and precondition["errors"] == int(before == "error"),
                f"{name}: failed to reconstruct genuine resident precondition {precondition}",
            )
        started = clock()
        save(workspace, contents[after])
        check = resident.check(workspace)
        checked = clock()
        require(
            check["route"] == ("noop" if name == "baseline" else "resident"),
            f"{name}: edited source used an unexpected route {check}",
        )
        require(
            check["errors"] == int(after == "error"),
            f"{name}: wrong source errors {check}",
        )
        building = resident.finish()
        did_run = False
        testing = None
        if building["state"] == "ready" and building["returncode"] == 0:
            current_quick = quick_fingerprint(binary)
            require(
                current_quick is not None,
                f"{name}: compiler succeeded without producing {binary}",
            )
            require(
                set(building["compiler_timing_ns"]) >= {"codegen", "link"}
                and set(building["callback_timing_ns"])
                >= {"build-analysis", "build-finished"},
                f"{name}: missing rustc and resident build timing phases: {building}",
            )
            require(
                building["link_artifacts"] == [str(binary)],
                f"{name}: compiler did not attest to the expected link artifact: {building['link_artifacts']}",
            )
            if name in ("behavior-edit", "behavior-repair"):
                require(
                    previous_quick is not None and current_quick != previous_quick,
                    f"{name}: successful compiler did not replace prior executable metadata",
                )
            did_run = True
            testing = run_binary(binary, workspace, output / "test")
            outcome = testing["result"]
            ended = testing.pop("completed_ns")
            identity = fingerprint(binary)
            if name in ("behavior-edit", "behavior-repair"):
                require(
                    identity != previous, f"{name}: executable bytes did not change"
                )
        else:
            ended = building["completed_ns"]
            outcome = "compile_error"
            identity = fingerprint(binary)
            require(
                building["state"] == "rejected" and building["returncode"] != 0,
                f"{name}: compiler did not reject an unbuildable source safely {building}",
            )
            require(
                previous is not None and identity == previous,
                f"{name}: missing or changed previous output prevents a real stale-binary guard",
            )
            require(
                "E0308" in building["error_codes"],
                f"{name}: expected E0308 in compiler logs",
            )
            require(
                not building["link_artifacts"]
                and "codegen" not in building["compiler_timing_ns"],
                f"{name}: rejected input unexpectedly attempted codegen",
            )
        require(
            outcome == expected,
            f"{name}: resident result {outcome} instead of {expected}",
        )
        building.pop("completed_ns")
        building["link_artifact_attested"] = building.pop("link_artifacts") == [
            str(binary)
        ]
        return {
            "pid": resident.pid,
            "outcome": outcome,
            "external_ns": ended - started,
            "save_and_check_ns": checked - started,
            "startup": warm,
            "precondition": precondition,
            "check": check,
            "build": building,
            "test": testing,
            "binary_executed": did_run,
            "binary_existed_before": previous is not None,
            "binary_unchanged": previous is not None and identity == previous,
            "binary_size": identity["size"] if identity else None,
        }
    finally:
        resident.close()


def cargo_environment(stage, target):
    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(target),
        CARGO_BUILD_BUILD_DIR=str(target / "build"),
        CARGO_INCREMENTAL="1",
        CARGO_TERM_COLOR="never",
        INSTA_UPDATE="no",
        RUSTC=str(stage / "bin/rustc"),
    )
    for option in (
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
    ):
        env.pop(option, None)
    return env


def cargo_compile(stage, target, workspace, output, offline):
    command = [
        "cargo",
        "+ohm",
        "test",
        "--locked",
        "-p",
        "ruff_python_parser",
        "--lib",
        "--no-run",
        "--message-format=json",
    ]
    if offline:
        command.append("--offline")
    started = clock()
    result = subprocess.run(
        command,
        cwd=workspace,
        env=cargo_environment(stage, target),
        capture_output=True,
        text=True,
        check=False,
    )
    ended = clock()
    write_logs(output, result.stdout, result.stderr)
    executable = None
    fresh = None
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if (
            item.get("reason") == "compiler-artifact"
            and item.get("target", {}).get("name") == "ruff_python_parser"
            and item.get("profile", {}).get("test")
            and item.get("executable")
        ):
            require(
                executable is None, f"more than one Cargo test executable in {output}"
            )
            executable = Path(item["executable"])
            fresh = item["fresh"]
    return {
        "returncode": result.returncode,
        "build_ns": ended - started,
        "completed_ns": ended,
        "executable": executable,
        "parser_artifact_fresh": fresh,
        "error_codes": source_error_codes(result.stdout),
    }


def cargo_transaction(
    stage, target, workspace, contents, phase, output, offline, known_binary
):
    name, _before, after, expected = phase
    output.mkdir(parents=True, exist_ok=True)
    previous = fingerprint(known_binary)
    previous_quick = quick_fingerprint(known_binary)
    started = clock()
    save(workspace, contents[after])
    building = cargo_compile(stage, target, workspace, output / "compiler", offline)
    did_run = False
    testing = None
    binary = building.pop("executable")
    if building["returncode"] == 0:
        require(binary is not None, f"{name}: Cargo succeeded without an executable")
        if known_binary is not None:
            require(
                binary == known_binary, f"{name}: Cargo changed the test binary path"
            )
        current_quick = quick_fingerprint(binary)
        require(
            current_quick is not None,
            f"{name}: Cargo advertised absent executable {binary}",
        )
        if name in ("behavior-edit", "behavior-repair"):
            require(
                previous_quick is not None and current_quick != previous_quick,
                f"{name}: Cargo retained prior binary metadata",
            )
        did_run = True
        testing = run_binary(binary, workspace, output / "test")
        outcome = testing["result"]
        ended = testing.pop("completed_ns")
        identity = fingerprint(binary)
        if name in ("behavior-edit", "behavior-repair"):
            require(
                identity != previous, f"{name}: Cargo executable bytes did not change"
            )
    else:
        ended = building["completed_ns"]
        outcome = "compile_error"
        identity = fingerprint(known_binary)
        require(
            building["returncode"] == 101
            and binary is None
            and "E0308" in building["error_codes"],
            f"{name}: Cargo did not reject E0308 without advertising a new executable {building}",
        )
        require(
            previous is not None and identity == previous,
            f"{name}: Cargo error did not leave the previous binary to test the guard",
        )
    require(
        outcome == expected, f"{name}: Cargo result {outcome} instead of {expected}"
    )
    building.pop("completed_ns")
    return {
        "outcome": outcome,
        "external_ns": ended - started,
        "build": building,
        "test": testing,
        "binary_executed": did_run,
        "binary_existed_before": previous is not None,
        "binary_unchanged": previous is not None and identity == previous,
        "binary_size": identity["size"] if identity else None,
    }, binary or known_binary


def metrics(rows, mode):
    selected = [row[mode] for row in rows]
    fields = {
        "save_to_result_ms": [item["external_ns"] for item in selected],
        "test_ms": [item["test"]["test_ns"] for item in selected if item["test"]],
        "build_ms": [item["build"]["build_ns"] for item in selected],
    }
    if mode == "resident":
        fields.update(
            save_and_check_ms=[item["save_and_check_ns"] for item in selected],
            native_reanalysis_ms=[item["check"]["analysis_ns"] for item in selected],
            restart_startup_ms=[item["startup"]["external_ns"] for item in selected],
            replay_precondition_ms=[
                item["precondition"]["external_ns"]
                for item in selected
                if item["precondition"]
            ],
            native_post_authorization_compile_ms=[
                item["build"]["post_authorization_compile_ns"] for item in selected
            ],
        )
        for key in ("codegen", "link"):
            fields[f"rustc_{key}_ms"] = [
                item["build"]["compiler_timing_ns"][key]
                for item in selected
                if key in item["build"]["compiler_timing_ns"]
            ]
    return {key: distribution(values, 1e6) for key, values in fields.items() if values}


def summary(raw):
    rows = raw["samples"]
    behavior_rows = [
        row for row in rows if row["phase"] in ("behavior-edit", "behavior-repair")
    ]
    return {
        "schema": 1,
        "ruff_revision": REVISION,
        "compiler": raw["compiler"],
        "machine": raw["machine"],
        "test": TEST,
        "rounds": raw["rounds"],
        "warmup_rounds": raw["warmup_rounds"],
        "transitions_per_round": [list(phase) for phase in PHASES],
        "measurement": "Each timer starts before a real source save and ends after the selected exact libtest exits, or after rustc rejects an unbuildable source. Modes run sequentially on independent disposable archives. No tests run after an unsuccessful build.",
        "resident": "New resident test-target compiler per build, warmed through full crate analysis before timing; repair workers replay the preceding scalar source edit in the same native process before timing to restore the prior HIR checkpoint. Successful workers hand the retained compilation back to stock rustc for actual code generation and linking, then exit. Cargo's captured --test invocation preserves test, emit, profile, and dependency flags; rustc disk incremental is disabled; process restart and replay are reported separately.",
        "cargo": "Ordinary warm cargo +ohm test --locked -p ruff_python_parser --lib --no-run --message-format=json with disk incremental enabled, followed by the exact emitted test executable. This separates build and test times; both are included in save-to-result.",
        "timing_details": "Rustc JSON section timings are enabled only on the native driver and report codegen and link separately; native external build includes all post-check code generation, linking, and compiler shutdown. Fresh artifact metadata is verified before test execution and binary content fingerprints after the timing interval.",
        "percentile": "nearest rank",
        "validation": {
            "transitions": len(rows),
            "fresh_process_for_each_build": len(
                {row["resident"]["pid"] for row in rows}
            )
            == len(rows),
            "matched_outcomes": all(
                row["resident"]["outcome"] == row["cargo"]["outcome"] for row in rows
            ),
            "native_edits": all(
                row["resident"]["check"]["route"]
                == ("noop" if row["phase"] == "baseline" else "resident")
                for row in rows
            ),
            "native_repair_preconditions": all(
                row["resident"]["precondition"]["route"] == "resident"
                for row in rows
                if "repair" in row["phase"]
            ),
            "successful_builds_attested_to_real_codegen_and_link": all(
                row["resident"]["build"]["link_artifact_attested"]
                and set(row["resident"]["build"]["compiler_timing_ns"])
                >= {"codegen", "link"}
                for row in rows
                if row["phase"] != "compile-error"
            ),
            "changed_executables_on_behavior_edit_and_repair": all(
                not row[mode]["binary_unchanged"]
                for row in rows
                if row["phase"] in ("behavior-edit", "behavior-repair")
                for mode in ("resident", "cargo")
            ),
            "rejected_E0308_and_never_ran_existing_binary": all(
                row[mode]["binary_existed_before"]
                and row[mode]["binary_unchanged"]
                and not row[mode]["binary_executed"]
                and "E0308" in row[mode]["build"]["error_codes"]
                for row in rows
                if row["phase"] == "compile-error"
                for mode in ("resident", "cargo")
            ),
        },
        "behavior_edit_and_repair_ms": {
            mode: metrics(behavior_rows, mode) for mode in ("resident", "cargo")
        },
        "all_worker_restarts_ms": distribution(
            [row["resident"]["startup"]["external_ns"] for row in rows], 1e6
        ),
        "by_phase_ms": {
            name: {
                **{
                    mode: metrics([row for row in rows if row["phase"] == name], mode)
                    for mode in ("resident", "cargo")
                },
                "ratio_of_medians_cargo_over_resident": round(
                    statistics.median(
                        row["cargo"]["external_ns"]
                        for row in rows
                        if row["phase"] == name
                    )
                    / statistics.median(
                        row["resident"]["external_ns"]
                        for row in rows
                        if row["phase"] == name
                    ),
                    3,
                ),
            }
            for name, *_rest in PHASES
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("bootstrap", "capture", "repo", "cargo-target", "output"):
        parser.add_argument(
            f"--{option}", type=lambda value: Path(value).resolve(), required=True
        )
    parser.add_argument("--target", default="aarch64-apple-darwin")
    parser.add_argument("--compiler-revision", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--driver", type=lambda value: Path(value).resolve())
    args = parser.parse_args()
    if args.rounds < 1 or args.warmups < 0:
        parser.error("--rounds must be positive and --warmups nonnegative")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("--output must be empty to avoid stale benchmark data")
    args.output.mkdir(parents=True, exist_ok=True)
    host = args.bootstrap / args.target
    stage = host / "stage1"
    capture = json.loads(args.capture.read_text())
    driver = args.driver or build(host, args.output)
    resident_workspace = args.output / "resident-workspace"
    cargo_workspace = args.output / "cargo-workspace"
    for workspace in (resident_workspace, cargo_workspace):
        archive_ruff(args.repo, workspace)
    contents = text_variants(resident_workspace)
    require(contents == text_variants(cargo_workspace), "independent archives differed")
    command, env, native_binary = compiler_command(
        driver, capture, resident_workspace, args.output / "resident-target", stage
    )
    raw = {
        "compiler": compiler(stage, args.compiler_revision),
        "machine": machine(),
        "rounds": args.rounds,
        "warmup_rounds": args.warmups,
        "samples": [],
        "warmups": [],
    }
    prime = cargo_compile(
        stage,
        args.cargo_target,
        cargo_workspace,
        args.output / "cargo-prime",
        args.offline,
    )
    cargo_binary = prime.pop("executable")
    require(
        prime["returncode"] == 0 and cargo_binary is not None,
        f"initial Cargo build failed: {prime}",
    )
    raw["cargo_prime"] = prime
    for index in range(args.warmups + args.rounds):
        warming = index < args.warmups
        round_no = index + 1 if warming else index - args.warmups + 1
        round_name = f"{'warmup' if warming else 'round'}-{round_no}"
        for phase in PHASES:
            name, *_rest = phase
            directory = args.output / "logs" / round_name / name
            directory.mkdir(parents=True, exist_ok=True)
            if index % 2:
                cargo, cargo_binary = cargo_transaction(
                    stage,
                    args.cargo_target,
                    cargo_workspace,
                    contents,
                    phase,
                    directory / "cargo",
                    args.offline,
                    cargo_binary,
                )
                resident = resident_transaction(
                    command,
                    env,
                    resident_workspace,
                    native_binary,
                    contents,
                    phase,
                    directory / "resident",
                )
            else:
                resident = resident_transaction(
                    command,
                    env,
                    resident_workspace,
                    native_binary,
                    contents,
                    phase,
                    directory / "resident",
                )
                cargo, cargo_binary = cargo_transaction(
                    stage,
                    args.cargo_target,
                    cargo_workspace,
                    contents,
                    phase,
                    directory / "cargo",
                    args.offline,
                    cargo_binary,
                )
            row = {
                "round": round_no,
                "phase": name,
                "resident": resident,
                "cargo": cargo,
            }
            raw["warmups" if warming else "samples"].append(row)
            write_json(args.output / "raw.json", raw)
            print(
                f"{round_name}/{name}: {resident['outcome']}/{cargo['outcome']} resident={resident['external_ns'] / 1e6:.1f}ms cargo={cargo['external_ns'] / 1e6:.1f}ms",
                flush=True,
            )
    compact = summary(raw)
    write_json(args.output / "summary.json", compact)
    require(
        all(compact["validation"].values()),
        f"validation failed: {compact['validation']}",
    )
    print(json.dumps(compact["validation"], indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
