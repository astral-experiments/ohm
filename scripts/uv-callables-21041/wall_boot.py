from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from wall_tail.visit import boot
boot()
