"""Adversarial replays on two previously archived real Apple linker invocations."""
import argparse
import hashlib
from pathlib import Path
import struct
from zipfile import ZipFile

from macho_paths import canonical, compare
from reopen_cgu import original_provider
from study import need


def rejected(callback):
    try:
        callback()
    except (RuntimeError, ValueError):
        return
    raise AssertionError("invalid Mach-O or input was accepted")


def resign(data):
    data = bytearray(data)
    pos = 32
    signature = None
    for _ in range(struct.unpack_from("<I", data, 16)[0]):
        cmd, size = struct.unpack_from("<2I", data, pos)
        if cmd == 0x1d:
            signature = struct.unpack_from("<I", data, pos + 8)[0]
        pos += size
    base = signature + 20
    offset = struct.unpack_from(">I", data, base + 16)[0]
    count = struct.unpack_from(">I", data, base + 28)[0]
    for i in range(count):
        at = base + offset + 32 * i
        data[at:at+32] = hashlib.sha256(data[i*4096:min(signature,(i+1)*4096)]).digest()
    return bytes(data)


def check(archive):
    with ZipFile(archive) as z:
        top = "provider-matrix/P-direct-declared-default/lower/"
        a, b = [v for _,v in original_provider(z, [top+"warm", top+"empty"])]
    result = compare(dict(P=a, C=b), incremental=True, same_namespace=True)
    assert result["raw_difference_bytes"] and result["P"]["nonce_objects"]
    norm, w = canonical(*a, incremental=True, namespace=False)
    assert norm == canonical(*b, incremental=True, namespace=False)[0]
    x, y, argv = a
    # A real code mutation violates the original signature. A correctly re-signed
    # mutation is structurally valid but must still disagree with the pristine image.
    code = bytearray(x)
    code[0x5000] ^= 1
    rejected(lambda: canonical(bytes(code), y, argv, incremental=True))
    signed = resign(code)
    canonical(signed, y, argv, incremental=True)
    rejected(lambda: compare(dict(P=(signed,y,argv), C=b), incremental=True))
    operand = w["nonce_objects"][0]["path"]
    rejected(lambda: canonical(x, y, [p for p in argv if p!=operand], incremental=True))
    rejected(lambda: canonical(x, y, [p for p in argv if p!=operand], incremental=True, namespace=False))
    rejected(lambda: canonical(x, y.replace("v2-", "v3-"), argv, incremental=True))
    nonce = w["nonce_objects"][0]["nonce"]
    filename = operand.encode()
    assert x.count(filename) == 1
    too_large = operand.replace("."+nonce+".rcgu.o", ".zzzzzzz.rcgu.o")
    wrong = resign(x.replace(filename,too_large.encode()))
    rejected(lambda: canonical(wrong,y,[too_large if p==operand else p for p in argv],incremental=True))
    cgu = w["nonce_objects"][0]["cgu"]
    renamed = operand.replace(cgu,("x" if cgu[0]!="x" else "y")+cgu[1:])
    diff = resign(x.replace(filename,renamed.encode()))
    rejected(lambda: compare(dict(P=(diff,y,[renamed if p==operand else p for p in argv]), C=b),incremental=True))
    print("Two physical whole images, signatures, same-role projection and seven corruptions passed.")


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("archive",type=Path);check(p.parse_args().archive)
