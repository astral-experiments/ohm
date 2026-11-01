"""Enroll all Cargo result paths and root-relative per-unit output roles, including fresh entries."""

from pathlib import Path
import os, stat
from protocol import need


def artifacts(messages, work, tree):
    def owned(name, *, directory=False):
        p = Path(name)
        need(
            p.is_absolute()
            and p.resolve() == p
            and (p.is_dir() if directory else p.is_file())
            and any(p.is_relative_to(work / part) for part in ("target", "build")),
            "foreign/missing Cargo output " + name,
        )
        return str(p.relative_to(work))

    return described(messages, tree, owned)


def described(messages, tree, owned):
    units = []
    generated = []
    for m in messages:
        if m["reason"] == "compiler-artifact":
            need(isinstance(m["filenames"], list) and m["filenames"], "unit without physical return path")
            units.append(
                [
                    m["package_id"].replace(tree.as_uri(), "file:///__locked__"),
                    m["target"]["name"],
                    m["target"]["kind"],
                    m["features"],
                    m["profile"],
                    sorted(owned(f) for f in m["filenames"]),
                    owned(m["executable"]) if m["executable"] else None,
                ]
            )
        elif m["reason"] == "build-script-executed":
            generated.append(
                [
                    m["package_id"].replace(tree.as_uri(), "file:///__locked__"),
                    owned(m["out_dir"], directory=True),
                ]
            )
    import json

    sort = lambda items: sorted(items, key=lambda r: json.dumps(r, sort_keys=True))
    return {"units": sort(units), "out_dirs": sort(generated)}
