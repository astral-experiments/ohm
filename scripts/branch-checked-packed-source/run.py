"""Bootstrap only the fixed compiler and qualify it against the genuine E and F writers."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workers
import corrected
import qualify_e

if __name__ == "__main__":
    qualify_e.main(Path(sys.argv[1]).resolve(), authority=corrected, extra_native=workers.run)
