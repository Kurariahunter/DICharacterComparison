"""Bounded read-only DI PK-FFFF reader for source gathering, methods 0/8.

Outer index and each local header restart CTR independently. Payload encryption
continues from its local header for a prefix (or whole DCT). CRC is checked on
every extracted member. Unsupported formats are explicit errors.
"""
from pathlib import Path,PurePosixPath
import struct,zlib,json
from Crypto.Cipher import AES
KEY=bytes.fromhex('681bbeea63160188f9b7945104a51499')

class Archive:
    def __init__(self,path,cache=None):
        self.path=Path(path);self.file=self.path.open('rb');self.size=self.path.stat().st_size
        self.index={}
        stamp=dict(path=str(self.path.resolve()),bytes=self.size,mtime_ns=self.path.stat().st_mtime_ns,reader='pk-gather-v1')
        if cache and Path(cache).exists():
            saved=json.loads(Path(cache).read_text(encoding='utf-8'))
            if saved.get('source')==stamp:self.index=saved['members'];return
        h=self.ctr(self.read(0,8))
        if h[:4]!=b'PK\xff\xff':raise ValueError('Not a standard-key PK-FFFF archive')
        count=struct.unpack_from('<I',h,4)[0]
        if count>100000 or 8+8*count>self.size:raise ValueError('Invalid archive index extent')
        index=self.ctr(self.read(0,8+8*count))
        for i in range(count):
            offset=struct.unpack_from('<I',index,12+8*i)[0]
            record=self.local(offset)
            key=record['name'].lower()
            if key in self.index:raise ValueError('Duplicate logical member requires review: '+key)
            self.index[key]=record
            if i and i%10000==0:print('Indexed',self.path.name,i,'/',count,flush=True)
        if cache:
            Path(cache).parent.mkdir(parents=True,exist_ok=True)
            Path(cache).write_text(json.dumps(dict(source=stamp,members=self.index)),encoding='utf-8')
    @staticmethod
    def ctr(raw):return AES.new(KEY,AES.MODE_CTR,nonce=b'').decrypt(raw)
    def read(self,offset,size):
        if offset<0 or size<0 or offset+size>self.size:raise ValueError('Source extent outside archive')
        self.file.seek(offset);raw=self.file.read(size)
        if len(raw)!=size:raise ValueError('Short source read')
        return raw
    @staticmethod
    def safe(name):
        name=name.replace('\\','/')
        p=PurePosixPath(name)
        if not name or p.is_absolute()or ':'in name or any(x in ('','..','.')for x in name.split('/')):raise ValueError('Unsafe archive member path')
        return p.as_posix()
    def local(self,offset):
        head=self.ctr(self.read(offset,30))
        if head[:4]!=b'PK\x03\x04':raise ValueError('Invalid local header')
        flags,method=struct.unpack_from('<HH',head,6)
        crc,packed,size=struct.unpack_from('<III',head,14);n,e=struct.unpack_from('<HH',head,26)
        if n==0 or n>4096 or offset+30+n+e+packed>self.size:raise ValueError('Invalid local member extent')
        allhead=self.ctr(self.read(offset,30+n+e))
        name=self.safe(allhead[30:30+n].decode('utf-8'))
        return dict(name=name,offset=offset,payload_offset=offset+30+n+e,packed=packed,bytes=size,crc32=f'{crc:08x}',method=method,flags=flags)
    def extract(self,logical):
        r=self.index[logical.lower()]
        if r['bytes']>64*1024*1024 or r['packed']>64*1024*1024:raise ValueError('Member exceeds gather size limit')
        if r['method']not in (0,8):raise ValueError('Compression method requires QuickBMS: '+str(r['method']))
        head=r['payload_offset']-r['offset'];prefix=r['packed'] if r['name'].lower().endswith('.dct')else min(512,r['packed'])
        decoded=self.ctr(self.read(r['offset'],head+prefix))[head:]
        packed=decoded+self.read(r['payload_offset']+prefix,r['packed']-prefix)
        if r['method']==0:result=packed
        else:
            d=zlib.decompressobj(-15);result=d.decompress(packed,r['bytes']+1)
            if not d.eof or d.unused_data or d.unconsumed_tail:raise ValueError('Deflate member stream/extent mismatch')
        if len(result)!=r['bytes']or f'{zlib.crc32(result)&0xffffffff:08x}'!=r['crc32']:raise ValueError('Member size/CRC mismatch')
        return result
    def close(self):self.file.close()
