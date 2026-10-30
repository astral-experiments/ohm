"""Bind a whole signed Apple executable to rustc's retained recipe and native object files."""

import json
from pathlib import Path
import struct

from macho_paths import canonical, root_cgu
from study import compress_bytes, digest, need, save


class Decoder:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        end = self.pos + size
        need(0 <= size and end <= len(self.data), "truncated rlink record")
        value = self.data[self.pos:end]
        self.pos = end
        return value

    def number(self, limit):
        value = 0
        for shift in range(0, 63, 7):
            b = self.take(1)[0]
            value |= (b & 127) << shift
            if b < 128:
                need(value <= limit and (not shift or b != 0), "invalid rlink integer")
                return value
        raise ValueError("oversized rlink integer")

    def string(self):
        value = self.take(self.number(1 << 18))
        need(self.take(1) == b"\xc1" and b"\x00" not in value, "invalid rlink string")
        return value.decode("utf-8")

    def option(self, get):
        flag = self.number(1)
        return get() if flag else None

    def module(self, expected_kind):
        name = self.string()
        need(self.number(1) == expected_kind, "wrong rustc module kind")
        paths = [self.option(self.string) for _ in range(6)]
        # object, global_asm_object, dwarf_object, bytecode, assembly, llvm_ir
        links = [self.string() for _ in range(self.number(2048))]
        need(name and paths[0] and not any(paths[1:]), "unexpected compiled module outputs")
        return {"name": name, "kind": expected_kind, "object": paths[0], "links": links}


def modules(body):
    d = Decoder(body)
    need(d.take(12) == b"rustlink\0\0\0\1", "unsupported rustc link recipe")
    version = d.string()
    need(version.startswith("1.99.0"), "wrong rustc version in recipe")
    result = [d.module(0) for _ in range(d.number(2048))]
    allocator = d.option(lambda: d.module(1))
    if allocator:
        result.append(allocator)
    need(result and d.pos < len(body) and len({r["name"] for r in result}) == len(result)
         and len({r["object"] for r in result}) == len(result), "ambiguous rlink modules")
    return version, result


def read_regular(path):
    need(path.is_file() and not path.is_symlink(), "missing regular native input: " + str(path))
    return path.read_bytes()


def stash(root, kind, data):
    key = digest(data)
    target = root / "receipts" / "cgu-inputs" / kind / (key + ".gz")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        compress_bytes(target, data)
    return key


def inputs(executable):
    exe = Path(executable)
    recipe = exe.with_suffix(".rlink")
    body = read_regular(recipe)
    version, rows = modules(body)
    owner = exe.with_suffix(".rlink-objects")
    need(owner.is_dir() and not owner.is_symlink(), "missing object directory")
    for r in rows:
        obj = Path(r["object"])
        need(obj.is_absolute() and obj.parent == owner and obj.suffix == ".o"
             and obj.is_file() and not obj.is_symlink(), "foreign or absent object in rustc recipe")
    return body, version, rows


def freeze(executable, directory, clone):
    """Clone sole recipe and module objects between unobserved commands, after the timer."""
    body, _, rows = inputs(executable)
    directory.mkdir(parents=True)
    source = Path(executable).with_suffix(".rlink")
    clone(source, directory / "saved.rlink")
    need((directory / "saved.rlink").read_bytes() == body, "recipe changed during its hold")
    for r in rows:
        obj = Path(r["object"])
        clone(obj, directory / obj.name)


def witness(root, out, image, executable, *, linker=None, held=None):
    """Corroborate the observed ld inputs or separately identify untraced saved-rustc inputs."""
    if held is None:
        receipt, version, rows = inputs(executable)
    else:
        receipt = read_regular(held / "saved.rlink")
        version, rows = modules(receipt)
    exe = Path(executable)
    owned = exe.with_suffix(".rlink-objects")
    paths = [r["object"] for r in rows]
    entry = {"source": "kernel-xcode-ld+rustc-recipe" if linker else "saved-rustc-recipe",
             "output": executable, "version": version, "recipe": stash(root, "recipes", receipt)}
    if linker is not None:
        actual = [p for p in linker if Path(p).parent == owned and p.endswith(".o")]
        need(len(set(actual)) == len(actual) and set(actual) == set(paths),
             "actual ld root object set differs from rustc CompiledModules")
        entry["linker_argv"] = digest(json.dumps(linker, separators=(",", ":")).encode())
    by_name = {}
    physical = {}
    for row in rows:
        path = Path(row["object"])
        need(path.is_absolute() and path.parent == owned, "recipe escaped root output")
        obj = read_regular(held / path.name if held is not None else path)
        need(obj[:8] == bytes.fromhex("cffaedfe0c000001")
             and struct.unpack_from("<I", obj, 12)[0] == 1, "input was not an ARM64 Mach-O object")
        key = stash(root, "objects", obj)
        need(row["name"] not in by_name, "duplicate stable CGU")
        by_name[row["name"]] = key
        physical[str(path)] = {"module": row["name"], "kind": row["kind"], "bytes": len(obj),
                               "sha256": key}
    operands = linker if linker is not None else [*paths, "-o", executable]
    blob, check = canonical(image, executable, operands, incremental=True, namespace=False)
    for row in check["nonce_objects"]:
        need(row["path"] in physical and root_cgu(row["path"], executable),
             "an altered N_OSO is missing its independently held physical input")
    entry.update(raw=digest(image), same_path_image=digest(blob), modules=by_name,
                 physical=physical, nonce_objects=check["nonce_objects"], code_pages=check["code_pages"])
    if linker is not None:
        blob, full = canonical(image, executable, linker, incremental=True)
        entry["cross_path_image"] = digest(blob)
        entry["debug_paths"] = full["paths"]
    save(out / "cgu-proof.json", entry)
    return entry


def agrees(a, b):
    return (a["output"] == b["output"] and a["same_path_image"] == b["same_path_image"]
            and a["modules"] == b["modules"])


def same_product(a, b, pa, pb):
    return (a.keys() == b.keys() and all(a[k] == b[k] for k in a if k != "raw")
            and pa["raw"] == a["raw"] and pb["raw"] == b["raw"] and agrees(pa, pb))
