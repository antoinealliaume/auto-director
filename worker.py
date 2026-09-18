import asyncio
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import psycopg
import redis
from edge_tts import Communicate
from imageio_ffmpeg import get_ffmpeg_exe
from psycopg.types.json import Jsonb

DATABASE_URL=os.environ["DATABASE_URL"]
REDIS_URL=os.environ["REDIS_URL"]
FFMPEG=get_ffmpeg_exe()
queue=redis.from_url(REDIS_URL,decode_responses=True)

def db(): return psycopg.connect(DATABASE_URL)

def run(cmd,timeout=900,check=True):
    p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
    if check and p.returncode!=0:
        raise RuntimeError((p.stderr or p.stdout or "")[-3500:])
    return p

def update(jid,status,stage,progress,message,score=None,revision=None,strategy=None):
    sets=["status=%s","stage=%s","progress=%s","message=%s","updated_at=now()"]
    vals=[status,stage,int(progress),str(message)[:500]]
    if score is not None:sets.append("critic_score=%s");vals.append(float(score))
    if revision is not None:sets.append("revision_count=%s");vals.append(int(revision))
    if strategy is not None:sets.append("strategy=%s");vals.append(strategy)
    vals.append(jid)
    with db() as c:c.execute("update jobs set "+",".join(sets)+" where id=%s",vals)

def media_info(path:Path):
    p=run([FFMPEG,"-hide_banner","-i",str(path)],timeout=45,check=False)
    text=p.stderr or ""
    m=re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)",text)
    duration=0.0
    if m:duration=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))
    has_audio="Audio:" in text
    return duration,has_audio

def scene_cuts(path:Path,max_seconds=35):
    p=run([FFMPEG,"-hide_banner","-t",str(max_seconds),"-i",str(path),"-vf","select='gt(scene,0.28)',showinfo","-an","-f","null","-"],timeout=180,check=False)
    vals=[float(x) for x in re.findall(r"pts_time:([0-9.]+)",p.stderr or "")]
    out=[]
    for x in vals:
        if x<0.6:continue
        if not out or x-out[-1]>=0.55:out.append(round(x,2))
        if len(out)>=16:break
    return out

def black_ratio(path:Path,duration:float):
    sample=min(max(duration,1.0),20.0)
    p=run([FFMPEG,"-hide_banner","-t",str(sample),"-i",str(path),"-vf","blackdetect=d=0.15:pix_th=0.08","-an","-f","null","-"],timeout=120,check=False)
    spans=re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)",p.stderr or "")
    black=sum(max(0,float(b)-float(a)) for a,b in spans)
    return min(1.0,black/max(sample,0.1))

def has_drawtext():
    try:return "drawtext" in run([FFMPEG,"-hide_banner","-filters"],timeout=30,check=False).stdout
    except Exception:return False
DRAWTEXT=has_drawtext()

def segment_filter(zoom:float,hook_file:Path|None,caption_file:Path|None):
    zw=max(720,int(round((720*zoom)/2)*2));zh=max(1280,int(round((1280*zoom)/2)*2))
    f=["scale=720:1280:force_original_aspect_ratio=increase","crop=720:1280",f"scale={zw}:{zh}","crop=720:1280","fps=30","setsar=1"]
    if DRAWTEXT and hook_file:
        f.append(f"drawtext=textfile='{hook_file.as_posix()}':fontcolor=white:fontsize=48:borderw=4:bordercolor=black:x=(w-text_w)/2:y=110:box=1:boxcolor=black@0.34:boxborderw=12")
    if DRAWTEXT and caption_file:
        f.append(f"drawtext=textfile='{caption_file.as_posix()}':fontcolor=white:fontsize=36:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h*0.76:box=1:boxcolor=black@0.28:boxborderw=10")
    return ",".join(f)

def make_segment(src:Path,out:Path,start:float,duration:float,zoom:float,hook:str="",caption:str=""):
    total,has_audio=media_info(src)
    if total>0:start=min(max(0,start),max(0,total-duration))
    hook_file=caption_file=None
    if hook:
        hook_file=out.with_suffix(".hook.txt");hook_file.write_text(hook,encoding="utf-8")
    if caption:
        caption_file=out.with_suffix(".cap.txt");caption_file.write_text(caption,encoding="utf-8")
    vf=segment_filter(zoom,hook_file,caption_file)
    cmd=[FFMPEG,"-y","-ss",str(max(0,start)),"-i",str(src)]
    if has_audio:
        cmd += ["-t",str(duration),"-vf",vf,"-map","0:v:0","-map","0:a:0","-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-ar","44100","-ac","2","-shortest",str(out)]
    else:
        cmd += ["-f","lavfi","-t",str(duration),"-i","anullsrc=channel_layout=stereo:sample_rate=44100","-t",str(duration),"-vf",vf,"-map","0:v:0","-map","1:a:0","-c:v","libx264","-preset","veryfast","-crf","23","-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-ar","44100","-ac","2","-shortest",str(out)]
    run(cmd,timeout=600)

def build_candidates(items):
    candidates=[]
    for item in items:
        points=[0.0]
        for cut in item["cuts"]:points.extend([max(0,cut-0.45),cut])
        d=item["duration"]
        if d>4:points += [d*0.22,d*0.48,d*0.72]
        seen=[]
        for p in points:
            q=round(max(0,p),2)
            if all(abs(q-x)>0.55 for x in seen):seen.append(q)
        item["starts"]=seen[:20]
        candidates.append(item)
    return candidates

def reference_pace(refs):
    intervals=[]
    for item in refs:
        cuts=item.get("cuts") or []
        prev=0.0
        for c in cuts[:10]:
            if c-prev>0.45:intervals.append(c-prev)
            prev=c
    if not intervals:return 2.35
    avg=sum(intervals)/len(intervals)
    return max(1.15,min(3.15,avg))

def hooks(project_name):
    clean=(project_name or "ce moment")[:55]
    return [f"Attends de voir ce qui se passe sur {clean}…","Je ne pensais pas que ça allait finir comme ça…","Regarde bien les prochaines secondes."]

def make_plan(project_name,sources,refs,variant,target,revision=0):
    pace=reference_pace(refs)
    if revision:pace=max(1.15,pace*0.82)
    pace=max(1.15,min(3.4,pace));target=max(8,min(30,target));needed=max(3,min(12,math.ceil(target/pace)))
    order=sources[variant%len(sources):]+sources[:variant%len(sources)];segs=[];cursor=variant
    for i in range(needed):
        item=order[i%len(order)];starts=item.get("starts") or [0.0];start=starts[(cursor+i*2)%len(starts)]
        duration=min(pace,max(1.1,target-sum(s["duration"] for s in segs)))
        segs.append({"assetId":item["id"],"start":start,"duration":duration,"zoom":1.02+0.02*((i+variant)%3),"caption":""})
        if sum(s["duration"] for s in segs)>=target-0.5:break
    hs=hooks(project_name)
    return {"hook":hs[variant%len(hs)],"segments":segs,"strategy":"reference_fast_reveal" if refs else "dynamic_scene_reveal","pace":pace}

def render_variant(workdir:Path,plan,sources_by_id:dict[str,Path],out:Path,captions=True,voiceover="auto"):
    segfiles=[]
    for i,s in enumerate(plan["segments"]):
        src=sources_by_id[s["assetId"]];seg=workdir/f"{out.stem}_s{i}.mp4";hook=plan["hook"] if captions and i==0 else "";caption=s.get("caption","") if captions else ""
        make_segment(src,seg,float(s["start"]),float(s["duration"]),float(s["zoom"]),hook,caption);segfiles.append(seg)
    concat=workdir/f"{out.stem}.txt";concat.write_text("\n".join([f"file '{p.as_posix()}'" for p in segfiles]),encoding="utf-8")
    base=workdir/f"{out.stem}_base.mp4";run([FFMPEG,"-y","-f","concat","-safe","0","-i",str(concat),"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-b:a","128k","-movflags","+faststart",str(base)],timeout=900)
    if voiceover!="off":
        voice=workdir/f"{out.stem}_voice.mp3"
        try:
            asyncio.run(Communicate(plan["hook"],voice="fr-FR-DeniseNeural",rate="+8%").save(str(voice)))
            if voice.exists() and voice.stat().st_size:
                run([FFMPEG,"-y","-i",str(base),"-i",str(voice),"-filter_complex","[0:a]volume=0.28[a0];[1:a]volume=1.1[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=2[a]","-map","0:v:0","-map","[a]","-c:v","copy","-c:a","aac","-b:a","128k","-movflags","+faststart",str(out)],timeout=600);return
        except Exception:pass
    out.write_bytes(base.read_bytes())

def score_output(path:Path,target:int,source_count:int,segment_count:int):
    duration,_=media_info(path);black=black_ratio(path,duration);duration_score=max(0,30-abs(duration-target)*2.5);diversity=min(20,source_count*6);pacing=min(20,segment_count*2.5);black_score=max(0,20-black*80);integrity=10 if path.exists() and path.stat().st_size>120000 else 0
    score=duration_score+diversity+pacing+black_score+integrity
    return round(max(0,min(100,score)),1),round(duration,2),round(black,3)

def render_job(jid:str):
    try:
        with db() as c:
            job=c.execute("select project_id,variants,settings,status from jobs where id=%s",(jid,)).fetchone()
            if not job:return
            project_id,variants,settings,status=job
            if status=="cancelled":return
            project=c.execute("select name from projects where id=%s",(project_id,)).fetchone();source_ids=[uuid.UUID(x) for x in settings.get("assetIds",[])]
            source_rows=c.execute("select id,name,data from assets where id=any(%s) and role='source'",(source_ids,)).fetchall();ref_rows=c.execute("select id,name,data from assets where project_id=%s and role='reference' and kind='source' order by created_at desc limit 4",(project_id,)).fetchall()
        if not source_rows:raise RuntimeError("Aucun rush source")
        update(jid,"running","analysis",8,"Analyse des rushs et détection des scènes")
        with tempfile.TemporaryDirectory(prefix="autodirector_") as td:
            workdir=Path(td);sources=[];refs=[];paths={};all_rows=[("source",r) for r in source_rows]+[("reference",r) for r in ref_rows]
            for idx,(role,row) in enumerate(all_rows):
                aid,name,data=row;path=workdir/f"a{idx}{Path(name).suffix or '.mp4'}";path.write_bytes(bytes(data));paths[str(aid)]=path;duration,_=media_info(path);cuts=scene_cuts(path);item={"id":str(aid),"name":name,"duration":duration,"cuts":cuts};(sources if role=="source" else refs).append(item)
            build_candidates(sources);build_candidates(refs);target=int(settings.get("targetDuration",18));captions=bool(settings.get("captions",True));voiceover=settings.get("voiceover","auto");auto_rev=bool(settings.get("autoRevision",True));output_ids=[];scores=[];total_revisions=0;best_strategy=""
            for v in range(max(1,min(3,int(variants)))):
                with db() as c:st=c.execute("select status from jobs where id=%s",(jid,)).fetchone()
                if st and st[0]=="cancelled":return
                plan=make_plan(project[0] if project else "Auto Director",sources,refs,v,target,0);update(jid,"running","director",18+v*22,f"Director : préparation variante {v+1}/{variants}",strategy=plan["strategy"]);initial=workdir/f"AutoDirector_V{v+1}.mp4";render_variant(workdir,plan,paths,initial,captions,voiceover);score,duration,black=score_output(initial,target,len({s["assetId"] for s in plan["segments"]}),len(plan["segments"]));final=initial;revision_count=0
                if auto_rev and score<78:
                    update(jid,"running","revision",min(88,32+v*22),f"Auto-révision V{v+1} · score {score}/100");plan2=make_plan(project[0] if project else "Auto Director",sources,refs,v,target,1);revised=workdir/f"AutoDirector_V{v+1}_R1.mp4";render_variant(workdir,plan2,paths,revised,captions,voiceover);score2,duration2,black2=score_output(revised,target,len({s["assetId"] for s in plan2["segments"]}),len(plan2["segments"]));
                    if score2>=score:final=revised;plan=plan2;score,duration,black=score2,duration2,black2;revision_count=1;total_revisions+=1
                meta={"score":score,"duration":duration,"blackRatio":black,"strategy":plan["strategy"],"hook":plan["hook"],"revisionCount":revision_count,"referenceCount":len(refs),"segmentCount":len(plan["segments"])}
                with db() as c:
                    aid=uuid.uuid4();blob=final.read_bytes();c.execute("insert into assets(id,project_id,name,content_type,size,role,kind,data,metadata) values(%s,%s,%s,'video/mp4',%s,'render','render',%s,%s)",(aid,project_id,final.name,len(blob),blob,Jsonb(meta)))
                output_ids.append(aid);scores.append(score);best_strategy=plan["strategy"];update(jid,"running","render",min(94,45+v*18),f"Variante {v+1} terminée · {score}/100",score=max(scores),revision=total_revisions,strategy=best_strategy)
            with db() as c:c.execute("update jobs set status='done',stage='complete',progress=100,message='Rendu terminé',output_asset_ids=%s,critic_score=%s,revision_count=%s,strategy=%s,updated_at=now() where id=%s",(output_ids,max(scores) if scores else 0,total_revisions,best_strategy,jid))
    except Exception as exc:
        try:update(jid,"failed","error",0,str(exc)[:500])
        except Exception:pass

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!="/health":self.send_response(404);self.end_headers();return
        db_ok=redis_ok=False
        try:
            with db() as c:c.execute("select 1")
            db_ok=True
        except Exception:pass
        try:redis_ok=bool(queue.ping())
        except Exception:pass
        body=json.dumps({"ok":db_ok and redis_ok,"worker":"ready","database":db_ok,"queue":redis_ok,"ffmpeg":bool(FFMPEG),"drawtext":DRAWTEXT}).encode();self.send_response(200 if db_ok and redis_ok else 503);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass

def health_server():HTTPServer(("0.0.0.0",int(os.environ.get("PORT","10000"))),Health).serve_forever()
def main():
    threading.Thread(target=health_server,daemon=True).start();print("Auto Director worker ready",flush=True)
    while True:
        item=queue.brpop("auto_director:jobs",timeout=5)
        if item:render_job(item[1])
if __name__=="__main__":main()
