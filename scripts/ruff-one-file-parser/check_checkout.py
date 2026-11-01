"""Exercise the real Git transplant and scope refusals in a disposable sparse checkout of B."""

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import protocol as p

f = p.f


def check(donor):
    common = Path(
        f.git(donor, "rev-parse", "--path-format=absolute", "--git-common-dir").decode().strip()
    )
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        f.git(repo, "init", "-q", "--template=", "-b", f.BRANCH.split("/")[-1])
        (repo / ".git/objects/info/alternates").write_text(str(common / "objects") + "\n")
        f.git(repo, "config", "core.sparseCheckout", "true")
        (repo / ".git/info").mkdir(exist_ok=True)
        (repo / ".git/info/sparse-checkout").write_text("/" + f.SRC + "\n")
        f.git(repo, "update-ref", f.BRANCH, f.B)
        f.git(repo, "read-tree", "-mu", "HEAD")
        source = [f.state(repo, "baseline")]
        for a, b in [
            ("baseline", "edited"),
            ("edited", "invalid"),
            ("invalid", "edited"),
            ("edited", "baseline"),
        ]:
            p.change(repo, a, b)
            source.append(f.state(repo, b))
        f.require(
            source[0] == source[-1]
            and source[1] == source[3]
            and len({v["index_sha256"] for v in source}) == 1,
            "unexpected Git mutation",
        )

        def reject():
            try:
                f.change_control(repo, "baseline")
            except ValueError:
                return
            raise ValueError("unregistered edit was admitted")

        p.change(repo, "baseline", "edited")
        alien = repo / "unexpected"
        alien.write_text("alien")
        reject()
        alien.unlink()
        f.git(repo, "add", "--", f.SRC)
        reject()
        f.git(repo, "restore", "--staged", "--", f.SRC)
        old = (repo / f.SRC).read_bytes()
        (repo / f.SRC).write_bytes(old + b"// different parser edit\n")
        reject()
        (repo / f.SRC).write_bytes(old)
        p.change(repo, "edited", "baseline")
        f.require(f.git(repo, "write-tree").decode().strip() == f.B_TREE, "staged postimage")
        return dict(
            states=source,
            refused=["unexpected working file", "staged parser edit", "incorrect parser body"],
        )


if __name__ == "__main__":
    print(json.dumps(check(Path(sys.argv[1]).resolve(strict=True)), sort_keys=True))
