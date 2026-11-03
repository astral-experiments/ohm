"""Extract the raw Cargo process, artifact, diagnostic and native-control records from the original job."""

import argparse
import hashlib
import io
import pathlib
import tarfile
import zipfile

EXPECTED = "8474cc422216800f8a7fd467827f8afbe874cc1488f38aa1c97717b6eebc447f"
ROOT_FILES = {
    "worker.json",
    "actual-sdk.json",
    "scope-sdks.json",
    "scope-kit-inline.json",
    "fixture-inline-P.json",
    "fixture-inline-C.json",
}
CARGO_PHASES = {
    "scope-old",
    "scope-old-unchanged",
    "scope-edit",
    "scope-traced-edit",
    "scope-new-unchanged",
    "scope-invalid",
    "scope-repaired",
    "scope-empty-new",
}
CARGO_FILES = {
    "command.json",
    "cargo.json",
    "native.json",
    "native-execs.json",
    "oracle",
    "oracle.o",
    "scope-rmetas.json",
    "stdout",
}
CLI_PHASES = {"scope-cli-old", "scope-cli-new", "scope-cli-empty-new"}


def keep(path):
    parts = pathlib.PurePosixPath(path).parts
    if path in ROOT_FILES:
        return True
    if parts[0] == "adt-rsic-upgrade":
        return parts[-1] in {"terminal.json", "result.json", "registration.json"}
    if parts[0] not in {"inline-P", "inline-C"}:
        return False
    if len(parts) == 2:
        return parts[1] in {
            "provenance.json",
            "scope-admitted.json",
            "scope-check-admitted.json",
        }
    if len(parts) == 3:
        return (
            parts[1] in CARGO_PHASES
            and parts[2] in CARGO_FILES
            or parts[1] in CLI_PHASES
            and parts[2] in {"command.json", "scope-cli.json"}
        )
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()
    with args.archive.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == EXPECTED
    with zipfile.ZipFile(args.archive) as source, tarfile.open(
        args.output, "w:xz", preset=3
    ) as target:
        for name in sorted(n for n in source.namelist() if keep(n)):
            body = source.read(name)
            member = tarfile.TarInfo(name)
            member.size = len(body)
            member.mode = 0o644
            target.addfile(member, io.BytesIO(body))


if __name__ == "__main__":
    main()
