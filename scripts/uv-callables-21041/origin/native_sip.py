"""Stable SipHash-128; matched to all 64 rustc-stable-hash vectors and actual native derive seeds."""
MASK=2**64-1
def rol(v,n):return ((v<<n)|(v>>(64-n)))&MASK
def run(s):
    a,b,c,d=s
    a=(a+b)&MASK;c=(c+d)&MASK;b=rol(b,13)^a;d=rol(d,16)^c;a=rol(a,32)
    c=(c+b)&MASK;a=(a+d)&MASK;b=rol(b,17)^c;d=rol(d,21)^a;c=rol(c,32)
    return a,b,c,d
def hash128(data,k0=0,k1=0):
    a,b,c,d=(k0^0x736f6d6570736575,k1^0x646f72616e646f6d^0xee,k0^0x6c7967656e657261,k1^0x7465646279746573)
    pos=0
    while pos+8<=len(data):
        word=int.from_bytes(data[pos:pos+8],'little');a,b,c,d=run((a,b,c,d^word));a^=word;pos+=8
    last=((len(data)&255)<<56)|int.from_bytes(data[pos:],'little')
    a,b,c,d=run((a,b,c,d^last));a^=last;c^=0xee
    for _ in range(3):a,b,c,d=run((a,b,c,d))
    lo=a^b^c^d;b^=0xdd
    for _ in range(3):a,b,c,d=run((a,b,c,d))
    return lo,a^b^c^d
