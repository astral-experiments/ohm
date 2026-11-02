"""Positive and negative controls for the frozen source enrollment and Rust Debug classifier."""
import collections
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import capture
import reopen

def main():
    spec = json.loads((HERE/"keys.json").read_bytes())
    assert len(spec["context"]) == len({tuple(x) for x in spec["context"]}) == 1426
    nodes = [r["node"] for r in spec["primary"]]
    assert collections.Counter(r["name"] for r in nodes) == {"fn_abi_of_instance_no_deduced_attrs":19,"symbol_name":16,"upstream_monomorphizations_for":12,"layout_of":1,"codegen_unit":1}
    assert len({(r["kind"],r["key"]) for r in nodes})==30
    assert capture.sha(HERE/"original-owner-A.nul") == spec["original_owner_sha256"]
    arg = (HERE/"original-owner-A.nul").read_bytes().rstrip(b"\0").decode().split("\0")
    assert len(arg)==621 and capture.selected(arg[1:])
    assert not capture.selected(["--crate-name","other","--crate-type","lib","--emit=link"])
    assert not capture.selected(["--crate-name","ruff_workspace","--crate-type","lib","--emit=metadata"])
    identity = capture.original_identity(arg[1:])
    assert "metadata=4f331947cad33b82" in identity["configuration"]
    assert len(set(identity["extern_names"])) == 34 and collections.Counter(identity["extern_names"])["pep440_rs"] == 2
    item = "Instance { def: Item(DefId(0:6 ~ fixture[1234]::stable)), args: [] }"
    generic = item.replace("args: []","args: [core::option::Option<u32>]")
    closure = item.replace("stable","stable::{closure#0}")
    assert reopen.classify("symbol_name",item)["class"] == "ordinary Item with no substitutions"
    assert reopen.classify("symbol_name",generic)["class"] == "instantiated generic item"
    assert reopen.classify("symbol_name",closure)["class"] == "closure or coroutine"
    assert reopen.classify("symbol_name",item.replace("Item(","DropGlue("))["class"]=="non-Item DropGlue"
    abi = "PseudoCanonicalInput { typing_env: " + reopen.NEUTRAL + ", value: (" + item + ", []) }"
    assert reopen.classify("fn_abi_of_instance_no_deduced_attrs",abi)["class"]=="ordinary Item with no substitutions"
    assert reopen.classify("fn_abi_of_instance_no_deduced_attrs",abi.replace(", []) }",", [u16]) }"))["class"]=="empty item substitutions with additional ABI context"
    assert reopen.classify("fn_abi_of_instance_no_deduced_attrs",abi.replace("Codegen","PostAnalysis"))["class"]=="empty item substitutions with additional ABI context"
    assert reopen.classify("symbol_name","unknown")["class"]=="unrecognized instance"

if __name__ == "__main__":
    main()
