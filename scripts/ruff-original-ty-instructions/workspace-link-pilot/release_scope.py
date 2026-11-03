"""Use only the registered original signed command shape for the requested release."""

import gzip, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def for_release(release):
    old = json.loads((HERE.parent / "workspace-link-proof/roles.json").read_bytes())
    if release == 23:
        return old
    assert release == 24
    raw = gzip.decompress((HERE / "signed-24-templates.json.gz").read_bytes())
    assert (
        hashlib.sha256(raw).hexdigest()
        == "880b522c57a0a214d3014457445d7c597930047a179799ce84783dc0ef9dfa4e"
    )
    packet = json.loads(raw)
    assert (
        packet["signed_run"] == 41722651807 and packet["variants"].keys() == old.keys()
    )
    new = {}
    for k, choices in packet["variants"].items():
        (spec,) = choices
        assert spec["owner"] == old[k]["owner"]
        new[k] = spec
    return new
