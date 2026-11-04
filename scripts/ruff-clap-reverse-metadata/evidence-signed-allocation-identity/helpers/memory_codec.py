"""Unsigned LEBs and rustc -24 initialized-memory allocation records.

Original four functions verbatim from the independently reviewed alias decoder
SHA-256 12e8e8ce5cc4227b5cb0a4234bb4a82e1aa9132c377f93ca66d8cfeeabcd347d.
"""

def read(b,i):
    n=0
    for j in range(10):
        c=b[i+j];n|=(c&127)<<(j*7)
        if c<128:return n,i+j+1
    raise ValueError("integer too large")

def encode(n):
    buf=bytearray()
    while n>=128:buf.append(128|(n&127));n>>=7
    buf.append(n);return bytes(buf)

def unpack(row):
    assert row[0]==0
    flags=row[1];n,i=read(row,2)
    if not flags&128:i+=n
    ptrs,i=read(row,i);start=i;refs=[]
    for _ in range(ptrs):
        off,i=read(row,i);idx,i=read(row,i);immutable,shared=row[i:i+2];i+=2
        assert immutable<=1 and shared<=1 and (not refs or off>refs[-1][0]) and off<n
        refs.append((off,idx,immutable,shared))
    suffix=row[i:]
    mask=suffix[0];j=1
    if mask==0:assert suffix[j]<=1;j+=1
    else:
        assert mask==1
        words,j=read(suffix,j);j+=8*words
    expected,j=read(suffix,j);assert expected==n and j==len(suffix)
    return row[:start],refs,suffix

def pack(rec,mapping):
    p,refs,s=rec
    return p+b"".join(encode(off)+encode(mapping[idx])+bytes((immutable,shared))for off,idx,immutable,shared in refs)+s
