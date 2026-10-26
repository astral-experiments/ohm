#!/usr/bin/env python3
"""Generate the frozen nine-change experiment inputs after rebuilding the release components."""
import argparse
import hashlib
import json
from pathlib import Path

CARGO = {
    'parent': '211465de4b9e4589da2be06871acd9304dd3b94c849c1304f723484cb4f71dfc',
    'stack': '71da9dfcb3ba440297f84705ff7e3a676634ced7d7b6ca9b525a439b7f748f58',
}
WILD = {
    'parent': '0d6335808b647d499f3d74993b602e64ff0625206c809bf4913c487eea380cd5',
    'stack': '076b2067722a82b6445183fcabc26a17819537e1656067ec85947b5800ba2a23',
}
RUSTLIB='lib/rustlib/x86_64-unknown-linux-gnu/lib/libstd-150b24506f9fb8c9.'
COMMON={
    'bin/rustc': '4fa9a18b77430bcc416e88561b6fe5797d98b996a7698b9f3bd11d4e7817a19f',
    'lib/libLLVM.so.23.1-rust-1.99.0-beta': '43bac9749e539cd5988a4d5452b64582cf07ac9e7c059fde29c7bee76e106c51',
    RUSTLIB+'rlib': 'bb1da52e02b3bf34996fb9bc50c6d80b9244a23b8fe6d3b47f7eabd5953d4191',
    RUSTLIB+'rmeta': '88fbc0dcf152f1122ee039e7f80c1fcf7728cec59bb40ae7a23639ba12104928',
}
WRAPPER='b64346aae62ba44938e62e25c7dbb5641bc638c5c21afcfe44017da0b8e90e1f'
STACK_DRIVER='244cf510684e96c444fae9be8b91f7a9b11b83388a5c843f5e310adf3c2f3962'
SEEDS={'build':2396102628,'test':2396102629}
COMMIT='f1a7cf9d20b2cae39e991b178b56ba06b43dc8fa'

def checked(path, expected):
    path=path.resolve(strict=True)
    with path.open('rb') as source:
        observed=hashlib.file_digest(source,'sha256').hexdigest()
    if observed!=expected:raise ValueError((path,observed,expected))
    return {'path':str(path),'sha256':observed}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['runtime','registry','wrapper','parent-cargo','stack-cargo','parent-wild','stack-wild',
                 'pristine-driver','stack-driver','output']:
        ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--pristine-driver-sha256',required=True)
    args=ap.parse_args()
    for path,digest in COMMON.items():checked(args.runtime/path,digest)
    drivers={'parent':checked(args.pristine_driver,args.pristine_driver_sha256),
             'stack':checked(args.stack_driver,STACK_DRIVER)}
    spec={'runtime':str(args.runtime.resolve(strict=True)),'registry':str(args.registry.resolve(strict=True)),
          'wrapper':checked(args.wrapper,WRAPPER),'rustc_commit':COMMIT,'seeds':SEEDS,'common_hashes':COMMON,'arms':{}}
    for arm in ['parent','stack']:
        spec['arms'][arm]={'driver':drivers[arm],
                           'cargo':checked(getattr(args,arm+'_cargo'),CARGO[arm]),
                           'wild':checked(getattr(args,arm+'_wild'),WILD[arm])}
    with args.output.open('x') as target:
        json.dump(spec,target,indent=2,sort_keys=True)
        target.write('\n')

if __name__=='__main__':main()
