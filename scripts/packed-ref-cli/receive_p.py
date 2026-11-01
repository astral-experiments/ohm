"""Run the frozen native source verifier in a clean interpreter before selecting P."""

import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import packed_sdk as spec


def source_reader(source):
    directory = source / "scripts/gnu-same-revision-donor"
    sys.path.insert(0, str(directory))
    import receive_source as original
    import reopen

    spec.need(
        Path(reopen.__file__).resolve() == directory / "reopen.py"
        and subprocess.check_output(
            ["git", "-C", source, "rev-parse", "HEAD"], text=True
        ).strip()
        == spec.SOURCE_QA,
        "wrong source qualification reader",
    )
    return original, reopen


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--source-preflight":
        original, _ = source_reader(Path(sys.argv[2]).resolve(strict=True))
        raw = gzip.decompress((HERE / "inputs/source-run-catalog.json.gz").read_bytes())
        spec.need(
            __import__("hashlib").sha256(raw).hexdigest()
            == "03f2b1fc275c25c7f760bfb43e6c99f805248bdef0a1c0fea8b020743669d7d9",
            "changed source catalog fixture",
        )
        v = json.loads(raw)
        cert = original.check_job(
            spec.SOURCE_QA,
            spec.SOURCE_RUN,
            spec.SOURCE_JOB,
            v["run"],
            v["jobs"],
            v["artifacts"],
        )
        spec.need(
            cert == spec.enrolled()["artifacts"],
            "the isolated source reader selected different media",
        )
        return
    source, inbox, donor, dest, receipts = map(Path, sys.argv[1:])
    directory = source / "scripts/gnu-same-revision-donor"
    original, reopen = source_reader(source)

    def get(suffix):
        return json.loads(
            subprocess.check_output(
                ["gh", "api", "repos/astral-experiments/ohm/actions/" + suffix],
                cwd=source,
            )
        )

    path = f"runs/{spec.SOURCE_RUN}"
    catalog = original.check_job(
        spec.SOURCE_QA,
        spec.SOURCE_RUN,
        spec.SOURCE_JOB,
        get(path),
        get(path + "/attempts/1/jobs?per_page=100"),
        get(path + "/artifacts?per_page=100"),
    )
    expected = spec.enrolled()
    spec.need(
        catalog == expected["artifacts"],
        "source archives differ from independent enrollment",
    )
    folders = [inbox / "verified-source", inbox / "verified-sdk"]
    for role, folder, kinds in zip(
        original.ARTIFACTS,
        folders,
        [{"host-entry", "P", "source-qualified.json"}, {"sdk"}],
        strict=True,
    ):
        artifact = catalog[role]
        zip_path = inbox / (role + ".zip")
        with zip_path.open("xb") as output:
            subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/astral-experiments/ohm/actions/artifacts/{artifact['id']}/zip",
                ],
                stdout=output,
                check=True,
            )
        original.extract(zip_path, folder, artifact, kinds)
    raw, logs = folders
    result = reopen.verify(raw, logs, None)
    spec.need(
        result == expected["source"]
        and spec.read(raw / "source-qualified.json")
        == result | {"physical_installation_reopened": True},
        "source-native tests, historical D rejection or donor closure differ",
    )
    subprocess.run(
        [
            sys.executable,
            "-IB",
            directory / "overlay.py",
            raw / "P/overlay",
            logs,
            donor,
            dest,
        ],
        check=True,
    )
    shutil.copyfile(raw / "P/native-qualified.json", receipts / "p-native-source.json")
    shutil.copyfile(raw / "source-qualified.json", receipts / "p-published-source.json")
    (receipts / "p-official.json").write_text(
        json.dumps(expected, sort_keys=True, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
