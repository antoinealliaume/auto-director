(()=>{
  const STATUS_URL='/api/worker-status';
  const byId=id=>document.getElementById(id);
  const safe=v=>v==null?'—':String(v);
  const renderLabel=info=>{
    const r=Array.isArray(info?.resolution)?info.resolution.join('×'):'—';
    return r+(info?.fps?` @ ${info.fps} fps`:'');
  };

  function paintOffline(reason='Aucun heartbeat worker reçu.'){
    const label=byId('workerStatusLabel'),detail=byId('workerStatusDetail'),led=byId('workerStatusLed'),stat=byId('statWorker');
    const profile=byId('workerProfilePill'),render=byId('workerRenderPill'),ai=byId('workerAiPill'),queue=byId('workerQueuePill');
    if(!label||!detail||!led)return;
    led.className='worker-led offline';
    label.textContent='Worker en attente';
    detail.textContent=reason+' Les jobs restent sauvegardés dans PostgreSQL et seront repris automatiquement.';
    if(stat)stat.textContent='Attente';
    if(profile)profile.textContent='Reprise auto';
    if(render)render.textContent='—';
    if(ai)ai.textContent='V8 sécurisé';
    if(queue)queue.textContent='File durable';
  }

  async function pollWorker(){
    const label=byId('workerStatusLabel');
    const detail=byId('workerStatusDetail');
    const led=byId('workerStatusLed');
    const stat=byId('statWorker');
    const profile=byId('workerProfilePill');
    const render=byId('workerRenderPill');
    const ai=byId('workerAiPill');
    const queue=byId('workerQueuePill');
    if(!label||!detail||!led)return;
    try{
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),5000);
      const r=await fetch(STATUS_URL,{cache:'no-store',signal:controller.signal,credentials:'same-origin'});
      clearTimeout(timer);
      if(!r.ok)throw new Error(`status ${r.status}`);
      const h=await r.json();
      const info=h.worker||{};
      const kind=h.activeWorker;
      if(!h.ok||!kind){
        paintOffline(h.queueDepth>0?`Aucun worker actif pour le moment · ${h.queueDepth} job(s) conservé(s).`:'Aucun worker actif pour le moment.');
        return;
      }
      const local=kind==='local';
      led.className='worker-led '+(local?'local':'cloud');
      label.textContent=local?'PC local prioritaire':'Render en secours';
      if(stat)stat.textContent=local?'Local':'Cloud';
      if(local){
        const localAI=!!info.localAI;
        detail.textContent=localAI?'Ton PC traite les jobs avec l’IA locale prudente.':'Ton PC traite les jobs avec le Director V8 léger, sans gros modèle.';
        if(profile)profile.textContent='Profil '+safe(info.profile||'safe');
        if(render)render.textContent=renderLabel(info);
        if(ai)ai.textContent=localAI?`IA ${safe(info.model)}`:'IA lourde désactivée';
      }else{
        detail.textContent='Le worker Render est vivant et traite les jobs tant que le PC local n’est pas connecté.';
        if(profile)profile.textContent='Fallback '+safe(info.profile||'cloud-safe');
        if(render)render.textContent=renderLabel(info);
        if(ai)ai.textContent='Director V8 local';
      }
      if(queue)queue.textContent=`File ${Number(h.queueDepth||0)} job(s)`;
    }catch(e){
      // A same-origin failure now means the Studio API itself could not report status.
      // We keep the wording recoverable because durable PostgreSQL jobs are not lost.
      paintOffline('État du worker temporairement indisponible.');
    }
  }

  pollWorker();
  setInterval(pollWorker,5000);
})();
