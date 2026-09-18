(()=>{
  const WORKER_HEALTH_URL='https://auto-director-worker.onrender.com/health';
  const byId=id=>document.getElementById(id);
  const safe=v=>v==null?'—':String(v);
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
      const timer=setTimeout(()=>controller.abort(),4500);
      const r=await fetch(WORKER_HEALTH_URL,{cache:'no-store',signal:controller.signal});
      clearTimeout(timer);
      const h=await r.json();
      if(!r.ok||!h.ok)throw new Error('worker degraded');
      const local=!!h.localWorkerOnline;
      const info=local?(h.localWorker||{}):{};
      led.className='worker-led '+(local?'local':'cloud');
      label.textContent=local?'PC local prioritaire':'Render en secours';
      stat.textContent=local?'Local':'Cloud';
      if(local){
        const localAI=!!info.localAI;
        detail.textContent=localAI?'Le PC traite les jobs avec IA locale prudente.':'Le PC traite les jobs en mode V8 léger, sans gros modèle.';
        profile.textContent='Profil '+safe(info.profile||'safe');
        render.textContent=(info.resolution||[]).join('×')+(info.fps?` @ ${info.fps} fps`:'');
        ai.textContent=localAI?`IA ${safe(info.model)}`:'IA lourde désactivée';
      }else{
        detail.textContent='Le worker cloud prend les jobs tant que le PC local n’est pas connecté.';
        profile.textContent='Fallback cloud';
        render.textContent=(h.resolution||[]).join('×')+(h.fps?` @ ${h.fps} fps`:'');
        ai.textContent='V8 local';
      }
      queue.textContent=`File ${Number(h.queueDepth||0)} job(s)`;
    }catch(e){
      led.className='worker-led offline';
      label.textContent='Worker indisponible';
      detail.textContent='Le Studio reste accessible, mais aucun rendu ne démarrera tant qu’un worker n’est pas revenu en ligne.';
      stat.textContent='—';
      profile.textContent='Hors ligne';
      render.textContent='—';
      ai.textContent='—';
      queue.textContent='—';
    }
  }
  pollWorker();
  setInterval(pollWorker,6000);
})();
