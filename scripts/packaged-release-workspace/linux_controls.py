"""Calibrate the new reader on the literal 50 historical Wild execs, plus source-bound negative controls."""
import copy
import gzip
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from linux_common import *

class Controls(unittest.TestCase):
    def setUp(self):
        self.q=json.loads(gzip.decompress((FIX/"original-exec-census.json.gz").read_bytes()))
        self.assertEqual(self.q["original"],ENROLL["source_archive_sha256"])
        self.tools={};self.alias={};self.rows=[]
        for pid,line,kind,physical in self.q["rows"]:
            path,argv=event(line.encode())
            # The old archive certifies actual physical paths. No inode claim is made for the
            # historical fixture. Current release tests instead stat and hash each real tool.
            record={"physical":physical,"sha256":digest(physical.encode()),"dev_ino":[0,0]}
            self.alias[path]=record
            typ={"full":"rustc","link-only":"rustc","cargo":"cargo","wild":"wild"}.get(kind)
            if typ:self.tools[typ]=record
            self.rows.append([pid,line])
    def test_all_archived_50(self):
        q=native(self.rows,self.tools,self.alias)
        self.assertEqual({p["output"]:p["pid"] for p in q["wild"]},self.q["original_per_output"])
        self.assertEqual(q["counts"]["wild"],50);self.assertEqual(q["counts"]["full"],1);self.assertEqual(q["counts"]["link-only"],50)
        self.assertEqual([r["crate"] for r in q["compilers"] if r["mode"]=="full"],["ron"])
    def test_missing_and_forged(self):
        q=native(self.rows,self.tools,self.alias)
        pid=q["wild"][0]["pid"]
        dropped=[r for r in self.rows if r[0]!=pid]
        self.assertEqual(native(dropped,self.tools,self.alias)["counts"]["wild"],49)
        bad=copy.deepcopy(self.tools);bad["wild"]["sha256"]="f"*64
        with self.assertRaises(RuntimeError):native(self.rows,bad,self.alias)
        bad=copy.deepcopy(self.rows);ix=next(i for i,v in enumerate(bad) if v[0]==pid);bad[ix][1]=bad[ix][1].replace('"-o",','"-o", "one", "-o",',1)
        with self.assertRaises(RuntimeError):native(bad,self.tools,self.alias)
    def test_complete_native_elf_and_source(self):
        raw=Path("/bin/true").read_bytes();q=elf_bytes(raw)
        self.assertEqual(q["sha256"],digest(raw));self.assertGreater(len(q["load_segments"]),1)
        for b in (raw[:70],b"not-elf"):
            with self.assertRaises(RuntimeError):elf_bytes(b)
        self.assertEqual((len(SUBJECTS),sum(x["cold_unchanged_same"] for x in SUBJECTS.values()),len(ENROLL["old_full_roster"])),(50,49,102))
        self.assertEqual(digest((FIX/"historical.patch").read_bytes()),ORACLE["patch_sha256"])
if __name__=="__main__":unittest.main()
