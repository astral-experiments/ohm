#!/usr/bin/env python3
"""Directional library edit pairs; separated from repeated entrypoint measurements."""
import re
import subprocess
import bench

for repo, relative, pattern, variants in [
    ('uv', 'crates/uv/src/lib.rs', r'(pub unsafe fn main<I, T>\(args: I\) -> ExitCode.*?\n\{)', ['off', 'on']),
    ('ruff', 'crates/ruff/src/lib.rs', r'(pub fn run\(.*?\) -> Result<ExitStatus> \{)', ['on', 'off']),
]:
    path=bench.ROOT/repo/relative
    original=subprocess.check_output(['git','show','HEAD:'+relative],cwd=bench.ROOT/repo,text=True)
    edited,count=re.subn(pattern,r'\1\n    std::hint::black_box(1u8);',original,count=1,flags=re.S)
    assert count==1
    try:
        path.write_text(edited)
        for variant in variants:
            bench.build(repo,variant,'library-edit-directional',0)
    finally:
        path.write_text(original)

