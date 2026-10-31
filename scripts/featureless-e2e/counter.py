"""Reuse the established inherited Linux tree counter with four additional physical selectors."""

import hashlib
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ORIGINAL = "907ec744d5806bac111cc3480520cf152424915bf9017616bd5aff50ec21f28c"
NAMES = ("build_rustc", "generator", "unicode_rustc", "ron")
# TSV wire names are retained for the existing four-sibling calibration.
MEANINGS = ("e2e rustc family", "executed generator family", "e2e GCC family", "e2e Wild family")


def build(work, original):
    source = (original / "tree-counter.c").read_bytes()
    assert hashlib.sha256(source).hexdigest() == ORIGINAL
    text = source.decode()

    def replace(before, after):
        nonlocal text
        assert text.count(before) == 1, before
        text = text.replace(before, after)

    replace("int main(int argc,char **argv){",
            (HERE / "scopes.inc").read_text() + "\nint main(int argc,char **argv){")
    replace('need(roster||cal||sham,"mode");',
            'int e2e=!strcmp(argv[2],"e2e"); need(roster||cal||sham||e2e,"mode"); '
            'if(e2e)enroll_scopes(argv[3]);')
    replace('else if(same(&actual,&rust)){',
            'else if(e2e)role=e2e_role(exe,&actual,buf,size);\n                else if(same(&actual,&rust)){')
    directory = work / "attribution"
    directory.mkdir()
    generated = directory / "counter.c"
    generated.write_text(text)
    for src, exe in [(generated, "counter"), (HERE / "nested.c", "nested")]:
        subprocess.run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread", src, "-o", directory / exe], check=True)
    donors = directory / "donors"
    donors.mkdir()
    for role in NAMES:
        shutil.copy2(directory / "nested", donors / role)
    assert len({p.stat().st_ino for p in donors.iterdir()}) == 4
    return directory
