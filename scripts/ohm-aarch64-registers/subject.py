"""Bind both source-built SDK roles for the GNU target experiment."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ohm-aarch64-linux"))
import capsule
import runtime as rt
from study import need, save, sha

BASE = "444c0273a2e2bc0b161e988d43c882349bc2d7a6"
TREATMENT = "d3538b42a2dc56edb9bffbc9cc2373fb93c35054"
rt.PARENT, rt.CHILD = BASE, TREATMENT


def main():
    action, *args = sys.argv[1:]
    if action == "freeze":
        role, part = args
        need(role in ("P", "C") and part in ("host", "target"), "invalid slice")
        rt.freeze(role, part)
    elif action == "select":
        role, = args
        need(role in ("P", "C"), "invalid role")
        changed = rt.select(role)
        save(rt.LOG / ("physical-roles-" + role + ".json"), {"different": changed, "source": {"P": BASE, "C": TREATMENT}[role],
             "tools": rt.TOOLS, "files": sha(rt.LOG / (role + "-sdk.json"))})
    elif action == "capsule":
        capsule.build()
    elif action == "restore":
        src, key, role, dest = args
        p = Path(src)
        need(sha(p) == key, "incorrect enrolled SDK archive")
        print(capsule.verify(p, role, Path(dest)))
    else:
        raise ValueError(action)


if __name__ == "__main__":
    main()
