# -*- coding: utf-8 -*-
import json
import os
import sys


def check(name, fn, critical=True):
    try:
        value=fn()
        return {'name':name,'ok':True,'critical':critical,'detail':str(value)[:240] if value is not None else 'OK'}
    except Exception as e:
        return {'name':name,'ok':False,'critical':critical,'detail':f'{type(e).__name__}: {str(e)[:220]}'}


def main():
    results=[]
    results.append(check('Python',lambda:f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',True))

    def ffmpeg_check():
        from imageio_ffmpeg import get_ffmpeg_exe
        import subprocess
        exe=get_ffmpeg_exe();p=subprocess.run([exe,'-version'],capture_output=True,text=True,timeout=15)
        if p.returncode:raise RuntimeError('FFmpeg ne démarre pas')
        return (p.stdout.splitlines() or ['FFmpeg OK'])[0]
    results.append(check('FFmpeg',ffmpeg_check,True))

    remote=os.environ.get('REMOTE_WORKER_MODE','0')=='1'
    studio=os.environ.get('STUDIO_URL','https://auto-director-web.onrender.com').rstrip('/')
    token=os.environ.get('WORKER_TOKEN','').strip()

    if remote:
        def studio_check():
            if studio!='https://auto-director-web.onrender.com':raise RuntimeError('STUDIO_URL non autorisée')
            if not token:raise RuntimeError('WORKER_TOKEN absent')
            import httpx
            with httpx.Client(timeout=12,follow_redirects=True) as c:
                r=c.post(studio+'/api/local-worker/heartbeat',headers={'Authorization':'Bearer '+token},json={'engine':'doctor','profile':'preflight','resolution':[720,1280],'fps':24,'ffmpegThreads':1,'localAI':False})
                r.raise_for_status()
            return 'HTTPS worker API = OK'
        results.append(check('Studio HTTPS',studio_check,True))
        results.append({'name':'Secrets cloud','ok':not bool(os.environ.get('DATABASE_URL') or os.environ.get('REDIS_URL')),'critical':False,'detail':'PostgreSQL/Redis non requis sur le PC'})
    else:
        db_url=os.environ.get('DATABASE_URL','').strip();redis_url=os.environ.get('REDIS_URL','').strip()
        def db_check():
            if not db_url:raise RuntimeError('DATABASE_URL non configurée')
            import psycopg
            with psycopg.connect(db_url,connect_timeout=8) as c:return 'select 1 = '+str(c.execute('select 1').fetchone()[0])
        def redis_check():
            if not redis_url:raise RuntimeError('REDIS_URL non configurée')
            import redis
            r=redis.from_url(redis_url,decode_responses=True,socket_connect_timeout=8,socket_timeout=8);return 'ping = '+str(bool(r.ping()))
        results.append(check('PostgreSQL',db_check,True));results.append(check('Redis',redis_check,True))

    profile=os.environ.get('PROFILE_NAME','safe-unknown')
    results.append({'name':'Profil matériel','ok':True,'critical':False,'detail':profile})

    def ollama_check():
        url=os.environ.get('LOCAL_VLM_URL','').strip()
        if not url:return 'désactivé volontairement'
        import httpx
        with httpx.Client(timeout=4) as c:r=c.get(url.rstrip('/')+'/api/tags');r.raise_for_status()
        return 'disponible'
    results.append(check('Ollama local',ollama_check,False))

    failed=[x for x in results if x['critical'] and not x['ok']]
    report={'ok':not failed,'profile':profile,'transport':'https' if remote else 'cloud-internal','checks':results}
    print(json.dumps(report,ensure_ascii=False))
    for x in results:
        mark='OK' if x['ok'] else ('ERREUR' if x['critical'] else 'OPTIONNEL')
        print(f"[{mark}] {x['name']}: {x['detail']}")
    return 0 if not failed else 2


if __name__=='__main__':raise SystemExit(main())
