"""Read rustc measureme v9 pages and string IDs with the existing real-graph reader."""
import functools
import struct


class Profile:
    def __init__(self,data):
        hdr=b'\x09\x00\x00\x00';assert data[:8]==b'MMPD'+hdr
        pages=[bytearray() for _ in range(3)];cursor=8
        while cursor<len(data):
            tag,n=struct.unpack_from('<BI',data,cursor);cursor+=5
            assert tag<3 and 0<n<=len(data)-cursor
            pages[tag]+=data[cursor:cursor+n];cursor+=n
        events,table,index=pages
        assert [x[:8] for x in pages]==[tag+hdr for tag in (b'MMES',b'MMSD',b'MMSI')]
        self.virtual=dict(struct.iter_unpack('<QQ',memoryview(index)[8:]));base=100000003
        @functools.cache
        def string(off):
            x=bytearray();i=off
            while True:
                ch=table[i];i+=1
                if ch==255:return x.decode()
                if ch==254:
                    ref,=struct.unpack_from('<Q',table,i);i+=8
                    x.extend(string(ref-base if ref>=base else self.virtual[ref]).encode())
                else:x.append(ch)
        @functools.cache
        def label(idx):
            if idx>=base:return string(idx-base)
            return string(self.virtual[idx]) if idx in self.virtual else ''
        self.label=label;self.entries=events
