"""Guard the source package, registry, generated nominal client, and HTML reader before bootstrap."""
import gzip
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inputs
import reopen


def reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("accepted invalid fixture")


def main():
    with tempfile.TemporaryDirectory() as name:
        root = Path(name)
        original = inputs.write_source(root / "work")
        assert len(inputs.BIND["ruff"]["blobs"]) == 19
        assert inputs.BIND["ruff"]["commit"] == "93526150df078af7dd8fc4226cdcc469539d2001"
        assert b"code.line_start(code.line_index(offset))" in original["facade/src/lib.rs"]
        assert b"facade::line_start" in original["client/src/main.rs"]
        inputs.registry(root / "cargo", original["Cargo.lock"], "index.crates.io-1949cf8c6b5b557f")
        reject(lambda: inputs.registry(root / "bad", original["Cargo.lock"] + b"\n", "index.crates.io-1949cf8c6b5b557f"))
        reject(lambda: inputs.members("ruff-inputs.tar.gz", [0, "0" * 64], 1 << 20))
        html = dict(zip(reopen.PAGES, (
            b'<a href="struct.TextSize.html">TextSize</a><a href="fn.line_start.html">line_start</a>',
            b"<h1>TextSize</h1><p>A measure of text length.</p>",
            b"<h1>line_start TextSize</h1><p>Returns the start of the line that contains the given byte offset.</p>",
        )))
        def write(page, data):
            (root / (page + ".gz")).write_bytes(gzip.compress(data, mtime=0))
            return reopen.sha(data)
        seals = {page:write(page, data) for page,data in html.items()}
        reopen.pages(root, seals)
        reject(lambda: reopen.pages(root, seals | {"index.html":"1" * 64}))
        seals["index.html"] = write("index.html", html["index.html"].replace(b"fn.line_start", b"other_function"))
        reject(lambda: reopen.pages(root, seals))
    print("Ruff source, 42 locked entries, nominal source and HTML positive/refusals passed")


if __name__ == "__main__":
    main()
