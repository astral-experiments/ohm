"""Invoke the existing full Ruff screen with the reviewed raw-object F/T policy."""

from pathlib import Path
import sys
import traceback

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "branch-first-session-e-screen")]
import policy
import screen

if __name__ == "__main__":
    try:
        screen.main(sys.argv[1], *map(Path, sys.argv[2:]), policy=policy)
    except BaseException:
        if screen.OUT.is_dir():
            (screen.OUT / "failure.txt").write_text(traceback.format_exc())
        raise
