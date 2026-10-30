"""Read genuine ARM64 Mach-O objects from BSD/GNU ar without invoking a second toolchain."""

from study import digest, need


def archive_evidence(path):
    data = path.read_bytes()
    need(data.startswith(b"!<arch>\n"), "wrong archive format")
    offset = 8
    table = b""
    members = {}
    metadata = {}
    while offset < len(data):
        header = data[offset : offset + 60]
        need(len(header) == 60 and header[58:60] == b"\x60\n", "invalid member header")
        size = int(header[48:58])
        first = offset + 60
        last = first + size
        need(last <= len(data), "truncated native archive")
        name = header[:16].strip()
        body = data[first:last]
        if name.startswith(b"#1/"):
            count = int(name[3:])
            need(count <= len(body), "invalid BSD name")
            name, body = body[:count].rstrip(b"\0"), body[count:]
        elif name == b"//":
            table = body
        elif name.startswith(b"/") and name[1:].isdigit():
            n = int(name[1:])
            end = table.index(b"/\n", n)
            name = table[n:end]
        else:
            name = name.removesuffix(b"/")
        if name in (b"lib.rmeta", b"lib.rmeta-link"):
            key = name.decode()
            need(key not in metadata, "duplicate native archive metadata")
            metadata[key] = {"size": len(body), "sha256": digest(body)}
        if name.endswith(b".o"):
            key = name.decode()
            need(
                key not in members
                and body[:8] == bytes.fromhex("cffaedfe0c000001")
                and body[12:16] == b"\1\0\0\0",
                "missing native ARM64 Mach-O member",
            )
            members[key] = {"size": len(body), "sha256": digest(body)}
        offset = last + (size % 2)
    need(offset == len(data) and members, "archive has no native Mach-O or odd padding")
    need("lib.rmeta" in metadata, "Ruff archive has no lib.rmeta")
    return {"archive_sha256": digest(data), "archive_objects": members, "archive_metadata": metadata}


def bag(reader):
    return sorted((v["size"], v["sha256"]) for v in reader["archive_objects"].values())
