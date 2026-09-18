#!/usr/bin/env python3
"""Exercise the resident-to-test-build bridge with a tiny, real rustc test binary."""

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

MAIN = """#[path = "other.rs"]
mod other;

fn behavior() -> bool {
    true
}

#[test]
fn test_behavior() {
    assert!(behavior());
    assert!(other::call());
}
"""

OTHER = """fn unrelated() -> bool {
    true
}

pub fn call() -> bool {
    unrelated()
}
"""

SENTINEL = b"previous executable; never run this sentinel\n"


@dataclass(frozen=True)
class Operation:
    source: str
    contents: str
    mode: str | None
    errors: int | None = None


@dataclass(frozen=True)
class Case:
    name: str
    operations: tuple[Operation, ...]
    build_version: int
    rejection: str | None = None
    test_exit: int | None = None
    sentinel: bool = False


def scalar(source, replacement):
    assert source.count("    true") == 1
    return source.replace("    true", "    " + replacement)


def cases():
    behavior = Operation("lib.rs", scalar(MAIN, "false"), "resident", 0)
    error = Operation("lib.rs", scalar(MAIN, "0u8"), "resident", 1)
    repair = Operation("lib.rs", MAIN, "resident", 0)
    return (
        Case("baseline", (), 0, test_exit=0),
        Case("behavior-edit", (behavior,), 1, test_exit=101),
        Case("behavior-repair", (behavior, repair), 2, test_exit=0),
        Case("type-error", (error,), 1, "accepted-source-has-errors"),
        Case("type-error-repair", (error, repair), 2, test_exit=0),
        Case("wrong-version", (), 1, "source-version-is-not-current", sentinel=True),
        Case(
            "unchecked-edit",
            (Operation("other.rs", scalar(OTHER, "false"), None),),
            0,
            "source-on-disk-does-not-match-accepted-revision",
            sentinel=True,
        ),
        Case(
            "unsupported-edit",
            (
                Operation(
                    "other.rs",
                    OTHER.replace("unrelated() -> bool", "unrelated() -> char"),
                    "fallback",
                    0,
                ),
            ),
            1,
            "source-revision-requires-fresh-compiler",
            sentinel=True,
        ),
        Case(
            "unrelated-error",
            (Operation("other.rs", scalar(OTHER, "0u8"), "resident", 1), behavior),
            2,
            "accepted-source-has-errors",
            sentinel=True,
        ),
    )


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_lines(stream, queue):
    try:
        for line in stream:
            queue.put(line.rstrip("\n"))
    finally:
        queue.put(None)


def run_case(case, args):
    directory = args.output / case.name
    directory.mkdir()
    sources = {name: directory / name for name in ("lib.rs", "other.rs")}
    for path, source in ((sources["lib.rs"], MAIN), (sources["other.rs"], OTHER)):
        path.write_text(source)
    artifact = directory / ("test.exe" if os.name == "nt" else "test")
    if case.sentinel:
        artifact.write_bytes(SENTINEL)

    command = [
        str(args.driver),
        "--edition=2024",
        "--sysroot",
        str(args.stage),
        "-Zohm-resident-query-graph",
        "--error-format=json",
        "--test",
        "--crate-name",
        "resident_test_guard",
        str(sources["lib.rs"]),
        "-o",
        str(artifact),
    ]
    stderr_path = directory / "compiler.stderr"
    transcript = []
    queue = Queue()
    proc = None
    reader = None

    def receive(kind):
        try:
            line = queue.get(timeout=args.timeout)
        except Empty:
            raise RuntimeError(f"timed out waiting for {kind!r}") from None
        require(line is not None, f"compiler closed stdout before {kind!r}")
        transcript.append(line)
        fields = line.split("\t")
        require(fields[0] == kind, f"expected {kind!r}, got {line!r}")
        return fields[1:]

    def send(line):
        proc.stdin.write(line + "\n")
        proc.stdin.flush()

    try:
        with stderr_path.open("w") as stderr:
            proc = subprocess.Popen(
                command,
                cwd=directory,
                env=dict(
                    os.environ,
                    OHM_RUFF_SOURCE_MODE="resident-build",
                    RUSTC_BOOTSTRAP="1",
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                encoding="utf-8",
            )
            reader = Thread(target=read_lines, args=(proc.stdout, queue), daemon=True)
            reader.start()
            ready = receive("ready")
            require(len(ready) == 2, f"unexpected ready fields: {ready!r}")

            checks = []
            version = 0
            for operation in case.operations:
                path = sources[operation.source]
                path.write_text(operation.contents)
                if operation.mode is None:
                    continue
                version += 1
                send(f"check\t{version}\t{path}")
                result = receive("result")
                require(len(result) == 14, f"unexpected check fields: {result!r}")
                require(result[0] == str(version), f"wrong check version: {result!r}")
                require(result[1] == operation.mode, f"wrong check route: {result!r}")
                require(
                    int(result[5]) == operation.errors,
                    f"wrong check errors: {result!r}",
                )
                checks.append(
                    {
                        "source": operation.source,
                        "route": result[1],
                        "reason": result[2],
                        "errors": int(result[5]),
                    }
                )

            send(f"build\t{case.build_version}")
            build = receive("build")
            expected_route = "rejected" if case.rejection else "ready"
            require(
                build
                == [str(case.build_version), expected_route, case.rejection or "-"],
                f"unexpected build response: {build!r}",
            )
            proc.stdin.close()
            compiler_exit = proc.wait(timeout=args.timeout)
            reader.join(timeout=args.timeout)
            require(not reader.is_alive(), "compiler stdout did not close")
            while not queue.empty():
                line = queue.get_nowait()
                if line is not None:
                    transcript.append(line)

        stages = [
            line.split("\t")[0] for line in transcript if line.startswith("build-")
        ]
        result = {
            "case": case.name,
            "checks": checks,
            "build_route": expected_route,
            "build_rejection": case.rejection,
            "compiler_exit": compiler_exit,
            "test_invoked": False,
            "test_exit": None,
            "stale_artifact_preserved": None,
        }
        if case.rejection:
            require(compiler_exit != 0, "rejected build exited successfully")
            require(
                not stages, f"rejected build reached later compiler stages: {stages!r}"
            )
            if case.sentinel:
                preserved = artifact.read_bytes() == SENTINEL
                require(
                    preserved, "rejected compiler overwrote the old executable sentinel"
                )
                result["stale_artifact_preserved"] = preserved
            else:
                require(
                    not artifact.exists(), "rejected compiler produced an executable"
                )
        else:
            require(compiler_exit == 0, f"compiler exited with {compiler_exit}")
            require(artifact.is_file(), "successful build produced no executable")
            require(
                stages == ["build-analysis", "build-finished"],
                f"unexpected compiler stage acknowledgements: {stages!r}",
            )
            # The only branch that executes an artifact requires both current-version compiler
            # acceptance and a successful process exit; rejected sentinels can never reach it.
            test = subprocess.run(
                [str(artifact), "--exact", "test_behavior"],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=args.timeout,
                check=False,
            )
            (directory / "test.stdout").write_text(test.stdout)
            (directory / "test.stderr").write_text(test.stderr)
            require(
                "running 1 test" in test.stdout,
                "test binary did not run the selected test",
            )
            require(
                test.returncode == case.test_exit,
                f"test returned {test.returncode}, expected {case.test_exit}",
            )
            result["test_invoked"] = True
            result["test_exit"] = test.returncode
        return result
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"{case.name}: {error}; inspect {stderr_path}") from error
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            if reader is not None:
                reader.join(timeout=args.timeout)
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            if proc.stdout:
                proc.stdout.close()
        (directory / "compiler.stdout").write_text("\n".join(transcript) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--driver", required=True, type=Path, help="compiled source-driver binary"
    )
    parser.add_argument(
        "--stage",
        required=True,
        type=Path,
        help="matching patched rustc stage1 sysroot",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="new or empty scratch directory"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60,
        help="seconds to wait for each subprocess step",
    )
    args = parser.parse_args()
    args.driver = args.driver.resolve(strict=True)
    args.stage = args.stage.resolve(strict=True)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        parser.error(f"output directory must be empty: {args.output}")
    if args.timeout <= 0:
        parser.error("timeout must be positive")

    results = [run_case(case, args) for case in cases()]
    summary = {"schema_version": 1, "passed": len(results), "cases": results}
    serialized = json.dumps(summary, indent=2) + "\n"
    (args.output / "summary.json").write_text(serialized)
    print(serialized, end="")


if __name__ == "__main__":
    main()
