# Held generation on the real Ruff link

The real unchanged workspace hit on three separately invoked builds. A retained descriptor for the prior 227,979,336-byte executable stayed live through publication. One regular-creation receipt on the O_PATH challenge was dev 33, old inode 7766445 and newly created and published inode 7766441. The old inode then had no names and held 227,983,360 allocated bytes until its final handle closed. Writing through that original O_PATH capability left the new 86b94323… ELF intact. The source also handled an in-progress rewrite and atomic replacement of the original. A different file deliberately installed just before its exclusive destination open triggered a full native link; its held descriptor still contained the exact 55-byte sentinel.

The whole root used 78.51–78.56 billion retired user instructions on the three hits and 81.88 billion on one source/no-reuse control on that boot, including the coordinator. The first pre-build in-place corruption stimulus then hit Linux ETXTBSY. Its output had already passed the real changed test. A read-only owner also received EAGAIN for a write lease, while the same fresh-mount and tmpfs tiny controls granted that lease in the presence of O_PATH alone. The complete independent NEW, malformed and later repair gates were still pending at that point. [Full original](https://github.com/astral-experiments/ohm/actions/runs/41720378614)

    gh-auto api repos/astral-experiments/ohm/actions/artifacts/13272497744/zip > held.zip
    python3 -IB read_functional.py held.zip 01b7d15d79d713383e7330a6e25ad584aa8a8fbc 41720378614 3b359c9d8adb4722b5fcbfc9db7d9b9a6085f98ea9ce93fda10432489870ee04 > actual.json
    cmp actual.json functional-3-reopened.json
