# -*- coding: utf-8 -*-
"""V9 Studio API additions kept separate from legacy-compatible internals."""
from typing import Optional
import uuid

from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

DIRECTOR_MODES={"auto","story","funny","highlight","fast","clean"}
EDIT_INTENSITIES={"soft","balanced","aggressive"}
HOOK_STYLES={"auto","curiosity","payoff","direct"}
VISUAL_STYLES={"auto","viral","cinematic","kinetic","clean","retro","glitch","meme","dreamy"}

class V9JobIn(BaseModel):
    projectId:str
    assetIds:list[str]
    variants:int=Field(default=2,ge=1,le=3)
    captions:bool=True
    voiceover:str="auto"
    autoRevision:bool=True
    targetDuration:int=Field(default=18,ge=8,le=35)
    directorMode:str="auto"
    editIntensity:str="balanced"
    hookStyle:str="auto"
    visualStyle:str="auto"


def attach(app):
    try:
        from . import main as main_module
        main_module.APP_VERSION='11.0.0';main_module.ENGINE_VERSION='9.2';app.version='11.0.0'
    except Exception:
        pass

    app.router.routes[:]=[
        route for route in app.router.routes
        if not (getattr(route,'path',None)=='/api/jobs' and 'POST' in (getattr(route,'methods',set()) or set()))
    ]

    @app.get('/api/v9/meta',include_in_schema=False)
    def meta(authorization:Optional[str]=Header(None)):
        from .main import require_auth
        require_auth(authorization)
        return {
            'version':'11.0.0','engine':'director-v9.2-style',
            'directorModes':sorted(DIRECTOR_MODES),
            'editIntensities':sorted(EDIT_INTENSITIES),
            'hookStyles':sorted(HOOK_STYLES),
            'visualStyles':sorted(VISUAL_STYLES),
            'qualityEngine':True,'styleEngine':True,
        }

    def _create(x:V9JobIn,authorization:Optional[str]):
        from .main import require_auth,parse_uuid,db,queue,QUEUE_KEY
        require_auth(authorization)
        pid=parse_uuid(x.projectId,'Projet')
        raw_ids=list(dict.fromkeys(str(a) for a in x.assetIds))[:30]
        if not raw_ids:raise HTTPException(400,'Sélectionne au moins un rush')
        ids=[parse_uuid(a,'Rush') for a in raw_ids]
        mode=x.directorMode if x.directorMode in DIRECTOR_MODES else 'auto'
        intensity=x.editIntensity if x.editIntensity in EDIT_INTENSITIES else 'balanced'
        hook=x.hookStyle if x.hookStyle in HOOK_STYLES else 'auto'
        visual=x.visualStyle if x.visualStyle in VISUAL_STYLES else 'auto'
        voice=x.voiceover if x.voiceover in {'auto','on','off'} else 'auto'
        jid=uuid.uuid4()
        with db() as c:
            if not c.execute('select 1 from projects where id=%s',(pid,)).fetchone():raise HTTPException(404,'Projet introuvable')
            valid=c.execute("select id from assets where project_id=%s and id=any(%s) and kind='source' and role in ('source','broll','talking_head')",(pid,ids)).fetchall()
            if len(valid)!=len(ids):raise HTTPException(400,'La sélection contient une référence ou un rush invalide')
            settings={
                'assetIds':[str(a) for a in ids],
                'captions':bool(x.captions),'voiceover':voice,'autoRevision':bool(x.autoRevision),
                'targetDuration':max(8,min(35,int(x.targetDuration))),
                'directorMode':mode,'editIntensity':intensity,'hookStyle':hook,'visualStyle':visual,'studioVersion':'11.0.0',
            }
            c.execute("insert into jobs(id,project_id,status,stage,progress,message,variants,settings) values(%s,%s,'queued','queued',0,%s,%s,%s)",(jid,pid,'V9.2 Style accepté · en attente du worker',max(1,min(3,int(x.variants))),Jsonb(settings)))
            c.execute("insert into job_events(job_id,stage,message) values(%s,'queued',%s)",(jid,f'Job V9.2 créé · mode {mode} · style {visual} · intensité {intensity}'))
        signalled=False
        try:queue.lpush(QUEUE_KEY,str(jid));signalled=True
        except Exception:pass
        return {'id':str(jid),'status':'queued','version':'11.0.0','directorMode':mode,'visualStyle':visual,'queueSignalled':signalled}

    @app.post('/api/jobs',include_in_schema=False)
    def create_job(x:V9JobIn,authorization:Optional[str]=Header(None)):
        return _create(x,authorization)

    @app.post('/api/v9/jobs',include_in_schema=False)
    def create_v9_job(x:V9JobIn,authorization:Optional[str]=Header(None)):
        return _create(x,authorization)
