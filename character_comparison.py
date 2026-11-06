"""Read-only PC/Wii U character comparison. No game Lua is executed or installed."""
from pathlib import Path,PurePosixPath
from collections import Counter,deque
import hashlib,json,re,sys,tempfile
ROOT=Path(__file__).resolve().parent
from research_pk_reader import Archive
from compare_config import Chunk,decode_tables
from check_wiiu_update import route
from read_binary_tup import parse as parse_tup

def logical_path(name):
 name=str(name).replace('\\','/').lower().removeprefix('assets/')
 p=PurePosixPath(name)
 if p.is_absolute()or '..'in p.parts or ':'in name:raise ValueError('Unsafe logical resource path')
 return p.as_posix()

def candidates(name,char):
 name=logical_path(name);bits=name.split('/');out=[]
 if len(bits)>2 and bits[0]=='characters':out.append('assets/characters/'+bits[1]+'/'+bits[1]+'.zip')
 if name.startswith('characters/')and len(bits)==2:out.append('assets/characters/characters.zip')
 if name.startswith('gamedb/'):out.append('assets/gamedb/'+bits[1]+'/'+bits[1]+'.zip'if len(bits)>2 else'assets/gamedb/'+char+'.zip')
 if name.startswith('ui/')and len(bits)>2:out.append('assets/ui/'+bits[1]+'/'+bits[1]+'.zip')
 if name.startswith('textures/')and len(bits)>1:out.append('assets/textures/'+bits[1][:2]+'.zip')
 out+=['assets/characters/'+char+'/'+char+'.zip','assets/gamedb/'+char+'.zip','assets/gamedb/core/core.zip']
 return list(dict.fromkeys(out))

class WiiReader:
 """Exact logical members and cumulative-hash archive candidates; no name guessing."""
 def __init__(self,base=None,update=None,cache=None):
  self.layers=[];self.archives={};self.failed_archives=set();self.archive_errors={};self.lookup_errors={};self.errors=[];self.sources={};self.cache=Path(cache or ROOT/'ComparisonCache');self.cache.mkdir(exist_ok=True)
  for role,value in (('base',base),('update',update)):
   if not value:continue
   p=Path(value).resolve();assert p.exists(),'Wii U '+role+' source does not exist: '+str(p)
   if (p/'Exports/content').is_dir():p=p/'Exports'
   if p.is_file():roots=[];packed=[p]
   else:
    roots=[p/'content/update/assets',p/'content/assets',p/'assets',p]
    packed=[p/'content/update/_root_.zip',p/'content/_root_.zip',p/'update/_root_.zip',p/'_root_.zip']
   self.layers.append(dict(role=role,path=p,roots=[x for x in roots if x.is_dir()],packed=[x for x in packed if x.is_file()]))
  assert self.layers,'Select at least one Wii U exported base/update source'
 def archive(self,path):
  path=Path(path)
  if path in self.failed_archives:raise ValueError('Archive reader previously failed for this source')
  if path not in self.archives:
   cache=self.cache/(hashlib.sha256(str(path).encode()).hexdigest()[:24]+'.json')
   # Reuse the independently stamped update index when it matches this exact archive.
   known=ROOT/'Alice/InventoryWork/root-index.json'
   if not cache.exists()and known.exists():
    saved=json.loads(known.read_text());s=saved.get('source',{});st=path.stat()
    if Path(s.get('path','')).resolve()==path.resolve()and s.get('bytes')==st.st_size and s.get('mtime_ns')==st.st_mtime_ns:cache.write_text(json.dumps(saved))
   opened=Archive.__new__(Archive)
   try:
    Archive.__init__(opened,path,cache);self.archives[path]=opened
   except Exception as e:
    handle=getattr(opened,'file',None)
    if handle is not None:handle.close()
    self.failed_archives.add(path);self.archive_errors[path]=str(e);raise
  return self.archives[path]
 def locate(self,name,archives,extract=True):
  name=logical_path(name)
  failures=[]
  for layer in reversed(self.layers):
   for root in layer['roots']:
    p=root/name
    if p.is_file():return self.record(p,None,name,layer,extract)
   paths=list(layer['packed'])
   for archive in archives:
    arc=logical_path(archive)
    for root in layer['roots']:
     for p in (root/arc,root/route(arc)):
      if p.is_file()and p not in paths:paths.append(p)
   for path in paths:
    if path in self.failed_archives:
     failures.append(str(path)+': '+self.archive_errors.get(path,'Archive reader failed'));continue
    try:
     a=self.archive(path)
     # Full logical path first. Basename is allowed only within its specifically routed archive.
     keys=[name]
     if path not in layer['packed']:keys.append(name.rsplit('/',1)[-1])
     key=next((x for x in keys if x in a.index),None)
     if key:return self.record(path,key,name,layer,extract)
    except Exception as e:
     message=str(path)+': '+str(e)
     failures.append(message)
     if message not in self.errors:self.errors.append(message)
  if failures:self.lookup_errors[name]=failures
  return None,None
 def record(self,path,member,name,layer,extract):
  data=self.archive(path).extract(member)if member else path.read_bytes()
  info={'source':str(path)+(' :: '+member if member else''),'container':str(path),'member':member,'layer':layer['role'],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'identity':'exact logical member'if member==name else'basename in explicitly routed archive'if member else'exact loose path'}
  self.sources[name]=info;return data,info
 def seeds(self,char):
  names=set();prefix='characters/'+char+'/'
  for layer in self.layers:
   for root in layer['roots']:
    folder=root/'characters'/char
    if folder.is_dir():names.update(p.relative_to(root).as_posix().lower()for p in folder.rglob('*')if p.is_file()and p.suffix.lower()!='.zip')
   paths=list(layer['packed'])
   for root in layer['roots']:
    arc='characters/'+char+'/'+char+'.zip'
    paths += [p for p in (root/arc,root/route(arc))if p.is_file()]
   for path in dict.fromkeys(paths):
    try:
     a=self.archive(path)
     for name in a.index:
      if name.startswith(prefix)or name in ('characters/'+char+'.dnax','gamedb/core/in3_'+char+'.lua','gamedb/core/in3_'+char+'_toolset.lua'):
       names.add(name)
      elif path not in layer['packed']and '/'not in name and name.endswith(('.oct','.bent','.mtb','.vbuf','.ibuf','.banm')):names.add(prefix+name)
    except Exception as e:
     msg=str(path)+': '+str(e)
     if msg not in self.errors:self.errors.append(msg)
  return names
 def close(self):
  for a in self.archives.values():a.close()

def key_name(k):
 if isinstance(k,str):
  k=k[2:]if k.startswith('s:')else'[number:'+k[2:]+']'if k.startswith('n:')else k
  return k.replace('~','~0').replace('/','~1')
 return '['+type(k).__name__+':'+str(k)+']'

def typed(value):
 # Preserve numeric/string key distinction, but Lua integral doubles equal integer keys.
 if isinstance(value,dict):return {('s:'+k)if isinstance(k,str)else('n:'+format(k,'.17g'))if isinstance(k,(int,float))and not isinstance(k,bool)else(type(k).__name__+':'+str(k)):typed(v)for k,v in value.items()}
 if isinstance(value,list):return [typed(x)for x in value]
 return value

def differences(a,b,path='',limit=160):
 out=[];truncated=False
 def excerpt(v):
  s=json.dumps(v,ensure_ascii=False,default=str);return v if len(s)<700 else s[:697]+'…'
 def emit(p,kind,x=None,y=None):
  nonlocal truncated
  if len(out)>=limit:truncated=True;return
  out.append({'field':p or'/','change':kind,'pc':excerpt(x),'wiiu':excerpt(y)})
 def visit(x,y,p):
  if truncated:return
  if isinstance(x,dict)and isinstance(y,dict):
   for k in sorted(x.keys()|y.keys(),key=str):
    q=p+'/'+key_name(k)
    if k not in x:emit(q,'wiiu_only',None,y[k])
    elif k not in y:emit(q,'pc_only',x[k],None)
    else:visit(x[k],y[k],q)
  elif isinstance(x,list)and isinstance(y,list):
   if len(x)!=len(y):emit(p+'/length','changed',len(x),len(y))
   for i,(u,v)in enumerate(zip(x,y)):visit(u,v,p+'/'+str(i))
  elif x!=y:emit(p,'changed',x,y)
 visit(a,b,path);return out,truncated

def array_storage_risks(proto):
 """Flag numeric sequences constructed solely in preallocated hash storage.

 This is a conservative storage warning, not a Lua iteration emulator.
 """
 regs={};globals_={};constants=[x['value']for x in proto['constants']];code=proto['instructions'];at=0
 def rk(k):return constants[k&255]if k&256 else regs[k]
 while at<len(code):
  w=code[at];at+=1;op=w&63;a=(w>>6)&255;c=(w>>14)&511;b=(w>>23)&511
  if op==1:regs[a]=constants[w>>14]
  elif op==2:regs[a]=bool(b)
  elif op==3:
   for i in range(a,b+1):regs[i]=None
  elif op==10:regs[a]={'entries':{},'array_hint':b,'hash_hint':c,'setlist':False}
  elif op==9:regs[a]['entries'][rk(b)]=rk(c)
  elif op==7:globals_[constants[w>>14]]=regs[a]
  elif op==34:
   if c==0:c=code[at];at+=1
   regs[a]['setlist']=True
   for i in range(1,b+1):regs[a]['entries'][(c-1)*50+i]=regs[a+i]
  elif op==30:break
  else:raise ValueError('Unreviewed literal instruction for storage inspection')
 risks=[]
 def visit(t,path):
  if not isinstance(t,dict)or'entries'not in t:return
  entries=t['entries'];keys=list(entries)
  if keys and all(type(k)in(int,float)and int(k)==k for k in keys)and set(keys)==set(range(1,len(keys)+1))and t['array_hint']==0 and t['hash_hint']>0 and not t['setlist']:
   risks.append({'field':path,'length':len(keys),'reason':'Contiguous numeric sequence uses an explicit hash-table constructor; storage iteration order requires review.'})
  for k,v in entries.items():visit(v,path+'/'+str(k))
 for k,v in globals_.items():visit(v,'/'+str(k))
 return risks

def decode(data,name,temp):
 """Return only reviewed structural interpretations, with opaque coverage explicit."""
 if data.startswith(b'\x1bLua'):
  proto=Chunk(data).read();tables=decode_tables(proto,True)
  return {'format':'Lua 5.1 literal tables','byte_order':'little'if data[6]else'big','coverage':'full_literal_tables','array_storage_risks':array_storage_risks(proto),'value':typed(tables)}
 if data[:4]in (bytes.fromhex('45017629'),bytes.fromhex('29760145')):
  p=Path(temp)/'resource.bin';p.write_bytes(data);d=parse_tup(p);nodes=[];opaque=[]
  for i,n in enumerate(d['nodes']):
   v=n['value']
   if isinstance(v,dict)and 'base64'in v:
    import base64
    payload=base64.b64decode(v['base64']);v={'opaque_bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()};opaque.append(n['key'])
   nodes.append({k:n[k]for k in ('depth','kind','data_type','key','name','parent')}|{'value':v})
  return {'format':'BinaryTup','byte_order':d['byte_order'],'coverage':'container_with_opaque_payloads'if opaque else'full_primitive_tree','opaque_fields':sorted(set(opaque)),'value':{'version':d['version'],'nodes':nodes}}
 ext=Path(name).suffix.lower()
 if ext in ('.banm','.animtreeoverrides','.json','.txt','.xml')or(data[:1]in (b'<',b'{')and b'\0'not in data):
  text=data.decode('utf-8-sig').replace('\r\n','\n');return {'format':'UTF-8 text','coverage':'text_only','value':text}
 raise ValueError('No reviewed structural comparison decoder for '+ext+' (byte hashes retained)')

def references(data,name):
 values=[]
 if data.startswith(b'\x1bLua'):
  def strings(t):
   if isinstance(t,dict):
    for k,v in t.items():
     if isinstance(v,str):yield v
     yield from strings(v)
  values=list(strings(decode_tables(Chunk(data).read(),True)))
 elif data[:4]in (bytes.fromhex('45017629'),bytes.fromhex('29760145'))and len(data)>=60:
  order='big'if data[:4]==bytes.fromhex('45017629')else'little';n=int.from_bytes(data[12:16],order)
  if 60+n>len(data):return []
  values=data[60:60+n].decode('utf-8').split('\0')
 elif name.endswith(('.banm','.animtreeoverrides')):values=re.findall(r'"([^"\r\n]+)"',data.decode('utf-8-sig'))
 out=[]
 for v in values:
  v=v.replace('\\','/').lower()
  if re.fullmatch(r'(?:characters|gamedb|ui|materials|textures|choreographies|presentation)/[a-z0-9_./ -]+\.[a-z0-9_]+',v):out.append(logical_path(v))
 return sorted(set(out))

def compare_character(report,pc,base=None,update=None,max_resources=2000):
 wii=WiiReader(base,update);char=report['character'];rows=[];errors=[];seen=set();queue=deque();reasons={}
 def add(name,why):
  name=logical_path(name)
  if name not in reasons:queue.append(name);reasons[name]=[]
  if why not in reasons[name]:reasons[name].append(why)
 for name in report.get('sources',{}):add(name,'Read by PC character report')
 for name in report.get('motion_dependencies',{}):add(name,'PC BENT/BANM motion reference')
 for name in sorted(wii.seeds(char)):add(name,'Exact character resource or named character-package member in Wii U source')
 # Include all members of the effective PC character package, beyond BENT aliases.
 package='assets/characters/'+char+'/'+char+'.zip';p=pc.loose(package)
 if p:
  try:
   if p not in pc.archives:pc.archives[p]=Archive(p)
   for name in pc.archives[p].index:
    add(name if name.startswith('characters/')else'characters/'+char+'/'+name,'PC character-package member')
  except Exception as e:errors.append('PC character package: '+str(e))
 for name in ('characters/'+char+'.dnax','gamedb/core/in3_'+char+'.lua','gamedb/core/in3_'+char+'_toolset.lua'):add(name,'Conventional character configuration candidate')
 print('Comparing PC vs Wii U sources for',char,'initial resources:',len(queue),flush=True)
 try:
  with tempfile.TemporaryDirectory(prefix='di-character-compare-')as temp:
   while queue and len(rows)<max_resources:
    name=queue.popleft()
    if name in seen:continue
    seen.add(name);arc=candidates(name,char);row={'logical':name,'reasons':reasons[name]};a=b=None
    before_errors=len(pc.errors)
    try:
     a=pc.read(name,arc)
     if a is None and len(pc.errors)>before_errors:row['pc_read_error']='; '.join(pc.errors[before_errors:])
    except Exception as e:row['pc_read_error']=str(e)
    row['pc']=pc.sources.get(name)if a is not None else None
    try:
     b,info=wii.locate(name,arc);row['wiiu']=info
     if b is None and wii.lookup_errors.get(name):row['wiiu_read_error']='; '.join(wii.lookup_errors[name])
    except Exception as e:row['wiiu']=None;row['wiiu_read_error']=str(e)
    if a is None or b is None:
     row['status']='read_error'if row.get('pc_read_error')or row.get('wiiu_read_error')else'pc_only_in_scope'if a is not None else'wiiu_only_in_scope'if b is not None else'unresolved_both'
     row['meaning']='Presence is limited to the declared readers, candidate archives and source layers; not proof of game-wide absence.'
    elif a==b:row['status']='same_bytes'
    else:
     decoded={}
     for side,data in (('pc',a),('wiiu',b)):
      try:
       d=decode(data,name,temp);decoded[side]=d;row[side+'_decoding']={k:v for k,v in d.items()if k!='value'}
      except Exception as e:row[side+'_decode_error']=str(e)
     if len(decoded)<2:row['status']='decode_unavailable'
     else:
      x,y=decoded['pc'],decoded['wiiu'];equal=x['value']==y['value'];row['decoded_equal']=equal
      opaque=any('opaque'in d.get('coverage','')for d in (x,y));storage_risk=any(d.get('array_storage_risks')for d in (x,y))
      if opaque or storage_risk:row['status']='partial_comparison'
      elif equal:row['status']='needs_conversion'if x.get('byte_order')!=y.get('byte_order')else'same_data'
      else:row['status']='different_data'
      if not equal:row['differences'],row['differences_truncated']=differences(x['value'],y['value'])
      if opaque:row['meaning']='Container fields compared; opaque animation/mesh payloads are hashed, not semantically decoded. Payload differences may be platform layouts.'
      if storage_risk:row['meaning']='Literal values compared, but explicit hash-backed numeric arrays need iteration-order review. Value equality alone does not verify the native stream loader contract.'
      if row['status']=='needs_conversion':row['meaning']='Decoded data matches but storage byte order differs. Conversion is indicated; no converter was executed or gameplay validated.'
    rows.append(row)
    # Follow only character-local and motion/blend paths, avoiding whole global tables.
    for side,data in (('PC',a),('Wii U',b)):
     if data is None or not(name.startswith('characters/'+char+'/')or name=='characters/'+char+'.dnax'):continue
     try:
      for ref in references(data,name):add(ref,side+' reference from '+name)
     except Exception as e:errors.append(name+' '+side+' reference decode: '+str(e))
    if len(rows)%100==0:print('Compared',len(rows),'resources; pending',len(queue),flush=True)
 finally:wii.close()
 counts=dict(Counter(r['status']for r in rows))
 return {'schema':'di-character-comparison-v1','character':char,'scope':{'pc_base':report['game'],'pc_mod_layers_low_to_high':report.get('mod_layers_low_to_high',[]),'wiiu_layers_low_to_high':[{'role':r['role'],'path':str(r['path'])}for r in wii.layers],'lookup':'Exact loose logical paths, exact root-archive members, and named/cumulative-hash archive candidates. Hashed archive names alone do not establish identity; internal members are checked.','limit':max_resources,'partial':bool(queue),'remaining_resources':len(queue)},'summary':counts,'resources':rows,'reader_errors':wii.errors+errors,'limitations':['No executable or script execution; no conversion, installation or mod packaging.','Only-in-scope means the other side was not resolved in inspected source candidates, not proven absent from the game.','BinaryTup container comparison does not decode opaque curve/vertex payloads; these remain partial comparisons.','Named Wii U exports or exported content/assets are required; encrypted NUS .app containers are not read here.','Native function support cannot be inferred from data differences; runtime/executable evidence remains a separate task.']}
