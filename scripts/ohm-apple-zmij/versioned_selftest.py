"""Exercise the new QA readers before compiling any product."""
from pathlib import Path
import gzip,hashlib,struct,subprocess,sys,tempfile,unittest
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE/"source-transport/versioned"))
import prepare_versioned as source
from versioned import HARD,V1,V2,marker_rules
from versioned_depfiles import encoded_file
from versioned_select import AWARE,CLASSIC
from objc2_clock import ALLOCATION, ORDERS
from study import PARENT,CHILD
class Protocol(unittest.TestCase):
    def test_exact_commits(self):
        actual=source.SOURCES
        self.assertEqual((actual['rust-parent']['source'],actual['rust-objc']['source'],actual['cargo-apple']['source']),(PARENT,CHILD,AWARE))
        self.assertEqual(actual['cargo-gnu']['base'],CLASSIC)
        for k,s in actual.items():
            raw=(source.FILES/(k+".commit")).read_bytes();patch=gzip.decompress((source.FILES/(k+".patch.gz")).read_bytes())
            self.assertEqual(hashlib.sha256(raw).hexdigest(),s["commit_sha256"])
            self.assertEqual(hashlib.sha256(patch).hexdigest(),s["patch_sha256"])
            self.assertEqual(hashlib.sha1(b"commit "+str(len(raw)).encode()+b"\0"+raw).hexdigest(),s['source'])
            self.assertEqual(raw.splitlines()[:2],[("tree "+s["tree"]).encode(),("parent "+s["base"]).encode()])
        self.assertEqual(ALLOCATION,720)
        self.assertEqual(ORDERS["confirmation"],"CP CP PC PC PC PC CP PC CP PC CP CP".split())
    def test_exact_dummy_rules(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);out=root/"receipts/edge-markers";out.mkdir(parents=True);fields={}
            for label,body in (("raw",f"bin: src/lib.rs {V2}\n\na.d: src/lib.rs\n\nsrc/lib.rs:\n{V2}:\n".encode()),("export",f"bin: src/lib.rs {V1}\n".encode())):
                h=hashlib.sha256(body).hexdigest();(out/(h+".d.gz")).write_bytes(gzip.compress(body));fields[label]={"sha256":h}
            self.assertEqual(marker_rules(root,{"marker":fields}),[("raw",[V2])])
    def test_opaque_suffix_and_wrong_indices(self):
        def make(names,index):
            body=bytearray(b"\0\0\0\0\xff\x04"+struct.pack("<I",len(names)))
            for n in names:
                bs=n.encode();body.extend(b"\x01"+struct.pack("<I",len(bs))+bs+b"\x00")
            body.extend(b"\0\0\0\0")
            if index is not None:
                body.extend(b"LNK1"+struct.pack("<I",index));body.extend(bytes.fromhex(subprocess.check_output(["b3sum"],input=body).decode().split()[0]))
            return bytes(body)
        self.assertFalse(encoded_file(make([V2],None))["has_LNK1"])
        self.assertEqual(encoded_file(make([V1,V2],1))["linked_marker"],V2)
        for data in (make([V2],0)[:-1], make([V2],5),make(["/real/input"],0), make([V2],0)[:-1]+bytes([make([V2],0)[-1]^1])):
            with self.assertRaises(AssertionError):encoded_file(data)
if __name__=='__main__':unittest.main(verbosity=2)
