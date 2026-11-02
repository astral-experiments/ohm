import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import files,verify


class Inputs(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name).resolve()
        self.work=self.root/"work"
        self.file=self.work/"build/debug/.fingerprint/foo/output-lib-foo"
        self.file.parent.mkdir(parents=True)
        self.old=b'OHM_LDV_GUARD original\n{"preserved":"input"}\n'
        self.new=b'OHM_LDV_GUARD guard\nOHM_LDV_REASONS 1 0 0 0 0 0 0 0\n{"preserved":"input"}\n'
        self.trace=self.root/"trace"
        self.trace.write_text(f'17 openat(AT_FDCWD,"{self.file}",O_RDONLY|O_CLOEXEC) = 4<{self.file}>\n')
        self.file.write_bytes(self.old)
        self.o=files.capture(self.trace,self.work,self.root/"dbo",self.old,"original")
        self.file.write_bytes(self.new)
        self.g=files.capture(self.trace,self.work,self.root/"dbg",self.new,"guard")
        self.key=str(self.file.relative_to(self.work))

    def test_actual_roundtrip(self):
        before=self.file.stat()
        files.switch(self.work,self.o,self.root/"dbo",self.g,self.g)
        self.assertEqual(self.file.read_bytes(),self.old)
        files.switch(self.work,self.g,self.root/"dbg",self.g,self.o)
        self.assertEqual(self.file.read_bytes(),self.new)
        s=self.file.stat()
        self.assertEqual((s.st_dev,s.st_ino,s.st_mtime_ns),(before.st_dev,before.st_ino,before.st_mtime_ns))
        self.assertEqual(self.o[self.key]["nonprobe"],self.g[self.key]["nonprobe"])

    def test_reject_preexisting_modified(self):
        st=self.file.stat()
        self.file.write_bytes(self.new[:-3]+b"x}\n")
        os.utime(self.file,ns=(st.st_atime_ns,st.st_mtime_ns))
        with self.assertRaises(ValueError): files.switch(self.work,self.o,self.root/"dbo",self.g,self.g)

    def test_sha_on_custody(self):
        h=self.o[self.key]["sha"]
        (self.root/"dbo"/h).write_bytes(b"?"*len(self.old))
        with self.assertRaises(ValueError): files.switch(self.work,self.o,self.root/"dbo",self.g,self.g)

    def test_allow_no_external_links(self):
        os.link(self.file,self.root/"bystander")
        with self.assertRaises(ValueError): files.switch(self.work,self.o,self.root/"dbo",self.g,self.g)
        self.assertEqual((self.root/"bystander").read_bytes(),self.new)

    def test_reject_symlink(self):
        saved=self.root/"real"
        self.file.rename(saved)
        self.file.symlink_to(saved)
        with self.assertRaises(ValueError): files.switch(self.work,self.o,self.root/"dbo",self.g,self.g)

    def test_reject_unobserved(self):
        self.trace.write_text(f'17 openat(AT_FDCWD,"{self.file}",O_RDONLY) = -1 ENOENT\n')
        with self.assertRaises(ValueError):
            files.capture(self.trace,self.work,self.root/"bad",self.new,"guard")

    def test_reject_different_stdout_reason(self):
        with self.assertRaises(ValueError):
            files.capture(self.trace,self.work,self.root/"bad",self.new+b'OHM_LDV_REASONS 7\n',"guard")

    def test_actual_registration(self):
        a=verify.read(HERE/"registration.json")
        self.assertEqual(a["cells"]["1"],a["cells"]["2"][::-1])
        self.assertEqual(set(map(tuple,a["cells"]["1"])),{(c,m) for c in ("original","guard") for m in ("original","guard")})
        boot=lambda i: {"boot":str(i),"slot":i,"qa":"abc","run":"7","counts":[[c,m,480_000_000+5_680_000*(c=="guard")] for c,m in a["cells"][str(i)]]}
        p,q=boot(1),boot(2)
        self.assertTrue(verify.analyze(p,q)["registered_sufficiency"])
        q["counts"][0][2]+=1_000_000
        self.assertFalse(verify.analyze(p,q)["registered_sufficiency"])
        q["boot"]=p["boot"]
        with self.assertRaises(ValueError): verify.analyze(p,q)


if __name__=="__main__":
    unittest.main()
