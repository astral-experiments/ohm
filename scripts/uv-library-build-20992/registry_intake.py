"""Prepare the public locked Cargo cache on a runner using its existing default registry policy."""
from pathlib import Path
import os
import sys
import tomllib
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import native
import material
def main():
    assert os.environ["GITHUB_REPOSITORY"]=="astral-experiments/ohm" and os.environ["GITHUB_REF"]=="refs/heads/charlie/codex-20992-production-build-guard"
    w=Path(os.environ["GITHUB_WORKSPACE"]);donor=w/"uv-donor";assert donor.is_dir()
    names=[];places=set()
    for p in (donor,native.SRC,w,Path(os.environ["HOME"])):
        for ancestor in (p,*p.parents):
            for cfg in ("config","config.toml"):places.add(ancestor/".cargo"/cfg)
    for p in sorted(places):
        if p.exists():
            policy=tomllib.loads(p.read_text())
            assert not any("replace-with"in v for v in policy.get("source",{}).values()),"existing Cargo source policy requires its own approved registry material"
            assert not policy.get("source",{}).get("crates-io",{}).get("registry") and not policy.get("registries",{}).get("crates-io",{}).get("index")
            names.append([p.name,native.sha(p)])
    assert not any(x.startswith("CARGO_SOURCE_") or x=="CARGO_REGISTRIES_CRATES_IO_INDEX" for x in os.environ)
    assert os.environ.get("CARGO_REGISTRIES_CRATES_IO_PROTOCOL","sparse")=="sparse"
    bank=native.TRANSIENT/"registry";data=material.registry(bank)
    native.save(native.ROOT/"registry.json",dict(data,existing_cargo_configuration=names))
if __name__=="__main__":main()

