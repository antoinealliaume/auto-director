import hashlib,hmac,os,secrets,uuid
from datetime import datetime,timezone
from typing import Optional
import psycopg
import redis
from fastapi import FastAPI,File,Form,Header,HTTPException,UploadFile
from fastapi.responses import HTMLResponse,Response
from pydantic import BaseModel

DATABASE_URL=os.environ['DATABASE_URL']
REDIS_URL=os.environ['REDIS_URL']
STUDIO_PASSWORD=os.environ.get('STUDIO_PASSWORD','change-me-now')
TOKEN_SECRET=os.environ.get('TOKEN_SECRET',secrets.token_hex(32))
MAX_UPLOAD_MB=int(os.environ.get('MAX_UPLOAD_MB','60'))

app=FastAPI(title='Auto Director Studio',version='6.0')
r=redis.from_url(REDIS_URL,decode_responses=True)

def db(): return psycopg.connect(DATABASE_URL)
def now(): return datetime.now(timezone.utc)
def sign(v:str)->str: return hmac.new(TOKEN_SECRET.encode(),v.encode(),hashlib.sha256).hexdigest()
def make_token()->str:
    raw=secrets.token_urlsafe(32); return raw+'.'+sign(raw)
def require_auth(authorization:Optional[str]):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Non autorisé')
    token=authorization[7:]; parts=token.rsplit('.',1)
    if len(parts)!=2 or not hmac.compare_digest(sign(parts[0]),parts[1]): raise HTTPException(401,'Session invalide')

def init_db():
    with db() as c:
        c.execute('''create table if not exists projects(id uuid primary key,name text not null,created_at timestamptz not null default now());
        create table if not exists assets(id uuid primary key,project_id uuid references projects(id) on delete set null,name text not null,content_type text not null,size bigint not null,role text not null default 'source',kind text not null default 'source',data bytea not null,created_at timestamptz not null default now());
        create table if not exists jobs(id uuid primary key,project_id uuid references projects(id) on delete cascade,status text not null,stage text not null default 'queued',progress int not null default 0,message text not null default '',variants int not null default 1,settings jsonb not null default '{}'::jsonb,output_asset_ids uuid[] not null default '{}',created_at timestamptz not null default now(),updated_at timestamptz not null default now());
        create table if not exists feedback(id uuid primary key,asset_id uuid references assets(id) on delete cascade,views bigint default 0,likes bigint default 0,comments bigint default 0,shares bigint default 0,completion double precision default 0,conversions bigint default 0,revenue double precision default 0,created_at timestamptz not null default now());''')

@app.on_event('startup')
def startup(): init_db()

@app.get('/health')
def health():
    ok_db=ok_redis=False
    try:
        with db() as c: c.execute('select 1'); ok_db=True
    except Exception: pass
    try: ok_redis=bool(r.ping())
    except Exception: pass
    return {'ok':ok_db and ok_redis,'database':ok_db,'queue':ok_redis,'version':'6.0'}

@app.get('/',response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)

class Login(BaseModel): password:str
@app.post('/api/login')
def login(x:Login):
    if not hmac.compare_digest(x.password,STUDIO_PASSWORD): raise HTTPException(401,'Mot de passe incorrect')
    return {'token':make_token()}

@app.get('/api/dashboard')
def dashboard(authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c:
        projects=c.execute('select id,name,created_at from projects order by created_at desc').fetchall()
        assets=c.execute("select id,project_id,name,content_type,size,role,kind,created_at from assets order by created_at desc limit 200").fetchall()
        jobs=c.execute('select id,project_id,status,stage,progress,message,variants,output_asset_ids,created_at,updated_at from jobs order by created_at desc limit 100').fetchall()
    def ser(row,keys): return {k:(str(v) if isinstance(v,uuid.UUID) else [str(x) for x in v] if isinstance(v,list) and v and isinstance(v[0],uuid.UUID) else v.isoformat() if hasattr(v,'isoformat') else v) for k,v in zip(keys,row)}
    return {'projects':[ser(x,['id','name','createdAt']) for x in projects],'assets':[ser(x,['id','projectId','name','contentType','size','role','kind','createdAt']) for x in assets],'jobs':[ser(x,['id','projectId','status','stage','progress','message','variants','outputAssetIds','createdAt','updatedAt']) for x in jobs]}

class ProjectIn(BaseModel): name:str
@app.post('/api/projects')
def create_project(x:ProjectIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization); pid=uuid.uuid4()
    with db() as c: c.execute('insert into projects(id,name) values(%s,%s)',(pid,x.name.strip()[:120] or 'Projet'))
    return {'id':str(pid),'name':x.name}

@app.post('/api/assets')
async def upload_asset(file:UploadFile=File(...),project_id:Optional[str]=Form(None),role:str=Form('source'),authorization:Optional[str]=Header(None)):
    require_auth(authorization); data=await file.read((MAX_UPLOAD_MB+1)*1024*1024)
    if len(data)>MAX_UPLOAD_MB*1024*1024: raise HTTPException(413,f'Fichier > {MAX_UPLOAD_MB} Mo')
    aid=uuid.uuid4(); pid=uuid.UUID(project_id) if project_id else None
    with db() as c: c.execute('insert into assets(id,project_id,name,content_type,size,role,kind,data) values(%s,%s,%s,%s,%s,%s,%s,%s)',(aid,pid,file.filename or 'video.mp4',file.content_type or 'video/mp4',len(data),role,'source',data))
    return {'id':str(aid),'name':file.filename,'size':len(data)}

@app.get('/api/assets/{asset_id}/download')
def download(asset_id:str,authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c: row=c.execute('select name,content_type,data from assets where id=%s',(uuid.UUID(asset_id),)).fetchone()
    if not row: raise HTTPException(404,'Introuvable')
    return Response(bytes(row[2]),media_type=row[1],headers={'Content-Disposition':f'inline; filename="{row[0]}"'})

class JobIn(BaseModel): projectId:str; assetIds:list[str]; variants:int=1; captions:bool=True; voiceover:str='auto'; autoRevision:bool=True
@app.post('/api/jobs')
def create_job(x:JobIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization); jid=uuid.uuid4(); settings={'assetIds':x.assetIds,'captions':x.captions,'voiceover':x.voiceover,'autoRevision':x.autoRevision}
    with db() as c: c.execute('insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,%s,%s,%s,%s,%s,%s)',(jid,uuid.UUID(x.projectId),'queued','queued',0,'En attente du worker',max(1,min(3,x.variants)),psycopg.types.json.Jsonb(settings)))
    r.lpush('auto_director:jobs',str(jid)); return {'id':str(jid),'status':'queued'}

@app.post('/api/feedback/{asset_id}')
def feedback(asset_id:str,views:int=0,likes:int=0,comments:int=0,shares:int=0,completion:float=0,conversions:int=0,revenue:float=0,authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c: c.execute('insert into feedback(id,asset_id,views,likes,comments,shares,completion,conversions,revenue) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(uuid.uuid4(),uuid.UUID(asset_id),views,likes,comments,shares,completion,conversions,revenue))
    return {'ok':True}

INDEX_HTML='''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Auto Director Studio</title><style>body{margin:0;background:#070914;color:#eef0ff;font-family:Inter,system-ui}.wrap{max-width:1180px;margin:auto;padding:28px}.card{background:#0e1224;border:1px solid #252b4a;border-radius:16px;padding:18px;margin:12px 0}button,input,select{background:#171c36;color:#fff;border:1px solid #30385e;border-radius:10px;padding:10px}.primary{background:#633cff}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.muted{color:#8f96bc}.bar{height:7px;background:#222843;border-radius:10px}.bar i{display:block;height:100%;background:#7147ff;border-radius:10px}.item{padding:10px;border-bottom:1px solid #222843}.ok{color:#34d399}@media(max-width:760px){.grid{grid-template-columns:1fr}}</style></head><body><div class="wrap"><h1>Auto Director Studio</h1><div id="login" class="card"><h2>Connexion</h2><input id="pw" type="password" placeholder="Mot de passe"><button class="primary" onclick="login()">Entrer</button><p id="err"></p></div><div id="app" style="display:none"><div class="card"><span id="health">Connexion...</span><button onclick="load()">Actualiser</button></div><div class="grid"><div class="card"><h2>Projet</h2><input id="pname" placeholder="Nom du projet"><button onclick="createProject()">Créer</button><select id="project"></select></div><div class="card"><h2>Importer des clips</h2><input id="files" type="file" accept="video/*" multiple><button onclick="upload()">Importer</button><p class="muted">Les clips Medal MP4 sont acceptés. 60 Mo max par fichier sur cette phase.</p></div></div><div class="card"><h2>Rushs</h2><button onclick="selectAll()">Tout sélectionner</button><div id="assets"></div></div><div class="card"><h2>Créer</h2><label>Variantes <select id="variants"><option>1</option><option>2</option><option>3</option></select></label> <button class="primary" onclick="job()">Lancer le bot complet</button></div><div class="card"><h2>Pipeline</h2><div id="jobs"></div></div></div></div><script>let token=localStorage.t||'',data={projects:[],assets:[],jobs:[]},sel=new Set();const H=()=>({'Authorization':'Bearer '+token});async function req(u,o={}){o.headers={...(o.headers||{}),...H()};let r=await fetch(u,o);if(!r.ok)throw Error(await r.text());return r.json()}async function login(){try{let r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw.value})});if(!r.ok)throw Error('Connexion refusée');token=(await r.json()).token;localStorage.t=token;show();load()}catch(e){err.textContent=e.message}}function show(){login.style.display='none';app.style.display='block'}async function load(){try{data=await req('/api/dashboard');project.innerHTML=data.projects.map(p=>`<option value="${p.id}">${p.name}</option>`).join('');assets.innerHTML=data.assets.filter(a=>a.kind==='source').map(a=>`<div class=item><input type=checkbox ${sel.has(a.id)?'checked':''} onchange="toggle('${a.id}',this.checked)"> ${a.name} <span class=muted>${(a.size/1048576).toFixed(1)} Mo</span></div>`).join('');jobs.innerHTML=data.jobs.map(j=>`<div class=item><b>${j.status}</b> · ${j.stage} · ${j.progress}%<div class=bar><i style="width:${j.progress}%"></i></div><span class=muted>${j.message}</span></div>`).join('');let h=await fetch('/health').then(r=>r.json());health.textContent=h.ok?'Services en ligne':'Services dégradés';health.className=h.ok?'ok':''}catch(e){health.textContent=e.message}}async function createProject(){await req('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:pname.value})});pname.value='';load()}async function upload(){if(!project.value)return alert('Crée un projet');for(const f of files.files){let fd=new FormData();fd.append('file',f);fd.append('project_id',project.value);await req('/api/assets',{method:'POST',body:fd})}files.value='';load()}function toggle(id,v){v?sel.add(id):sel.delete(id)}function selectAll(){data.assets.filter(a=>a.kind==='source').forEach(a=>sel.add(a.id));load()}async function job(){let ids=[...sel];if(!ids.length)ids=data.assets.filter(a=>a.kind==='source'&&a.projectId===project.value).map(a=>a.id);if(!ids.length)return alert('Aucun rush');await req('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({projectId:project.value,assetIds:ids,variants:+variants.value})});load()}if(token){show();load();setInterval(load,5000)}</script></body></html>'''
