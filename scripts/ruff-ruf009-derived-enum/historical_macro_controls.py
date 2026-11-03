"""Exercise the frozen older macro images with the actual stage1 Rust tools, outside Cargo histories."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import external


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def materialize():
    prior = HERE / "evidence-precounter-41616388897"
    reg = json.loads((prior / "four-real-macros.json").read_bytes())
    capture = prior / "original.zip"
    assert digest(capture.read_bytes()) == reg["before_counter_zip"]
    with zipfile.ZipFile(capture) as z:
        base = subprocess.check_output(
            ["zstd", "-qdc"], input=z.read("C/registry-prefix/compiled-macro.so.zst")
        )
    assert digest(base) == reg["base"] and len(base) == 3_204_376
    compressed = (prior / "three-literal-xor.zst").read_bytes()
    assert digest(compressed) == reg["delta_sha256"]
    delta = subprocess.check_output(["zstd", "-qdc"], input=compressed)
    assert digest(delta) == reg["delta_expanded_sha256"] and len(delta) == 3 * len(base)
    images = {}
    at = 0
    for h in sorted(reg["inputs"]):
        if h == reg["base"]:
            body = base
        else:
            body = bytes(x ^ y for x, y in zip(base, delta[at : at + len(base)]))
            at += len(base)
        assert digest(body) == h and body[:4] == b"\x7fELF"
        images[h] = body
    assert at == len(delta)
    return images


def classify(base):
    """Read all eight original compiler diagnostics again on the separate receiver."""
    reg = json.loads((HERE / "evidence-precounter-41616388897/four-real-macros.json").read_bytes())
    out = base / "prior-get-size-0.5.1-controls"
    sdks = json.loads((base / "scope-sdks.json").read_bytes())
    rows = {}
    for role in ("P", "C"):
        for h in sorted(reg["inputs"]):
            name = role + "-" + h
            actual = external.read_expansion(out / ("expansion-" + name))
            assert actual["macro"] == h
            rows[name] = {"driver": sdks["inline-" + role]["driver"], "result": actual}
    assert {rows["P-" + h]["driver"] for h in reg["inputs"]} != {
        rows["C-" + h]["driver"] for h in reg["inputs"]
    }
    assert all(rows["P-" + h]["result"] == rows["C-" + h]["result"] for h in reg["inputs"])
    assert (
        len({tuple(e[0] for e in rows["P-" + h]["result"]["errors"]) for h in reg["inputs"]}) >= 2
    ), "the four complete native images must exercise different real ordered conflicts"
    return rows


def offline():
    """Reopen the original refusal and reject five independent changes to its genuine messages."""
    from tempfile import TemporaryDirectory
    from copy import deepcopy

    prior = HERE / "evidence-precounter-41616388897"
    frozen = json.loads((prior / "offline.json").read_bytes())
    images = materialize()
    with zipfile.ZipFile(prior / "original.zip") as z, TemporaryDirectory() as tmp:
        assert not any(n.endswith("/hardware.json") for n in z.namelist())
        folder = Path(tmp)
        names = ("command.json", "stdout", "stderr")
        src = "C/registry-prefix/expansion-after-registry-seed/"
        for n in names:
            (folder / n).write_bytes(z.read(src + n))
        actual = external.read_expansion(folder)
        assert actual == frozen["archived_macro"] and actual["macro"] in images
        original = [json.loads(line) for line in (folder / "stderr").read_bytes().splitlines()]
        stdout = (folder / "stdout").read_bytes()
        for label in (
            "unknown conflict",
            "wrong named pair",
            "weakened span",
            "extra compiler error",
            "wrong valid expansion",
        ):
            rows = deepcopy(original)
            edited = stdout
            if label == "unknown conflict":
                rows[0]["children"][0]["message"] += " not present in the original"
            elif label == "wrong named pair":
                rows[1]["children"][0]["message"] = original[2]["children"][0]["message"]
            elif label == "weakened span":
                rows[1]["spans"][0]["byte_start"] -= 1
            elif label == "extra compiler error":
                rows.insert(2, rows[0])
            else:
                edited = stdout.replace(b"2usize", b"3usize")
                assert edited != stdout
            (folder / "stdout").write_bytes(edited)
            (folder / "stderr").write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in rows))
            try:
                external.read_expansion(folder)
            except ValueError as err:
                assert str(err) == frozen["mutations"][label], (label, err)
            else:
                raise AssertionError(("damaged original passed", label))
        # A true reverse wording is a separate output, even though the named pair is the same.
        altered = deepcopy(original)
        msg = altered[1]["children"][0]["message"]
        altered[1]["children"][0]["message"] = msg.replace(
            "`ignore` conflicts with mutually exclusive `size`",
            "`size` conflicts with mutually exclusive `ignore`",
        )
        assert altered[1]["children"][0]["message"] != msg
        (folder / "stdout").write_bytes(stdout)
        (folder / "stderr").write_bytes(b"".join(json.dumps(row).encode() + b"\n" for row in altered))
        changed = external.read_expansion(folder)
        assert changed["errors"] != actual["errors"] and changed["stderr"] != actual["stderr"]
    print("Reopened the original refusal, all four actual plugin binaries, and five input mutations")


def main():
    import case

    images = materialize()
    out = case.BASE / "prior-get-size-0.5.1-controls"
    out.mkdir()
    scratch = case.ROOT / "unscored-historical-macro-diagnostics"
    scratch.mkdir()
    proof = {}
    for role in ("P", "C"):
        kit = case.old.activate(role)
        for h, body in images.items():
            place = scratch / h
            place.mkdir(exist_ok=True)
            sdk_macro = place / "libget_size_derive2.so"
            if not sdk_macro.exists():
                sdk_macro.write_bytes(body)
            assert digest(sdk_macro.read_bytes()) == h
            name = role + "-" + h
            result = external.actual_expansion(out, name, sdk_macro, case.env(), scratch)
            assert result["macro"] == h
            proof[name] = {"driver": kit["driver"], "result": result}
    assert classify(case.BASE) == proof
    case.save(out / "verified.json", proof)
    print(
        "Four physical get-size-derive2 0.5.1 plugins, both real compilers",
        [(h, v["result"]["errors"][0][0]) for h, v in proof.items() if h.startswith("P-")],
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--offline"]:
        offline()
    else:
        assert not sys.argv[1:]
        main()
