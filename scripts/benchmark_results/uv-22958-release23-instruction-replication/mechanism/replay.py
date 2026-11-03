"""Count actual typeck_root calls at the external provider boundary in two raw Callgrind files."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
TARGET = "rustc_query_impl::query_vtables::typeck_root::invoke_provider_fn::__rust_begin_short_backtrace"
GRAPH_SHA = "8acb671d5ac900cdd4bef3f554b49f84f90f45898870be879d7d78b6d3ed4d2d"
EXPECTED = {"R": ("58de632bdddbdf35d73ffe36afd12f9016d18a4ef287f35b83a4601944610b65",
                  "616d7ef089752dde404289fbc396f08cb4ccc295f51489151d751541fb009fe0"),
            "F": ("5460cd0d5ff15caff6bfb9eac33ae92dd46d254d5d69d24ba85ef4fa05f99ddb",
                  "a9ab23fe3b949f7c340e85c36f713549569e468028d61510b4a78b34ddd65b77")}


def hash_bytes(b):
    return hashlib.sha256(b).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


class Profile:
    def __init__(self, path):
        self.path = path

    def open(self):
        return gzip.open(self.path, "rt")


def verify(role, graph, lock):
    raw_sha, admission_sha = EXPECTED[role]
    source = HERE / (role + "-native.json")
    raw = HERE / (role + ".callgrind.gz")
    admission = read(source)
    origin = read(HERE / "providers.json")[role]
    assert hash_bytes(source.read_bytes()) == admission_sha == origin["accepted"]
    assert admission["raw"] == origin["raw"] and admission["unscored"]
    data = gzip.decompress(raw.read_bytes())
    assert len(data) == origin["raw"]["bytes"] and hash_bytes(data) == raw_sha == origin["raw"]["sha256"]
    physical = HERE / (role + "-physical.json")
    assert hash_bytes(physical.read_bytes()) == origin["physical"]
    if role == "F":
        assert admission["role"] == lock["sources"]["F"]
        assert read(physical)["exit"] == 1 and admission["stopped_after_all_native_gates"] and admission["unmodified_selector_gate"]
        assert hash_bytes((HERE / "F-original-refusal.log").read_bytes()) == admission["original_error"]
        assert admission["raw"]["original"] == f"guest/raw/raw.{admission['pid']}.2"
        assert set(admission["negative_controls"]) == {"wrong_pid", "wrong_filename", "altered_full_argv"}
    else:
        assert admission["signed"] == lock["sources"]["R"]["commit"] and read(physical)["exit"] == 0
        assert hash_bytes(raw.read_bytes()) == origin["raw"]["gzip_sha256"]
    h, own, edges, calls, objects = graph(Profile(raw))
    assert h["pid"] == admission["pid"] == origin["pid"]
    assert h["cmd"] == " ".join(admission["argv"]) and h["Ir"] == sum(own.values()) == origin["total_guest_Ir"]
    assert hash_bytes(json.dumps(admission["argv"],separators=(",",":")).encode()) == origin["argv"]
    assert admission["target_externs"] == origin["selected_externs"] == 64 and admission["sibling_externs"] == 30
    pattern = re.compile(re.escape(TARGET) + r"(?:'\d+)?")
    nodes = {n for n in own if pattern.fullmatch(re.sub(r"\[[0-9a-f]{8,16}\]","",n))}
    assert nodes and sorted(nodes) == origin["native_symbol_variants"]
    drivers = {Path(ob).name for n in nodes for ob in objects[n]}
    driver_paths = {k for k in lock["raw"][role] if k.startswith("lib/librustc_driver-")}
    driver, = driver_paths
    assert drivers == {Path(driver).name}
    incoming = [(a,b,n,calls[a,b]) for (a,b),n in edges.items() if a not in nodes and b in nodes]
    incoming_ir = sum(n for _,_,n,_ in incoming)
    external_calls = sum(c for *_,c in incoming)
    outgoing_ir = sum(n for (a,b),n in edges.items() if a in nodes and b not in nodes)
    assert [list(r) for r in incoming] == origin["callers"] and external_calls == origin["provider_calls"]
    assert incoming_ir == origin["provider_inclusive_guest_Ir"] == sum(own[n] for n in nodes) + outgoing_ir
    return {"pid": h["pid"], "rustc": lock["sources"][role]["commit"], "driver_sha256": lock["raw"][role][driver]["sha256"],
            "guest_instructions": h["Ir"], "provider_calls": external_calls, "provider_guest_instructions": incoming_ir,
            "native_argv_sha256": origin["argv"], "raw_sha256": raw_sha}


def main():
    assert __debug__
    parser = HERE / "callgrind.py"
    assert hash_bytes(parser.read_bytes()) == GRAPH_SHA
    graph = runpy.run_path(str(parser))["read"]
    lock = read(HERE.parent / "reader/signed-23-split-lock.json")
    results = {role: verify(role, graph, lock) for role in ("R", "F")}
    assert results["R"]["native_argv_sha256"] == results["F"]["native_argv_sha256"]
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
