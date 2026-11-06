"""Read BinaryTup records using Wii U RPX routines documented in README.md.
Does not interpret renderer vertex formats or create meshes.
"""
import argparse, base64, hashlib, json, struct
from pathlib import Path

def parse(path):
    b=Path(path).read_bytes()
    endian={bytes.fromhex('45017629'):'>',bytes.fromhex('29760145'):'<'}.get(b[:4])
    if endian is None or len(b)<60: raise ValueError('Invalid BinaryTup magic/header')
    version=struct.unpack_from(endian+'f',b,4)[0]
    string_size,atom_size,declared=struct.unpack_from(endian+'III',b,12)
    if 60+string_size+atom_size!=len(b): raise ValueError('Header length mismatch')
    raw=b[60:60+string_size]
    if not raw.endswith(b'\0'): raise ValueError('Unterminated string table')
    strings=[s.decode('utf-8') for s in raw[:-1].split(b'\0')]
    index_bytes=2 if len(strings)<=65536 else 4
    pos=60+string_size; nodes=[]; stack=[]
    def take(n):
        nonlocal pos
        if n<0 or pos+n>len(b): raise ValueError(f'Truncated record at {pos}')
        v=b[pos:pos+n];pos+=n;return v
    def uint(n): return int.from_bytes(take(n),'big' if endian=='>' else 'little')
    def string():
        i=uint(index_bytes)
        if i>=len(strings): raise ValueError(f'Bad string index {i} at {pos}')
        return strings[i]
    while pos<len(b):
        offset=pos;flags=uint(2);depth=flags>>10;kind=flags&3;dtype=(flags>>3)&7
        key=string();name=string() if flags&4 else None
        count_bytes=((flags>>6)&3)+1;int_bytes=((flags>>8)&3)+1
        count=1
        if kind==2 or (kind==3 and dtype==4): count=uint(count_bytes)
        if kind==1: value=None
        elif kind in (2,3):
            if dtype==1: value=[string() for _ in range(count)]
            elif dtype==2: value=[struct.unpack(endian+'f',take(4))[0] for _ in range(count)]
            elif dtype==3: value=[int.from_bytes(take(int_bytes),'big' if endian=='>' else 'little',signed=True) for _ in range(count)]
            elif dtype==4 and kind==3: value={'base64':base64.b64encode(take(count)).decode(),'bytes':count}
            else: raise ValueError(f'Unsupported kind/data type {kind}/{dtype} at {offset}')
            if kind==3 and dtype!=4: value=value[0]
        else: raise ValueError(f'Invalid atom kind at {offset}')
        while stack and nodes[stack[-1]]['depth']>=depth: stack.pop()
        if not nodes:
            if depth!=0: raise ValueError('First record is not root')
        elif not stack or depth!=nodes[stack[-1]]['depth']+1 or nodes[stack[-1]]['kind']!=1:
            raise ValueError(f'Invalid hierarchy at {offset}')
        node=dict(offset=offset,end=pos,flags=hex(flags),depth=depth,kind=kind,data_type=dtype,key=key,name=name,value=value,parent=stack[-1] if stack else None)
        nodes.append(node);stack.append(len(nodes)-1)
    if len(nodes)!=declared: raise ValueError(f'Atom count {len(nodes)} != header {declared}')
    return dict(input=str(path),sha256=hashlib.sha256(b).hexdigest(),byte_order='big' if endian=='>' else 'little',version=version,string_bytes=string_size,string_count=len(strings),atom_start=60+string_size,atom_bytes=atom_size,declared_atoms=declared,parsed_atoms=len(nodes),exact_end=pos==len(b),strings=strings,nodes=nodes)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('files',nargs='+');ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    for f in args.files:
        result=parse(f);out=args.output/(Path(f).name+'.json');out.write_text(json.dumps(result,indent=2,allow_nan=False),encoding='utf-8')
        print(f'{Path(f).name}: {result["parsed_atoms"]} atoms, {result["string_count"]} strings, exact EOF; {out}')
