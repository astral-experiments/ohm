"""Reopen the complete bounded first attempt, including parent constructors and both native build errors."""

from hashlib import sha256
import json
from pathlib import Path
import zipfile

path = Path(__file__).resolve().parent / "original.zip"
assert path.stat().st_size == 52_900
assert sha256(path.read_bytes()).hexdigest() == "1d3ccbbc256f6aa5af0d1258391e850b6a9fdb561c3b894f72a5633ec12f08f4"
with zipfile.ZipFile(path) as z:
    assert len(z.namelist()) == len(set(z.namelist())) == 12 and z.testzip() is None
    entry = json.loads(z.read("entry.json"))
    assert entry["qa"] == "0509c465a456a4f10d7f422831cc4f4bfb57821e"
    source = json.loads(z.read("selected-actual-source.json"))
    assert source["subject"] == "a9d85b2241b2661d6b6615a0ed1aaf5ca7558b2b"
    parent = json.loads(z.read("P-constructed.json"))
    assert parent["source"]["revision"] == "531eb1980c08c75ccbf3f6b77adbee53cd9b8bd5"
    assert parent["total_physical_execs"] == 1667 and all(parent["rustc_crates"].values())
    assert parent["cxx"]["OhmRegisterCoalescer.cpp"] and not parent["cxx"]["OhmSourcePlacement.cpp"]
    assert parent["native_selection"] == sha256(z.read("P-constructors.jsonl.gz")).hexdigest()
    assert json.loads(z.read("P-docs.json"))["source"] == parent["source"]["revision"]
    assert "C-constructed.json" not in z.namelist() and "factory.json" not in z.namelist()
    error = z.read("build-C.log")
    assert error.count(b"error[E0599]: no method named `iter` found for enum `LlvmConfigOutput`") == 2
    for location in (b"269:17", b"270:22"):
        assert error.count(b"compiler/rustc_llvm/build.rs:" + location) == 1
    assert b"could not compile `rustc_llvm` (build script) due to 2 previous errors" in error

print("Parent, rustdoc and native constructors verified; both Rust build-script errors reproduced. Zero candidate SDKs or hardware observations.")
