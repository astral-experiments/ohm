import json
import sys
from pathlib import Path

from study import check_host


if __name__ == "__main__":
    print(json.dumps(check_host(Path(sys.argv[1]), int(sys.argv[2])), sort_keys=True))
