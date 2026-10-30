"""Verify the strict response parser and bind real long-argv Xcode links before observing Ruff."""
import base64
from copy import deepcopy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execs import ExecTrace
from study import compress_bytes, digest, need, save
from xcode_response import ResponseRows, darwin_user_temp, resolved, words


def synthetic(root):
    response = root/"response-a970af.txt"
    response.write_bytes(b'"-o" "/tmp/exe"\n"/tmp/with space.o" "-lSystem"\n')
    parent = {"pid": 3, "pgid": 2, "ppid": 1, "seq": 8, "path": "/tool/clang", "cdhash": "aa",
              "argv": ["/tool/clang", "/tmp/with space.o", "-o", "/tmp/exe", "-lSystem"]}
    child = {"pid": 4, "pgid": 2, "ppid": 3, "seq": 9, "path": "/tool/ld", "cdhash": "bb",
             "argv": ["/tool/ld", "@"+str(response)]}
    rows = ResponseRows(root)
    rows.append(parent)
    rows.append(child)
    return rows


class Cases(unittest.TestCase):
    def test_argv(self):
        self.assertEqual(words(b'"/with space/x.o"\n"-o"\t/simple -lSystem\n'),
                         ["/with space/x.o", "-o", "/simple", "-lSystem"])
        for data in (b'', b'""', b'a\\ b', b'a\x00b', b'"a"b', b'@nested', b"'x'", b'"bad', b'a\xff'):
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                words(data)

    def test_witness(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = synthetic(Path(tmp))
            self.assertEqual(list(resolved(rows))[-1]["argv"], ["/tool/ld", "-o", "/tmp/exe", "/tmp/with space.o", "-lSystem"])
            for which in ("parent", "parent-input", "parent-output", "parent-order", "raw", "bytes", "stamp", "temp", "drop", "foreign"):
                copied = deepcopy(list(rows))
                proof = copied[-1]["xcode_response"]
                if which == "parent": copied[-1]["ppid"] = 41
                if which == "parent-input": copied[0]["argv"][1] = "/bad.o"
                if which == "parent-output": copied[0]["argv"][3] = "/bad"
                if which == "parent-order": copied[0]["seq"] = 11
                if which == "raw": copied[-1]["argv"][1] += "2"
                if which == "bytes": proof["bytes"] = base64.b64encode(b"wrong").decode()
                if which == "stamp": proof["identity"][5] += 1
                if which == "temp": proof["temporary"] = "/another"
                if which == "drop": del copied[-1]["xcode_response"]
                if which == "foreign": copied[-1]["path"] = "/other/ld"
                with self.subTest(which=which), self.assertRaises(RuntimeError):
                    list(resolved(copied))

    def test_no_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/"original"
            source.write_bytes(b"-o /tmp/one")
            alias = root/"response-af34.txt"
            alias.symlink_to(source)
            with self.assertRaises(RuntimeError):
                ResponseRows(root).append({"path": "/tool/ld", "argv": ["ld", "@"+str(alias)]})


def native(root):
    root = root.resolve()
    work = root/"link-response-control"
    work.mkdir()
    log = root/"receipts/link-response-control"
    log.mkdir()
    src, obj, exe = (work/name for name in ("main.c", "main.o", "probe"))
    src.write_text('extern int puts(const char*);\nvolatile const unsigned char a[64*1024*1024]={29};\nint main(void){ return a[0] == 29 ? (puts("29"), 0) : 1; }\n')
    cc = subprocess.check_output(["xcrun", "--find", "clang"], text=True).strip()
    sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
    subprocess.run([cc, "-isysroot", sdk, "-c", src, "-o", obj], check=True)
    trace = ExecTrace()
    try:
        trace.ready()
        base = [cc, "-isysroot", sdk, str(obj), "-o", str(exe)]
        # Actual LLVM driver, plain and over its response-file threshold. Each distinct empty
        # library directory leaves libSystem selection and the final executable unchanged.
        search = work/"search"
        search.mkdir()
        options = []
        for i in range(825):
            d = search/(f"{i:04}-" + "a" * 96)
            d.mkdir()
            options.append("-L"+str(d))
        images = {}
        for role, arguments in (("direct", base), ("response", [*base, *options])):
            rows = ResponseRows(tempfile.gettempdir(), darwin_user_temp())
            save(log/(role+"-roots.json"), sorted(map(str, rows.temporary)))
            try:
                with (log/(role+".out")).open("wb") as out, (log/(role+".err")).open("wb") as err:
                    status, events = trace.command(arguments, cwd=work, env=os.environ.copy(), out=out, err=err,
                                                   observed_rows=rows)
            finally:
                compress_bytes(log/(role+"-exec.json.gz"), json.dumps(rows).encode())
            need(status == 0, f"native {role} calibration failed")
            expanded = list(resolved(events))
            original, = [e for e in events if Path(e["path"]).name in ("ld", "ld64", "ld-prime", "ld-classic")]
            used, = [e for e in expanded if e["pid"] == original["pid"] and e["seq"] == original["seq"]]
            need(("xcode_response" in original) == (role == "response") and str(obj) in used["argv"] and
                 str(exe) in used["argv"], "native response control did not use both invocation forms")
            program = exe.read_bytes()
            actual = subprocess.check_output([str(exe)])
            need(actual == b"29\n", "wrong physical calibration executable")
            images[role] = {"image": digest(program), "bytes": len(program), "output": actual.decode(),
                            "argv": digest(json.dumps(used["argv"], separators=(",", ":")).encode())}
            exe.unlink()
        need(images["direct"]["image"] == images["response"]["image"], "parent and response produced different calibration binaries")
        save(log/"terminal.json", images)
    finally:
        trace.close()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "native":
        native(Path(sys.argv[2]))
    else:
        unittest.main()
