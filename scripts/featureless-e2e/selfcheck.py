"""Exercise the kernel descendant classifier and its no-PMU rejection without compiling Ruff."""
import argparse
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "mixed-generics-ruff")]
import cost
import counter

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("counter_directory", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        b = counter.build(root, args.counter_directory)
        for mode in ("cal", "sham"):
            d = root / mode
            p = cost.run_scope(d, b / "counter", mode, b / "donors", [b / "nested", "root", b / "donors", "100000"])
            assert p.returncode == 0, (mode, p.returncode, p.stderr)
            command, v, events, parents = cost.parsed(d)
            assert command["status"] == 0
            if mode == "cal":
                roots = [next(row[0] for row in events if row[2] == i) for i in range(4)]
                a, g, c, w = roots
                assert [cost.ancestry(pid, v["root"][0], parents) & set(roots) for pid in roots] == [
                    {a}, {g}, {a, c}, {a, c, w}]
                assert len(parents) >= 5
            else:
                assert not events and not parents
            if v["whole"][0]:
                try:
                    cost.measured(d, nested=True)
                except RuntimeError as e:
                    assert "unavailable or multiplexed" in str(e)
                else:
                    raise AssertionError("impossible local hardware read was admitted")
            print(mode, "raw root", v["root"], "whole errno", v["whole"][0], "kernel edges", len(parents))
