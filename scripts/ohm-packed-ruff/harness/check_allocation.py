"""Calibrate all three allocation readers across independent roots and hard links."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
import count


def main(volume, out):
    out.mkdir()
    with tempfile.TemporaryDirectory(prefix="allocation-fixture-",dir=volume) as temp:
        folder=Path(temp)
        target,shared=folder/"target",folder/"build"
        target.mkdir()
        shared.mkdir()
        big=target/"object.o"
        big.write_bytes(bytes(range(256))*6145)
        os.link(big,shared/"link to object.o")
        (shared/"target-alias").symlink_to(target,target_is_directory=True)
        (target/"missing").symlink_to("absent")
        sparse=target/"sparse"
        with sparse.open("wb") as f:
            f.seek(2**25)
            f.write(b"end")
        sub=target/"incremental"/"a"/"s-0-old"
        sub.mkdir(parents=True)
        for i in range(40):
            (sub/f"small-{i}").write_bytes(bytes(i*97))
        first=count.census(target,shared,out)
        (shared/"link to object.o").unlink()
        second=count.census(target,shared)
        # Directory blocks may change but the link's former data must survive.
        assert abs(first["target_and_build_bytes"]-second["target_and_build_bytes"])<64*1024
        assert first["target_and_build_bytes"]<sparse.stat().st_size and first["target_and_build_bytes"]>=big.stat().st_size
        payload={"before":first,"after":second,
                 "tools":{tool:subprocess.check_output([tool,"--version"],text=True).splitlines()[0]
                          for tool in ("/usr/bin/du","/usr/bin/find")}}
        (out/"fixture.json").write_text(json.dumps(payload,sort_keys=True,indent=2)+"\n")


if __name__=="__main__":
    main(*map(Path,sys.argv[1:]))
