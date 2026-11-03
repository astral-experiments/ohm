"""Bind each staged source change to the exact upstream release before a native build."""

import hashlib, io, json, subprocess, sys, tarfile, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "e2e-existing-output"
sys.path[:0] = [str(HERE), str(PREVIOUS)]
import multi_source, prepare_reuse, prepare_source


def run(repo):
    git = lambda *a: subprocess.check_output(["git", "-C", repo, *a])
    h = lambda raw: hashlib.sha256(raw).hexdigest()
    pin = prepare_source.BASE
    with tempfile.TemporaryDirectory() as temp:
        p = Path(temp)
        data = git("archive", pin, "libwild/src", "wild/src/main.rs")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as t:
            t.extractall(p, filter="data")
        original = prepare_reuse.base.prepare
        try:
            prepare_reuse.base.prepare = prepare_source.apply_diagnostic
            names = multi_source.apply(p)
        finally:
            prepare_reuse.base.prepare = original
        current = {n: h((p / n).read_bytes()) for n in names}
        previous = json.loads((PREVIOUS / "source-preflight.json").read_bytes())[
            "after"
        ]
        assert current.keys() == previous.keys()
        changes = sorted(k for k in current if current[k] != previous[k])
        assert changes == [
            "libwild/src/frozen.rs",
            "libwild/src/lib.rs",
            "libwild/src/reuse.rs",
        ]
        code = (p / "libwild/src/lib.rs").read_text()
        for mark in (
            "FRESH-PUBLISH",
            "if let Some((bytes, donor))",
            "crate::reuse::published_new_generation",
            "crate::frozen::generated_input()",
        ):
            assert code.count(mark) == 1, mark
        seed = json.loads(
            (
                HERE.parent / "workspace-link-proof/first-ordinary/reopened.json"
            ).read_bytes()
        )
        expected = json.loads((HERE / "accepted-48.json").read_bytes())
        assert (
            expected == seed["decisions"]["first-unchanged"]["strict_equal_roles"]
            and len(expected) == 48
        )
        return {
            "pin": pin,
            "tree": git("rev-parse", pin + "^{tree}").decode().strip(),
            "after": current,
            "changed_from_one_output": changes,
            "first-ordinary": 41727051091,
            "first-ordinary-sha256": "82148079f32d04d8d230d7a6c264c0a42407c038b61dc62e14b0d08095292eee",
            "accepted_roles_sha256": h((HERE / "accepted-48.json").read_bytes()),
        }


if __name__ == "__main__":
    print(json.dumps(run(Path(sys.argv[1])), sort_keys=True, indent=2))
