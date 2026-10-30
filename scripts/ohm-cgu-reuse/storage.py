"""Count physical filesystem allocation across the private compiler roots, once per inode."""
import os
import stat


def allocation(work):
    allocated = {}
    for name in ('target', 'shared'):
        root = work / name
        for parent, dirs, files in os.walk(root):
            for child in dirs + files:
                entry = os.lstat(os.path.join(parent, child))
                if stat.S_ISREG(entry.st_mode):
                    allocated[entry.st_dev, entry.st_ino] = entry.st_blocks * 512
    return {'regular_file_inodes': len(allocated), 'allocated_bytes': sum(allocated.values())}
