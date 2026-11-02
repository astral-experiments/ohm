"""Immutable signed inputs, a private LLVM DSO with one extra DT_NEEDED, and kernel receipts."""

import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ruff-ldv-pilot"))
import probes
import support
import physical
from support import census, guards, need, put, sha

PATCHER = "35fc95654387035338a74bb8cf62fde3712ec83dd8ca30a768deb714d07f063a"
DEB = "962a43e33cd56061522554898557a038ccbb8aa4e1e0f421b2d6f6adf1f80c60"
DEB_URL = "https://archive.ubuntu.com/ubuntu/pool/universe/p/patchelf/patchelf_0.18.0-1.1build1_amd64.deb"
STDIN_FLAGS = ["-e", "trace=%process,read,readv", "-e", "raw=read,readv", "-e", "read=0"]


def patcher(folder, local=None):
    if local is not None:
        tool = Path(local)
    else:
        package = folder / "patchelf.deb"
        with urllib.request.urlopen(DEB_URL, timeout=60) as response:
            data = response.read(106301)
        need(len(data) == 106300 and hashlib.sha256(data).hexdigest() == DEB, "unattested Ubuntu package")
        with package.open("xb") as out:
            out.write(data)
        subprocess.run(["dpkg-deb", "--extract", package, folder / "ubuntu"], check=True)
        tool = folder / "ubuntu/usr/bin/patchelf"
    need(sha(tool) == PATCHER and subprocess.check_output([tool, "--version"]).strip() == b"patchelf 0.18.0",
         "unexpected ELF editor")
    return tool


def file_id(p):
    s = p.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def code_sections(path):
    with path.open("rb") as f:
        head = f.read(64)
        need(head[:6] == b"\x7fELF\x02\x01", "need ELF64 little endian")
        offset, = struct.unpack_from("<Q", head, 40)
        width, count, names_id = struct.unpack_from("<HHH", head, 58)
        need(width == 64 and count > names_id, "invalid section table")
        f.seek(offset)
        rows = [struct.unpack("<IIQQQQIIQQ", f.read(64)) for _ in range(count)]
        f.seek(rows[names_id][4])
        names = f.read(rows[names_id][5])
        code = {}
        for name, kind, flags, address, start, size, _, _, _, _ in rows:
            key = names[name:names.index(b"\0", name)].decode()
            if not (flags & 4 or key in (".rodata", ".eh_frame")):
                continue
            f.seek(start)
            h = hashlib.sha256()
            left = size
            while left:
                data = f.read(min(left, 1048576))
                need(data, "short ELF section")
                h.update(data)
                left -= len(data)
            code[key] = [kind, flags, address, size, h.hexdigest()]
        need(".text" in code and ".rodata" in code, "missing loaded compiler code")
        return code


class Contact:
    def __init__(self, sdk, tools, evidence, local_patcher=None, signed_donor=None):
        self.sdk, self.tools, self.evidence = sdk, tools, evidence
        self.llvm = sdk / support.SDK_LLVM
        self.original, self.derived = tools / "stock-libLLVM", tools / "diagnostic-libLLVM"
        self.signed = signed_donor or tools / "original-signed-sdk"
        self.active = False
        # The 79-member authenticated donor stays on its own inode set. Cargo
        # subsequently observes exactly the same active frontend and driver in every role.
        if signed_donor is None:
            sdk.rename(self.signed)
            shutil.copytree(self.signed, sdk, symlinks=True)
        else:
            need(local_patcher is not None and self.llvm.is_symlink(), "local fixture needs read-only member binds")
            for name in census.common.SDK["members"]:
                need((sdk / name).samefile(self.signed / name), ("wrong immutable local source", name))
        self.verify_signed = self.verify_frozen if signed_donor is not None else census.acquire.verify_sdk
        self.verify_signed(self.signed)
        self.verify_signed(sdk)
        self.front = sdk / "bin/rustc"
        self.driver, = (sdk / "lib").glob("librustc_driver-*.so")
        self.stable = {str(p): file_id(p) for p in (self.front, self.driver, sdk / "bin/cargo")}
        self.original_sha = sha(self.llvm)
        need(self.original_sha == support.LLVM, "wrong stock LLVM")
        (tools / "guard.so").write_bytes(gzip.decompress((support.HERE / "guard.so.gz").read_bytes()))
        need(sha(tools / "guard.so") == support.PLUGIN, "wrong public pass")
        self.helper = tools / "rustc-contact.so"
        subprocess.run(["/usr/bin/cc", "-O2", "-Wall", "-Wextra", "-Werror", "-fPIC", "-shared", HERE / "contact.c",
                        "-ldl", "-o", self.helper], check=True)
        edit = patcher(tools, local_patcher)
        shutil.copyfile(self.llvm, self.derived)
        os.chmod(self.derived, 0o755)
        need(self.derived.stat().st_nlink == 1 and not self.derived.samefile(self.llvm), "aliased private copy")
        subprocess.run([edit, "--add-needed", self.helper, self.derived], check=True)
        needed = lambda p: subprocess.check_output([edit, "--print-needed", p], text=True).splitlines()
        before, after = needed(self.llvm), needed(self.derived)
        need(after == [str(self.helper), *before], "more than one loader dependency changed")
        code = code_sections(self.llvm)
        need(code_sections(self.derived) == code, "executable LLVM sections, addresses or unwind data differed")
        self.diagnostic_sha = sha(self.derived)
        self.llvm.parent.chmod(self.llvm.parent.stat().st_mode | 0o200)
        self.identity = {"signed_members": len(census.common.SDK["members"]), "sdk": census.common.SDK["asset"],
                         "rustc": sha(self.front), "driver": sha(self.driver), "cargo": sha(sdk / "bin/cargo"),
                         "stable_file_identities": self.stable, "capture_dso": sha(self.helper),
                         "pass_dso": support.PLUGIN, "wild": sha(sdk / support.WILD),
                         "patchelf": PATCHER, "patchelf_deb": DEB,
                         "original_llvm": self.original_sha, "original_bytes": self.llvm.stat().st_size,
                         "diagnostic_llvm": self.diagnostic_sha, "diagnostic_bytes": self.derived.stat().st_size,
                         "needed_before": before, "needed_after": after, "unchanged_code": code}
        put(evidence / "physical-contact.json", self.identity)

    @staticmethod
    def verify_frozen(root):
        # Local forensic SDK has had write permission removed without changing its bytes.
        ref = census.common.SDK["members"]
        for name, (_, mode, size, code) in ref.items():
            p = root / name
            need(p.stat().st_mode & 0o777 in (mode, mode & ~0o222) and p.stat().st_size == size and sha(p) == code, name)
        need({str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()} == set(ref), "extra SDK files")

    def select(self, arm):
        need(arm in ("plain", "original", "guard"), "unknown diagnostic mode")
        active = arm != "plain"
        if active and not self.active:
            self.llvm.rename(self.original)
            self.derived.rename(self.llvm)
        if not active and self.active:
            self.llvm.rename(self.derived)
            self.original.rename(self.llvm)
        self.active = active
        need(all(file_id(Path(k)) == v for k, v in self.stable.items()), "Cargo's physical compiler key changed")
        need(sha(self.llvm) == (self.diagnostic_sha if self.active else self.original_sha), "wrong selected LLVM")

    def env(self, base, arm, where):
        need(not any("TRUST" in k or k.startswith("QA_LDV") or k in
                     ("RUSTC", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC_WRAPPER", "LD_PRELOAD", "LD_AUDIT")
                     for k in base), "unregistered Cargo inputs")
        if arm == "plain":
            return base.copy()
        return {**base, "QA_LDV_FRONTEND": str(self.front), "QA_LDV_LLVM": str(self.llvm),
                "QA_LDV_PLUGIN": str(self.tools / "guard.so"), "QA_LDV_RECORD": str(where), "OHM_LDV_GUARD": arm}

    def finish(self):
        self.select("plain")
        self.verify_signed(self.signed)
        self.verify_signed(self.sdk)
        need(sha(self.derived) == self.diagnostic_sha and sha(self.helper) == self.identity["capture_dso"]
             and sha(self.tools / "guard.so") == support.PLUGIN, "diagnostic tools changed")


def counted_argv(counter, result, executable, ordinary):
    # count.c calls execv(argv[2], argv + 3). The path to execute and the
    # original argv[0] are separate fields, as required by rustup dispatch.
    need(ordinary and ordinary[0] == "cargo" and executable, "expected the ordinary Cargo proxy")
    return [str(counter), str(result), str(executable), *ordinary]


def visit(contact, dest, work, repo, arm, env, cmd, expected=0, score=False, cold=False, fixture=False):
    dest.mkdir()
    for subdir in ("native", "trace"):
        (dest / subdir).mkdir()
    eff = contact.env(env, arm, dest / "native")
    runner = list(map(str, cmd))
    if score:
        proxy = shutil.which("cargo", path=env["PATH"])
        runner = counted_argv(contact.tools / "count", dest / "pmu.json", proxy, runner)
    flags = STDIN_FLAGS if cold else ["-e", "trace=%process"]
    argv = ["/usr/bin/strace", "-ff", "-qq", "-s", "131072", "-v", *flags, "-o", str(dest / "trace/exec"), "--", *runner]
    put(dest / "command.json", {"ordinary": cmd, "actual": argv, "environment": eff})
    code = guards.run(argv, repo, eff, dest, work, dest, timeout=3000)
    need(code == expected, (str(dest), code, (dest / "outer.stderr").read_bytes()[-3000:]))
    measured = None
    if score:
        pm = json.loads((dest / "pmu.json").read_bytes())
        need(os.waitstatus_to_exitcode(pm["status"]) == code and pm["enabled"] == pm["running"] > 0
             and pm["instructions"] > 0, "unqualified hardware counter")
        measured = pm["instructions"]
    rusts, raw_roster = support.observed(dest, contact.sdk, arm, False)
    tree = json.loads((dest / "kernel.json").read_bytes())["tree"]
    front, llvm = contact.front.stat(), contact.llvm.stat()
    expected_pids = {r["pid"] for r in rusts if r["selected"]} if arm != "plain" else set()
    loaded_pids = {int(p.stem) for p in (dest / "native").glob("*.loaded")}
    need(loaded_pids == expected_pids, ("physical rustc contact", expected_pids, loaded_pids))
    for pid in loaded_pids:
        line = (dest / "native" / f"{pid}.loaded").read_text()
        need(line == f"{arm} {front.st_dev} {front.st_ino} {llvm.st_dev} {llvm.st_ino}\n", "different physical compiler")
    expected_links = [(r["pid"], r["path"]) for r in tree["linkers"]]
    linker_argv = []
    for trace in (dest / "trace").glob("exec.[0-9]*"):
        with trace.open() as lines:
            for line in lines:
                if not line.startswith(("execve(", "execveat(")) or not line.rstrip().endswith("= 0"):
                    continue
                m = support.EXEC.fullmatch(line.rstrip())
                need(m, "unsupported successful exec")
                child = {s.split("=", 1)[0] for s in ast.literal_eval(m[3])}
                need(not {"LD_PRELOAD", "LD_AUDIT", "RUSTC_WRAPPER", "CARGO_BUILD_RUSTC_WRAPPER"} & child,
                     ("loader or Cargo wrapper on ordinary child", m[1]))
                exe, pid = ast.literal_eval(m[1]), int(trace.suffix[1:])
                if (pid, exe) in expected_links:
                    linker_argv.append({"pid": pid, "path": exe, "argv": ast.literal_eval(m[2]), "sha256": sha(Path(exe)),
                                        "signed_wild": support.real_program(exe, contact.sdk / support.WILD)})
    need(sorted((r["pid"], r["path"]) for r in linker_argv) == sorted(expected_links), "missing actual linker")
    put(dest / "linker-argv.json", linker_argv)
    roster, originals = probes.capture(dest, rusts, tree, raw_roster, cold, expected_shape=not fixture)
    for row in originals:
        owner = row["equivalence"]
        store = contact.evidence / "probe-owners"
        store.mkdir(exist_ok=True)
        saved = physical.keep(Path(owner["owner"]).resolve(strict=True), store, b"\x7fELF")
        need(saved["sha256"] == owner["owner_sha256"], "actual probe owner changed during custody")
    put(dest / "probes.json", originals)
    return measured, rusts, raw_roster, roster, originals
