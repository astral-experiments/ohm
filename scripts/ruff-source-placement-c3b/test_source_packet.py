"""Check correct bytes, damaged inputs, names, file type, and refusal of the old C2 candidate."""

from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_packet as packet

with tempfile.TemporaryDirectory() as d:
    p = Path(d)
    files = {n: p / n for n in ("cpp", "native", "footer")}
    for k, path in files.items():
        path.write_bytes(("original-" + k).encode())
    candidate = {
        "candidate_files": {
            k: {"bytes": a.stat().st_size, "sha256": packet.sha(a.read_bytes())}
            for k, a in files.items()
        }
    }
    packet.bind_packet(candidate, files)

    def rejects(test):
        try:
            test()
        except (ValueError, FileNotFoundError):
            return
        raise AssertionError("incorrect source was accepted")

    rejects(lambda: packet.bind_packet(candidate, {k: v for k, v in files.items() if k != "cpp"}))
    rejects(lambda: packet.shape(p, packet.C2))
    for n in files:
        original = files[n].read_bytes()
        files[n].write_bytes(bytes([original[0] ^ 1]) + original[1:])
        rejects(lambda: packet.bind_packet(candidate, files))
        files[n].write_bytes(original)
    link = p / "link"
    link.symlink_to(files["cpp"])
    rejects(lambda: packet.bind_packet(candidate, files | {"cpp": link}))
print(
    "Independent source packet requires a new real candidate and exactly three matching regular file bodies."
)

# Both permitted parentage forms must bind real Git commits and the exact delta.
import subprocess
import os

with tempfile.TemporaryDirectory() as d:
    repo = Path(d) / "isolated-fixture"
    repo.mkdir()
    env = os.environ | {
        "GIT_AUTHOR_NAME": "Source packet test",
        "GIT_AUTHOR_EMAIL": "qa@example.invalid",
        "GIT_COMMITTER_NAME": "Source packet test",
        "GIT_COMMITTER_EMAIL": "qa@example.invalid",
    }

    def g(*args):
        return subprocess.check_output(["git", "-C", repo, *args], env=env, text=True).strip()

    g("init", "-q")
    keys = ("compiler/fixture/a", "compiler/fixture/b", "compiler/fixture/c", "compiler/fixture/d")
    p = repo / "compiler/fixture"
    p.mkdir(parents=True)
    for name in keys:
        (repo / name).write_text("parent:" + name)
    g("add", "--", "compiler")
    g("commit", "-qm", "parent")
    packet.PARENT = g("rev-parse", "HEAD")
    for name in keys[:3]:
        (repo / name).write_text("C2:" + name)
    g("add", "--", "compiler")
    g("commit", "-qm", "reference")
    packet.C2 = g("rev-parse", "HEAD")
    packet.C2_TREE = g("rev-parse", "HEAD^{tree}")
    for name in keys[:3]:
        (repo / name).write_text("candidate:" + name)
    g("add", "--", "compiler")
    g("commit", "-qm", "child")
    child = g("rev-parse", "HEAD")
    sibling = g(
        "commit-tree", "HEAD^{tree}", "-p", packet.PARENT, "-m", "independent direct candidate"
    )
    data = {name: repo / name for name in keys[:3]}
    for head, want in ((child, [packet.C2, child]), (sibling, [sibling])):
        actual = packet.shape(repo, head)
        assert [v.split()[0] for v in actual["actual_history"]] == want
        packet.bind_packet(actual, data)
    (repo / keys[3]).write_bytes(b"unspecified fourth file")
    g("add", "--", "compiler")
    g("commit", "-qm", "extra")
    rejects(lambda: packet.shape(repo, g("rev-parse", "HEAD")))
print("Both real Git histories reopened; a fourth source edit was refused.")
