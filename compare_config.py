"""Read-only Lua 5.1 structure comparison; never executes extracted Lua."""
from pathlib import Path
import struct, json, hashlib, collections

P=Path(__file__).resolve().parent
GAME=Path('assets') # Used only by historical direct-entry code; reporter uses explicit paths.

class Chunk:
    def __init__(self, data):
        self.data=data; self.at=12
        if data[:6]!=b'\x1bLuaQ\x00': raise ValueError('Not standard Lua 5.1')
        if data[6] not in (0,1): raise ValueError('Invalid byte order')
        self.order='little' if data[6] else 'big'
        self.intsize,self.strsize,self.opsize,self.numsize,self.integral=data[7:12]
        if (self.intsize,self.strsize,self.opsize,self.numsize,self.integral)!=(4,4,4,8,0): raise ValueError('Unreviewed Lua layout')
    def take(self,n):
        if n<0 or self.at+n>len(self.data): raise ValueError('Truncated Lua chunk')
        result=self.data[self.at:self.at+n];self.at+=n;return result
    def uint(self,n=4):return int.from_bytes(self.take(n),self.order)
    def count(self):
        n=self.uint()
        if n>len(self.data):raise ValueError('Unreasonable count')
        return n
    def string(self):
        n=self.count()
        if n==0:return None
        raw=self.take(n)
        if raw[-1:]!=b'\0':raise ValueError('String missing terminator')
        return raw[:-1].decode('utf-8',errors='backslashreplace')
    def proto(self):
        source=self.string();line=self.uint();last=self.uint();flags=list(self.take(4))
        code=[self.uint() for _ in range(self.count())]
        constants=[]
        for _ in range(self.count()):
            tag=self.uint(1)
            if tag==0:v=None
            elif tag==1:v=bool(self.uint(1))
            elif tag==3:v=struct.unpack('<d' if self.order=='little' else '>d',self.take(8))[0]
            elif tag==4:v=self.string()
            else:raise ValueError(f'Unknown constant tag {tag}')
            constants.append(dict(tag=tag,value=v))
        children=[self.proto()for _ in range(self.count())]
        for _ in range(self.count()):self.uint()
        for _ in range(self.count()):self.string();self.uint();self.uint()
        for _ in range(self.count()):self.string()
        return dict(flags=flags,instructions=code,constants=constants,prototypes=children)
    def read(self):
        result=self.proto()
        if self.at!=len(self.data):raise ValueError('Trailing chunk bytes')
        return result

def sha(data):return hashlib.sha256(data).hexdigest()
def strings(proto):
    result=[c['value']for c in proto['constants']if c['tag']==4]
    for child in proto['prototypes']:result.extend(strings(child))
    return result

def decode_tables(proto, preserve_key_types=False):
    """Interpret only literal table constructors; reject calls/control flow."""
    registers={};globals_={};constants=[c['value']for c in proto['constants']]
    def rk(n): return constants[n&255] if n&256 else registers[n]
    code=proto['instructions'];pc=0
    while pc<len(code):
        word=code[pc];pc+=1;op=word&63;a=(word>>6)&255;c=(word>>14)&511;b=(word>>23)&511;bx=word>>14
        if op==1:registers[a]=constants[bx]
        elif op==2:
            if c:raise ValueError('LOADBOOL skip not supported')
            registers[a]=bool(b)
        elif op==3:
            for i in range(a,b+1):registers[i]=None
        elif op==10:registers[a]={}
        elif op==9:
            table=registers[a]
            if not isinstance(table,dict):raise ValueError('SETTABLE target not table')
            table[rk(b)]=rk(c)
        elif op==7:globals_[constants[bx]]=registers[a]
        elif op==34:
            if b==0:raise ValueError('Dynamic SETLIST not supported')
            if c==0:c=code[pc];pc+=1
            for i in range(1,b+1):registers[a][(c-1)*50+i]=registers[a+i]
        elif op==30:
            if pc!=len(code):raise ValueError('Nonfinal RETURN')
        else:raise ValueError(f'Not a literal-table opcode: {op}')
    def clean(value):
        if not isinstance(value,dict):return value
        keys=[str(k)for k in value]
        if len(set(keys))!=len(keys):raise ValueError('JSON key collision')
        return {str(k):clean(v)for k,v in sorted(value.items(),key=lambda x:str(x[0]))}
    return globals_ if preserve_key_types else clean(globals_)

def differences(left,right,path=''):
    if isinstance(left,dict) and isinstance(right,dict):
        for key in sorted(left.keys()|right.keys()):
            sub=path+'/'+key
            if key not in left:yield dict(path=sub,status='pc_only',pc=right[key])
            elif key not in right:yield dict(path=sub,status='wiiu_only',wiiu=left[key])
            else:yield from differences(left[key],right[key],sub)
    elif type(left)!=type(right) or left!=right:yield dict(path=path,status='changed',wiiu=left,pc=right)

def main():
    out=P/'ConfigComparison';out.mkdir(exist_ok=True)
    wii=P/'WiiUExtract/_root_';pc=P/'PCConfigExtract'
    pairs=[('DNA','characters/ali_alice.dnax','characters/ali_alice.dnax'),
        ('progression','gamedb/core/in3_ali_alice.lua','core/in3_ali_alice.lua'),
        ('toolset','gamedb/core/in3_ali_alice_toolset.lua','core/in3_ali_alice_toolset.lua'),
        ('combos','gamedb/core/emuinfo_av_alice.lua','core/emuinfo_av_alice.lua')]
    results=[]
    for label,wrel,prel in pairs:
        wp=wii/wrel;pp=pc/prel;wb=wp.read_bytes();pb=pp.read_bytes()
        wr=Chunk(wb);pr=Chunk(pb);wt=wr.read();pt=pr.read()
        ws=set(strings(wt));ps=set(strings(pt))
        wtables=decode_tables(wt);ptables=decode_tables(pt)
        delta=list(differences(wtables,ptables))
        row=dict(role=label,wiiu=str(wp),pc_archive_extraction=str(pp),wiiu_bytes=len(wb),pc_bytes=len(pb),wiiu_sha256=sha(wb),pc_sha256=sha(pb),
            byte_identical=wb==pb,wiiu_byte_order=wr.order,pc_byte_order=pr.order,
            normalized_prototype_equal=wt==pt,strings_only_wiiu=sorted(ws-ps),strings_only_pc=sorted(ps-ws),
            shared_string_count=len(ws&ps))
        row.update(literal_tables_equal=wtables==ptables,table_difference_count=len(delta),difference_status_counts=dict(collections.Counter(d['status']for d in delta)))
        (out/(label+'-wiiu-tables.json')).write_text(json.dumps(wtables,indent=2),encoding='utf-8')
        (out/(label+'-pc-tables.json')).write_text(json.dumps(ptables,indent=2),encoding='utf-8')
        (out/(label+'-table-diff.json')).write_text(json.dumps(delta,indent=2),encoding='utf-8')
        loose=GAME/wrel
        if loose.is_file():row['pc_loose']=dict(path=str(loose),sha256=sha(loose.read_bytes()),matches_pc_archive=loose.read_bytes()==pb,matches_wiiu=loose.read_bytes()==wb)
        (out/(label+'-wiiu.json')).write_text(json.dumps(wt,indent=2),encoding='utf-8')
        (out/(label+'-pc.json')).write_text(json.dumps(pt,indent=2),encoding='utf-8')
        results.append(row)
        print(label,'bytes',row['byte_identical'],'normalized prototype',row['normalized_prototype_equal'],'endian',wr.order,pr.order,'unique strings',len(ws-ps),len(ps-ws))
    report=dict(scope='Lua instruction words, constant values and nested prototypes normalized for byte order; source/debug metadata excluded. No script execution, decompilation or gameplay equivalence claim.',pairs=results)
    (out/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for row in results:
        print(row['role'],'Wii U only strings:',row['strings_only_wiiu'][:35]);print(row['role'],'PC only strings:',row['strings_only_pc'][:35])
    print('Report:',out/'comparison.json')

if __name__=='__main__':main()
