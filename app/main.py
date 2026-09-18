import hashlib
import hmac
import os
import secrets
import uuid
from typing import Optional

import psycopg
import redis
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from psycopg.types.json import Jsonb

DATABASE_URL=os.environ["DATABASE_URL"]
REDIS_URL=os.environ["REDIS_URL"]
STUDIO_PASSWORD=os.environ.get("STUDIO_PASSWORD","change-me-now")
TOKEN_SECRET=os.environ.get("TOKEN_SECRET",secrets.token_hex(32))
MAX_UPLOAD_MB=int(os.environ.get("MAX_UPLOAD_MB","80"))
ALLOWED_EXT={".mp4",".mov",".webm",".mkv",".avi",".m4v"}
app=FastAPI(title="Auto Director Studio",version="7.0")
queue=redis.from_url(REDIS_URL,decode_responses=True)

def db(): return psycopg.connect(DATABASE_URL)
def sign(v:str)->str: return hmac.new(TOKEN_SECRET.encode(),v.encode(),hashlib.sha256).hexdigest()
def make_token()->str:
    raw=secrets.token_urlsafe(32)
    return raw+"."+sign(raw)
def require_auth(authorization:Optional[str]):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Non autorisé")
    token=authorization[7:];parts=token.rsplit(".",1)
    if len(parts)!=2 or not hmac.compare_digest(sign(parts[0]),parts[1]): raise HTTPException(401,"Session invalide")

def init_db():
    with db() as c:
        c.execute("""create table if not exists projects(id uuid primary key,name text not null,created_at timestamptz not null default now());
        create table if not exists assets(id uuid primary key,project_id uuid references projects(id) on delete set null,name text not null,content_type text not null,size bigint not null,role text not null default 'source',kind text not null default 'source',data bytea not null,metadata jsonb not null default '{}'::jsonb,created_at timestamptz not null default now());
        create table if not exists jobs(id uuid primary key,project_id uuid references projects(id) on delete cascade,status text not null,stage text not null default 'queued',progress int not null default 0,message text not null default '',variants int not null default 1,settings jsonb not null default '{}'::jsonb,output_asset_ids uuid[] not null default '{}',critic_score double precision not null default 0,revision_count int not null default 0,strategy text not null default '',created_at timestamptz not null default now(),updated_at timestamptz not null default now());
        create table if not exists feedback(id uuid primary key,asset_id uuid references assets(id) on delete cascade,views bigint default 0,likes bigint default 0,comments bigint default 0,shares bigint default 0,completion double precision default 0,conversions bigint default 0,revenue double precision default 0,created_at timestamptz not null default now());
        create table if not exists trends(id uuid primary key,project_id uuid references projects(id) on delete cascade,label text not null,url text not null default '',notes text not null default '',created_at timestamptz not null default now());
        alter table assets add column if not exists metadata jsonb not null default '{}'::jsonb;
        alter table jobs add column if not exists critic_score double precision not null default 0;
        alter table jobs add column if not exists revision_count int not null default 0;
        alter table jobs add column if not exists strategy text not null default '';""")

@app.on_event("startup")
def startup(): init_db()

@app.get("/health")
def health():
    ok_db=ok_queue=False
    try:
        with db() as c:c.execute("select 1")
        ok_db=True
    except Exception: pass
    try:ok_queue=bool(queue.ping())
    except Exception:pass
    return {"ok":ok_db and ok_queue,"database":ok_db,"queue":ok_queue,"version":"7.0","storage":"postgres-temporary"}

@app.get("/",response_class=HTMLResponse)
def index(): return HTMLResponse(INDEX_HTML)

class LoginIn(BaseModel): password:str
@app.post("/api/login")
def login(x:LoginIn):
    if not hmac.compare_digest(x.password,STUDIO_PASSWORD): raise HTTPException(401,"Mot de passe incorrect")
    return {"token":make_token()}

def sv(v):
    if isinstance(v,uuid.UUID):return str(v)
    if isinstance(v,list):return [str(x) if isinstance(x,uuid.UUID) else x for x in v]
    if hasattr(v,"isoformat"):return v.isoformat()
    return v
def ser(row,keys):return {k:sv(v) for k,v in zip(keys,row)}

@app.get("/api/dashboard")
def dashboard(authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c:
        projects=c.execute("select id,name,created_at from projects order by created_at desc").fetchall()
        assets=c.execute("select id,project_id,name,content_type,size,role,kind,metadata,created_at from assets order by created_at desc limit 400").fetchall()
        jobs=c.execute("select id,project_id,status,stage,progress,message,variants,output_asset_ids,critic_score,revision_count,strategy,created_at,updated_at from jobs order by created_at desc limit 150").fetchall()
    return {"projects":[ser(x,["id","name","createdAt"]) for x in projects],"assets":[ser(x,["id","projectId","name","contentType","size","role","kind","metadata","createdAt"]) for x in assets],"jobs":[ser(x,["id","projectId","status","stage","progress","message","variants","outputAssetIds","criticScore","revisionCount","strategy","createdAt","updatedAt"]) for x in jobs]}

class ProjectIn(BaseModel):name:str
@app.post("/api/projects")
def create_project(x:ProjectIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization);name=x.name.strip()[:120] or "Projet";pid=uuid.uuid4()
    with db() as c:c.execute("insert into projects(id,name) values(%s,%s)",(pid,name))
    return {"id":str(pid),"name":name}

@app.post("/api/assets")
async def upload_asset(file:UploadFile=File(...),project_id:Optional[str]=Form(None),role:str=Form("source"),authorization:Optional[str]=Header(None)):
    require_auth(authorization);filename=file.filename or "video.mp4";ext=os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXT:raise HTTPException(415,"Format vidéo non pris en charge")
    role="reference" if role=="reference" else "source";data=await file.read((MAX_UPLOAD_MB+1)*1024*1024)
    if len(data)>MAX_UPLOAD_MB*1024*1024:raise HTTPException(413,f"Fichier > {MAX_UPLOAD_MB} Mo")
    aid=uuid.uuid4();pid=uuid.UUID(project_id) if project_id else None;meta={"medal":"medal" in filename.lower(),"extension":ext}
    with db() as c:c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,%s,%s,%s,'source',%s,%s)",(aid,pid,filename,file.content_type or "video/mp4",len(data),role,data,Jsonb(meta)))
    return {"id":str(aid),"name":filename,"size":len(data),"role":role}

class RoleIn(BaseModel):role:str
@app.post("/api/assets/{asset_id}/role")
def set_role(asset_id:str,x:RoleIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization);role="reference" if x.role=="reference" else "source"
    with db() as c:c.execute("update assets set role=%s where id=%s",(role,uuid.UUID(asset_id)))
    return {"ok":True,"role":role}

@app.delete("/api/assets/{asset_id}")
def delete_asset(asset_id:str,authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c:
        if not c.execute("select 1 from assets where id=%s",(uuid.UUID(asset_id),)).fetchone():raise HTTPException(404,"Introuvable")
        c.execute("delete from assets where id=%s",(uuid.UUID(asset_id),))
    return {"ok":True}

@app.get("/api/assets/{asset_id}/download")
def download(asset_id:str,authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c:row=c.execute("select name,content_type,data from assets where id=%s",(uuid.UUID(asset_id),)).fetchone()
    if not row:raise HTTPException(404,"Introuvable")
    return Response(bytes(row[2]),media_type=row[1],headers={"Content-Disposition":f'inline; filename="{row[0].replace(chr(34),"_")}"'})

class JobIn(BaseModel):
    projectId:str;assetIds:list[str];variants:int=1;captions:bool=True;voiceover:str="auto";autoRevision:bool=True;targetDuration:int=18
@app.post("/api/jobs")
def create_job(x:JobIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization);pid=uuid.UUID(x.projectId)
    with db() as c:
        if not c.execute("select 1 from projects where id=%s",(pid,)).fetchone():raise HTTPException(404,"Projet introuvable")
        if x.assetIds:
            rows=c.execute("select id,role from assets where id=any(%s) and project_id=%s",([uuid.UUID(v) for v in x.assetIds],pid)).fetchall();source_ids=[str(a) for a,role in rows if role=="source"]
        else:
            rows=c.execute("select id from assets where project_id=%s and role='source' and kind='source'",(pid,)).fetchall();source_ids=[str(v[0]) for v in rows]
    if not source_ids:raise HTTPException(400,"Aucun rush source")
    jid=uuid.uuid4();settings={"assetIds":source_ids,"captions":x.captions,"voiceover":x.voiceover if x.voiceover in {"auto","off"} else "auto","autoRevision":x.autoRevision,"targetDuration":max(8,min(30,x.targetDuration))}
    with db() as c:c.execute("insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,'En attente du worker',%s,%s)",(jid,pid,max(1,min(3,x.variants)),Jsonb(settings)))
    queue.lpush("auto_director:jobs",str(jid));return {"id":str(jid),"status":"queued"}

@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id:str,authorization:Optional[str]=Header(None)):
    require_auth(authorization);jid=uuid.UUID(job_id)
    with db() as c:
        row=c.execute("select status from jobs where id=%s",(jid,)).fetchone()
        if not row:raise HTTPException(404,"Job introuvable")
        c.execute("update jobs set status='cancelled',stage='cancelled',message='Annulé',updated_at=now() where id=%s",(jid,))
    queue.lrem("auto_director:jobs",0,str(jid));return {"ok":True,"status":"cancelled"}

@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id:str,authorization:Optional[str]=Header(None)):
    require_auth(authorization);jid=uuid.UUID(job_id)
    with db() as c:
        if not c.execute("select 1 from jobs where id=%s",(jid,)).fetchone():raise HTTPException(404,"Job introuvable")
        c.execute("update jobs set status='queued',stage='queued',progress=0,message='Relancé',updated_at=now() where id=%s",(jid,))
    queue.lpush("auto_director:jobs",str(jid));return {"ok":True}

class FeedbackIn(BaseModel):
    views:int=0;likes:int=0;comments:int=0;shares:int=0;completion:float=0;conversions:int=0;revenue:float=0
@app.post("/api/feedback/{asset_id}")
def feedback(asset_id:str,x:FeedbackIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization);aid=uuid.UUID(asset_id)
    with db() as c:
        if not c.execute("select 1 from assets where id=%s and kind='render'",(aid,)).fetchone():raise HTTPException(404,"Rendu introuvable")
        c.execute("insert into feedback(id,asset_id,views,likes,comments,shares,completion,conversions,revenue) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)",(uuid.uuid4(),aid,max(0,x.views),max(0,x.likes),max(0,x.comments),max(0,x.shares),max(0,min(1,x.completion)),max(0,x.conversions),max(0,x.revenue)))
    return {"ok":True}

@app.get("/api/learning")
def learning(authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c:rows=c.execute("select a.id,a.name,a.metadata,coalesce(sum(f.views),0),coalesce(sum(f.likes),0),coalesce(sum(f.shares),0),coalesce(avg(f.completion),0),coalesce(sum(f.conversions),0),coalesce(sum(f.revenue),0) from assets a left join feedback f on f.asset_id=a.id where a.kind='render' group by a.id,a.name,a.metadata order by coalesce(sum(f.views),0) desc limit 100").fetchall()
    return {"items":[{"assetId":str(r[0]),"name":r[1],"metadata":r[2],"views":int(r[3]),"likes":int(r[4]),"shares":int(r[5]),"completion":float(r[6]),"conversions":int(r[7]),"revenue":float(r[8])} for r in rows]}

class TrendIn(BaseModel):projectId:str;label:str;url:str="";notes:str=""
@app.post("/api/trends")
def add_trend(x:TrendIn,authorization:Optional[str]=Header(None)):
    require_auth(authorization);tid=uuid.uuid4()
    with db() as c:c.execute("insert into trends(id,project_id,label,url,notes) values(%s,%s,%s,%s,%s)",(tid,uuid.UUID(x.projectId),x.label.strip()[:160],x.url.strip()[:500],x.notes.strip()[:2000]))
    return {"id":str(tid)}
@app.get("/api/trends/{project_id}")
def get_trends(project_id:str,authorization:Optional[str]=Header(None)):
    require_auth(authorization)
    with db() as c:rows=c.execute("select id,label,url,notes,created_at from trends where project_id=%s order by created_at desc limit 50",(uuid.UUID(project_id),)).fetchall()
    return {"items":[{"id":str(x[0]),"label":x[1],"url":x[2],"notes":x[3],"createdAt":x[4].isoformat()} for x in rows]}

INDEX_HTML = '<!doctype html>\n<html lang="fr">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>Auto Director Studio</title>\n<style>\n:root{font-family:Inter,ui-sans-serif,system-ui;background:#070914;color:#eef0ff}\n*{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at 15% 0,#2a195e55,transparent 32%),#070914}\nbutton,input,select,textarea{font:inherit}\nbutton{cursor:pointer}\n.wrap{max-width:1220px;margin:auto;padding:26px 18px 80px}\nheader{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}\nh1,h2,h3,p{margin:0} h1{font-size:30px} h2{font-size:19px}\n.muted{color:#8d94ba}.small{font-size:12px}.ok{color:#37e0a1}.warn{color:#f6c85f}.bad{color:#ff7b8c}\n.card{background:#0d1122d9;border:1px solid #242b4d;border-radius:17px;padding:17px;margin:12px 0;box-shadow:0 20px 55px #0003}\n.grid{display:grid;grid-template-columns:1fr 1fr;gap:13px}\n.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}\n.stat{padding:14px;border-radius:14px;background:#11162a;border:1px solid #242b4d}.stat b{display:block;font-size:24px;margin-top:6px}\n.tabs{display:flex;gap:7px;flex-wrap:wrap;margin:15px 0}\n.tab,.ghost,.secondary,.primary,.danger{border:1px solid #2b3358;color:#eef0ff;background:#141a32;border-radius:10px;padding:10px 13px}\n.tab.active,.primary{background:linear-gradient(135deg,#7c3aed,#4f46e5);border-color:transparent;font-weight:750}\n.danger{color:#ff9aaa}.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}.grow{flex:1}\ninput,select,textarea{background:#10152b;color:#eef0ff;border:1px solid #2c3459;border-radius:10px;padding:10px;min-width:0}\ntextarea{width:100%;min-height:84px}\n.drop{border:1px dashed #4d5688;border-radius:16px;padding:25px;text-align:center;background:#11162a;transition:.2s}\n.drop.over{border-color:#8b5cf6;background:#21194a}\n.list{display:grid;gap:8px;margin-top:12px;max-height:420px;overflow:auto}\n.item{border:1px solid #242b4d;background:#10152a;border-radius:12px;padding:11px;display:flex;align-items:center;gap:10px}\n.item .meta{min-width:0;flex:1}.item strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.badge{display:inline-flex;border:1px solid #313960;background:#181e39;border-radius:999px;padding:4px 8px;font-size:11px}\n.bar{height:7px;background:#252b49;border-radius:20px;overflow:hidden;margin:8px 0}.bar i{height:100%;display:block;background:linear-gradient(90deg,#7c3aed,#4f46e5)}\n.gallery{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.tile{border:1px solid #242b4d;border-radius:14px;padding:12px;background:#10152a}\nvideo{width:100%;border-radius:10px;background:#000;aspect-ratio:9/16;max-height:420px}\n.progressbox{margin:10px 0}.uploadline{display:flex;justify-content:space-between;gap:10px;font-size:12px;margin:5px 0}\n.hidden{display:none!important}.login{max-width:460px;margin:12vh auto}.notice{border:1px solid #6f5418;background:#2c230c;color:#ffe08b;border-radius:12px;padding:11px;margin:10px 0}\n@media(max-width:850px){.grid,.gallery{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}header{align-items:flex-start}.row.mobile-col{align-items:stretch;flex-direction:column}}\n</style>\n</head>\n<body>\n<div id="loginView" class="wrap login">\n  <div class="card">\n    <h1>Auto Director Studio</h1>\n    <p class="muted" style="margin:8px 0 18px">Studio privé de création vidéo automatisée.</p>\n    <div class="row"><input class="grow" id="pw" type="password" placeholder="Mot de passe"><button class="primary" onclick="login()">Entrer</button></div>\n    <p id="loginErr" class="bad small" style="margin-top:10px"></p>\n  </div>\n</div>\n<div id="appView" class="wrap hidden">\n<header>\n  <div><div class="small muted">AUTO DIRECTOR · RENDER</div><h1>Studio de création</h1></div>\n  <div class="row"><span id="healthText" class="muted">Connexion…</span><button class="ghost" onclick="loadDashboard()">Actualiser</button><button class="ghost" onclick="logout()">Déconnexion</button></div>\n</header>\n<div id="notice"></div>\n<div class="stats">\n <div class="stat"><span class="muted small">Rushs</span><b id="sSources">0</b></div>\n <div class="stat"><span class="muted small">Références</span><b id="sRefs">0</b></div>\n <div class="stat"><span class="muted small">Rendus</span><b id="sRenders">0</b></div>\n <div class="stat"><span class="muted small">Jobs actifs</span><b id="sJobs">0</b></div>\n</div>\n<div class="tabs">\n <button class="tab active" data-tab="studio" onclick="showTab(\'studio\')">Studio</button>\n <button class="tab" data-tab="pipeline" onclick="showTab(\'pipeline\')">Pipeline</button>\n <button class="tab" data-tab="gallery" onclick="showTab(\'gallery\')">Galerie</button>\n <button class="tab" data-tab="learning" onclick="showTab(\'learning\')">Learning</button>\n <button class="tab" data-tab="trends" onclick="showTab(\'trends\')">Références / Trends</button>\n</div>\n<section id="tab-studio">\n <div class="grid">\n  <div class="card">\n   <h2>1 · Projet</h2><br>\n   <div class="row"><input class="grow" id="projectName" placeholder="Ex. Garry\'s Mod DarkRP RiverSide"><button class="secondary" onclick="createProject()">Créer</button></div>\n   <select id="projectSelect" style="width:100%;margin-top:10px" onchange="projectChanged()"></select>\n  </div>\n  <div class="card">\n   <h2>2 · Import</h2><br>\n   <div id="drop" class="drop">\n    <strong>Glisse tes clips Medal, vidéos ou dossiers ici</strong>\n    <p class="muted small" style="margin:8px">MP4 / MOV / WebM / MKV / AVI / M4V · max __MAX__ Mo / fichier</p>\n    <div class="row" style="justify-content:center">\n      <button class="secondary" onclick="filePicker.click()">Choisir des fichiers</button>\n      <button class="secondary" onclick="folderPicker.click()">Choisir un dossier</button>\n    </div>\n    <input id="filePicker" class="hidden" type="file" accept="video/*,.mkv,.avi,.m4v" multiple>\n    <input id="folderPicker" class="hidden" type="file" webkitdirectory multiple>\n   </div>\n   <div class="row" style="margin-top:10px"><label class="small muted">Importer comme</label><select id="uploadRole"><option value="source">Rush source</option><option value="reference">Référence de style</option></select></div>\n   <div id="uploadQueue"></div>\n  </div>\n </div>\n <div class="card">\n  <div class="row"><h2 class="grow">3 · Rushs et références</h2><button class="ghost" onclick="selectAllSources()">Sélectionner tous les rushs</button><button class="ghost" onclick="selected.clear();renderAssets()">Vider la sélection</button></div>\n  <div id="assetList" class="list"></div>\n </div>\n <div class="card">\n  <h2>4 · Direction & rendu</h2><br>\n  <div class="row mobile-col">\n   <label>Variantes <select id="variants"><option>1</option><option>2</option><option>3</option></select></label>\n   <label>Durée cible <select id="duration"><option value="12">12 s</option><option value="15">15 s</option><option value="18" selected>18 s</option><option value="22">22 s</option><option value="28">28 s</option></select></label>\n   <label><input type="checkbox" id="captions" checked> Hook / texte</label>\n   <label>Voix off <select id="voiceover"><option value="auto">Auto</option><option value="off">Off</option></select></label>\n   <label><input type="checkbox" id="revision" checked> Auto-révision</label>\n  </div>\n  <p id="selectionInfo" class="muted small" style="margin:12px 0">0 rush sélectionné</p>\n  <button class="primary" onclick="createJob()">Lancer le bot complet</button>\n </div>\n</section>\n<section id="tab-pipeline" class="hidden">\n <div class="card"><div class="row"><h2 class="grow">Pipeline</h2><button class="ghost" onclick="loadDashboard()">Actualiser</button></div><div id="jobList" class="list"></div></div>\n</section>\n<section id="tab-gallery" class="hidden">\n <div class="card"><div class="row"><h2 class="grow">Galerie finale</h2><span class="muted small">Prévisualisation privée via session</span></div><div id="gallery" class="gallery" style="margin-top:12px"></div></div>\n</section>\n<section id="tab-learning" class="hidden">\n <div class="card"><h2>Mémoire de performance</h2><p class="muted small" style="margin:7px 0 15px">Ajoute les performances réelles pour comparer les formats.</p><div id="learningList" class="list"></div></div>\n</section>\n<section id="tab-trends" class="hidden">\n <div class="grid">\n  <div class="card"><h2>Ajouter une tendance / idée</h2><br><input id="trendLabel" style="width:100%" placeholder="Ex. reveal rapide / challenge / moment drôle"><input id="trendUrl" style="width:100%;margin-top:8px" placeholder="Lien de référence (optionnel)"><textarea id="trendNotes" style="margin-top:8px" placeholder="Ce qu\'il faut retenir du rythme, hook, reveal…"></textarea><button class="primary" style="margin-top:8px" onclick="addTrend()">Ajouter</button></div>\n  <div class="card"><h2>Références du projet</h2><div id="trendList" class="list"></div></div>\n </div>\n</section>\n</div>\n<script>\nlet token=localStorage.getItem(\'autoDirectorToken\')||\'\';\nlet data={projects:[],assets:[],jobs:[]};\nlet selected=new Set();\nconst $=id=>document.getElementById(id);\nconst authHeaders=()=>({\'Authorization\':\'Bearer \'+token});\nasync function api(url,opts={}){\n  opts.headers={...(opts.headers||{}),...authHeaders()};\n  const res=await fetch(url,opts);\n  if(res.status===401){logout();throw Error(\'Session expirée\');}\n  if(!res.ok){let t=await res.text();try{t=JSON.parse(t).detail||t}catch{}throw Error(t)}\n  const ct=res.headers.get(\'content-type\')||\'\';\n  return ct.includes(\'application/json\')?res.json():res;\n}\nasync function login(){\n  $(\'loginErr\').textContent=\'\';\n  try{\n    const r=await fetch(\'/api/login\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({password:$(\'pw\').value})});\n    if(!r.ok)throw Error(\'Mot de passe incorrect\');\n    token=(await r.json()).token;localStorage.setItem(\'autoDirectorToken\',token);showApp();await loadDashboard();\n  }catch(e){$(\'loginErr\').textContent=e.message}\n}\nfunction logout(){localStorage.removeItem(\'autoDirectorToken\');token=\'\';$(\'appView\').classList.add(\'hidden\');$(\'loginView\').classList.remove(\'hidden\')}\nfunction showApp(){$(\'loginView\').classList.add(\'hidden\');$(\'appView\').classList.remove(\'hidden\')}\nfunction showTab(name){\n document.querySelectorAll(\'[id^="tab-"]\').forEach(x=>x.classList.add(\'hidden\'));\n $(\'tab-\'+name).classList.remove(\'hidden\');\n document.querySelectorAll(\'.tab\').forEach(x=>x.classList.toggle(\'active\',x.dataset.tab===name));\n if(name===\'learning\')loadLearning();if(name===\'trends\')loadTrends();\n}\nfunction currentProject(){return $(\'projectSelect\').value}\nasync function loadDashboard(){\n try{\n   const [d,h]=await Promise.all([api(\'/api/dashboard\'),fetch(\'/health\').then(r=>r.json())]);\n   data=d;\n   $(\'healthText\').textContent=h.ok?\'API · DB · Queue en ligne\':\'Services dégradés\';\n   $(\'healthText\').className=h.ok?\'ok small\':\'bad small\';\n   $(\'notice\').innerHTML=h.storage===\'postgres-temporary\'?\'<div class="notice">Phase actuelle : petits/moyens clips stockés dans Postgres. Pour du gros volume Medal, on branchera ensuite un stockage objet S3/R2.</div>\':\'\';\n   const old=currentProject();\n   $(\'projectSelect\').innerHTML=data.projects.map(p=>`<option value="${p.id}">${escapeHtml(p.name)}</option>`).join(\'\');\n   if(old&&data.projects.some(p=>p.id===old))$(\'projectSelect\').value=old;\n   updateStats();renderAssets();renderJobs();renderGallery();\n }catch(e){$(\'healthText\').textContent=e.message;$(\'healthText\').className=\'bad small\'}\n}\nfunction updateStats(){\n const pid=currentProject();const a=data.assets.filter(x=>!pid||x.projectId===pid);\n $(\'sSources\').textContent=a.filter(x=>x.kind===\'source\'&&x.role===\'source\').length;\n $(\'sRefs\').textContent=a.filter(x=>x.kind===\'source\'&&x.role===\'reference\').length;\n $(\'sRenders\').textContent=a.filter(x=>x.kind===\'render\').length;\n $(\'sJobs\').textContent=data.jobs.filter(x=>(!pid||x.projectId===pid)&&[\'queued\',\'running\'].includes(x.status)).length;\n}\nfunction projectChanged(){selected.clear();updateStats();renderAssets();renderJobs();renderGallery();loadTrends()}\nasync function createProject(){\n const name=$(\'projectName\').value.trim();if(!name)return alert(\'Donne un nom au projet\');\n const p=await api(\'/api/projects\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({name})});\n $(\'projectName\').value=\'\';await loadDashboard();$(\'projectSelect\').value=p.id;projectChanged();\n}\nfunction escapeHtml(s){return String(s||\'\').replace(/[&<>"\']/g,c=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'"\':\'&quot;\',"\'":\'&#039;\'}[c]))}\nfunction renderAssets(){\n const pid=currentProject();const list=data.assets.filter(a=>a.projectId===pid&&a.kind===\'source\');\n $(\'assetList\').innerHTML=list.length?list.map(a=>`<div class="item">\n   <input type="checkbox" ${selected.has(a.id)?\'checked\':\'\'} ${a.role===\'reference\'?\'disabled\':\'\'} onchange="toggleAsset(\'${a.id}\',this.checked)">\n   <div class="meta"><strong>${escapeHtml(a.name)}</strong><span class="muted small">${(a.size/1048576).toFixed(1)} Mo · ${a.metadata?.medal?\'Medal · \':\'\'}${a.role===\'reference\'?\'Référence\':\'Rush source\'}</span></div>\n   <select onchange="changeRole(\'${a.id}\',this.value)"><option value="source" ${a.role===\'source\'?\'selected\':\'\'}>Rush</option><option value="reference" ${a.role===\'reference\'?\'selected\':\'\'}>Référence</option></select>\n   <button class="danger" onclick="deleteAsset(\'${a.id}\')">Supprimer</button>\n </div>`).join(\'\'):\'<p class="muted">Aucun clip dans ce projet.</p>\';\n $(\'selectionInfo\').textContent=`${selected.size} rush(s) sélectionné(s) — si 0, tous les rushs source du projet seront utilisés.`;\n}\nfunction toggleAsset(id,on){on?selected.add(id):selected.delete(id);renderAssets()}\nfunction selectAllSources(){data.assets.filter(a=>a.projectId===currentProject()&&a.kind===\'source\'&&a.role===\'source\').forEach(a=>selected.add(a.id));renderAssets()}\nasync function changeRole(id,role){await api(\'/api/assets/\'+id+\'/role\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({role})});selected.delete(id);await loadDashboard()}\nasync function deleteAsset(id){if(!confirm(\'Supprimer ce clip ?\'))return;await api(\'/api/assets/\'+id,{method:\'DELETE\'});selected.delete(id);await loadDashboard()}\nfunction uploadXHR(file,role){\n return new Promise((resolve,reject)=>{\n   const key=\'u\'+Math.random().toString(36).slice(2);const box=document.createElement(\'div\');box.className=\'progressbox\';box.innerHTML=`<div class="uploadline"><span>${escapeHtml(file.name)}</span><span id="${key}t">0%</span></div><div class="bar"><i id="${key}b" style="width:0"></i></div>`;$(\'uploadQueue\').prepend(box);\n   const xhr=new XMLHttpRequest();xhr.open(\'POST\',\'/api/assets\');xhr.setRequestHeader(\'Authorization\',\'Bearer \'+token);\n   xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.round(e.loaded/e.total*100);$(key+\'t\').textContent=p+\'%\';$(key+\'b\').style.width=p+\'%\'}};\n   xhr.onload=()=>xhr.status>=200&&xhr.status<300?resolve():reject(Error(xhr.responseText||\'Upload impossible\'));\n   xhr.onerror=()=>reject(Error(\'Erreur réseau\'));\n   const fd=new FormData();fd.append(\'file\',file);fd.append(\'project_id\',currentProject());fd.append(\'role\',role);xhr.send(fd);\n });\n}\nasync function uploadFiles(files){\n if(!currentProject())return alert(\'Crée un projet\');\n const allowed=[\'.mp4\',\'.mov\',\'.webm\',\'.mkv\',\'.avi\',\'.m4v\'];const vids=[...files].filter(f=>allowed.some(x=>f.name.toLowerCase().endsWith(x)));\n if(!vids.length)return;\n for(const f of vids){try{await uploadXHR(f,$(\'uploadRole\').value)}catch(e){alert(f.name+\' : \'+e.message)}}\n await loadDashboard();\n}\n$(\'filePicker\').addEventListener(\'change\',e=>uploadFiles(e.target.files));\n$(\'folderPicker\').addEventListener(\'change\',e=>uploadFiles(e.target.files));\nconst drop=$(\'drop\');\n[\'dragenter\',\'dragover\'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add(\'over\')}));\n[\'dragleave\',\'drop\'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove(\'over\')}));\ndrop.addEventListener(\'drop\',async e=>{\n const out=[];const items=[...(e.dataTransfer.items||[])];\n async function walk(entry){if(entry.isFile)return new Promise(r=>entry.file(f=>{out.push(f);r()}));if(entry.isDirectory){const rd=entry.createReader();return new Promise(resolve=>{const read=()=>rd.readEntries(async ents=>{if(!ents.length)return resolve();for(const x of ents)await walk(x);read()});read()})}}\n if(items.length&&items[0].webkitGetAsEntry){for(const it of items){const en=it.webkitGetAsEntry();if(en)await walk(en)}await uploadFiles(out)}else await uploadFiles(e.dataTransfer.files);\n});\nasync function createJob(){\n if(!currentProject())return alert(\'Crée un projet\');\n const body={projectId:currentProject(),assetIds:[...selected],variants:+$(\'variants\').value,captions:$(\'captions\').checked,voiceover:$(\'voiceover\').value,autoRevision:$(\'revision\').checked,targetDuration:+$(\'duration\').value};\n try{await api(\'/api/jobs\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify(body)});showTab(\'pipeline\');await loadDashboard()}catch(e){alert(e.message)}\n}\nfunction renderJobs(){\n const pid=currentProject();const rows=data.jobs.filter(j=>j.projectId===pid);\n $(\'jobList\').innerHTML=rows.length?rows.map(j=>`<div class="item"><div class="meta"><div class="row"><b>${escapeHtml(j.status)}</b><span class="badge">${escapeHtml(j.stage)}</span><span class="muted small">${j.progress}%</span>${j.criticScore?`<span class="badge">Score ${Math.round(j.criticScore)}/100</span>`:\'\'}</div><div class="bar"><i style="width:${j.progress}%"></i></div><span class="muted small">${escapeHtml(j.message)} ${j.strategy?\'· \'+escapeHtml(j.strategy):\'\'}</span></div>${[\'queued\',\'running\'].includes(j.status)?`<button class="danger" onclick="cancelJob(\'${j.id}\')">Annuler</button>`:\'\'}${j.status===\'failed\'?`<button class="secondary" onclick="retryJob(\'${j.id}\')">Relancer</button>`:\'\'}</div>`).join(\'\'):\'<p class="muted">Aucun job.</p>\';\n}\nasync function cancelJob(id){await api(\'/api/jobs/\'+id+\'/cancel\',{method:\'POST\'});loadDashboard()}\nasync function retryJob(id){await api(\'/api/jobs/\'+id+\'/retry\',{method:\'POST\'});loadDashboard()}\nfunction renderGallery(){\n const pid=currentProject();const renders=data.assets.filter(a=>a.projectId===pid&&a.kind===\'render\');\n $(\'gallery\').innerHTML=renders.length?renders.map(a=>`<div class="tile"><div class="videoSlot" id="v_${a.id}"></div><h3 style="margin:8px 0 5px">${escapeHtml(a.name)}</h3><div class="row">${a.metadata?.score?`<span class="badge">Score ${Math.round(a.metadata.score)}/100</span>`:\'\'}${a.metadata?.strategy?`<span class="badge">${escapeHtml(a.metadata.strategy)}</span>`:\'\'}</div><div class="row" style="margin-top:9px"><button class="secondary" onclick="preview(\'${a.id}\')">Voir</button><button class="secondary" onclick="downloadAsset(\'${a.id}\',\'${encodeURIComponent(a.name)}\')">Télécharger</button></div></div>`).join(\'\'):\'<p class="muted">Aucun rendu final pour le moment.</p>\';\n}\nasync function getBlob(id){const r=await fetch(\'/api/assets/\'+id+\'/download\',{headers:authHeaders()});if(!r.ok)throw Error(await r.text());return r.blob()}\nasync function preview(id){const b=await getBlob(id);const url=URL.createObjectURL(b);$(\'v_\'+id).innerHTML=`<video controls playsinline src="${url}"></video>`}\nasync function downloadAsset(id,name){const b=await getBlob(id);const u=URL.createObjectURL(b);const a=document.createElement(\'a\');a.href=u;a.download=decodeURIComponent(name);a.click();setTimeout(()=>URL.revokeObjectURL(u),5000)}\nasync function loadLearning(){\n try{const x=await api(\'/api/learning\');$(\'learningList\').innerHTML=x.items.length?x.items.map(i=>`<div class="item"><div class="meta"><strong>${escapeHtml(i.name)}</strong><span class="muted small">${i.views} vues · ${i.likes} likes · ${i.shares} partages · completion ${(i.completion*100).toFixed(0)}% · ${i.conversions} conv. · ${i.revenue.toFixed(2)} €</span></div><button class="secondary" onclick="feedbackPrompt(\'${i.assetId}\')">Ajouter résultats</button></div>`).join(\'\'):\'<p class="muted">Publie un rendu puis ajoute ses résultats ici.</p>\'}catch(e){$(\'learningList\').textContent=e.message}\n}\nasync function feedbackPrompt(id){\n const views=+(prompt(\'Vues\',\'0\')||0),likes=+(prompt(\'Likes\',\'0\')||0),shares=+(prompt(\'Partages\',\'0\')||0),completion=+(prompt(\'Completion 0 à 1\',\'0\')||0),conversions=+(prompt(\'Conversions\',\'0\')||0),revenue=+(prompt(\'Revenu\',\'0\')||0);\n await api(\'/api/feedback/\'+id,{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({views,likes,shares,completion,conversions,revenue})});loadLearning();\n}\nasync function addTrend(){\n if(!currentProject())return alert(\'Choisis un projet\');\n await api(\'/api/trends\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({projectId:currentProject(),label:$(\'trendLabel\').value,url:$(\'trendUrl\').value,notes:$(\'trendNotes\').value})});\n $(\'trendLabel\').value=\'\';$(\'trendUrl\').value=\'\';$(\'trendNotes\').value=\'\';loadTrends();\n}\nasync function loadTrends(){\n if(!currentProject())return;\n try{const x=await api(\'/api/trends/\'+currentProject());$(\'trendList\').innerHTML=x.items.length?x.items.map(t=>`<div class="item"><div class="meta"><strong>${escapeHtml(t.label)}</strong><span class="muted small">${escapeHtml(t.notes||\'\')}${t.url?\' · \'+escapeHtml(t.url):\'\'}</span></div></div>`).join(\'\'):\'<p class="muted">Aucune tendance enregistrée.</p>\'}catch(e){$(\'trendList\').textContent=e.message}\n}\nif(token){showApp();loadDashboard();setInterval(()=>{if(!document.hidden)loadDashboard()},5000)}\n</script>\n</body></html>'.replace('__MAX__',str(MAX_UPLOAD_MB))
