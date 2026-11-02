"""Freeze prior donor files while the selected compiler is still at its ELF exec stop."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import green_inputs
if __name__=='__main__':
    owner,work,store=map(Path,sys.argv[1:])
    if not all(p.is_absolute() and p.is_dir() for p in (owner,work,store)):
        raise ValueError("expected existing private stage, work root, and graph store")
    green_inputs.capture(owner,owner/'original.nul',work,store,'exec')
