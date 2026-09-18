(()=>{
  const STATUS_URL='/api/worker-status';
  const LOCAL_AGENT_URL='http://127.0.0.1:8765';
  const INSTALLER_URL='/static/INSTALL_AUTO_DIRECTOR_WORKER.bat';
  const byId=id=>document.getElementById(id);
  const safe=v=>v==null?'—':String(v);
  let agentState={online:false,workerRunning:false,busy:false};

  const renderLabel=info=>{
    const r=Array.isArray(info?.resolution)?info.resolution.join('×'):'—';
    return r+(info?.fps?` @ ${info.fps} fps`:'');
  };

  const notify=(message,type='ok')=>{
    try{ if(typeof toast==='function') return toast(message,type); }catch{}
    console.log(message);
  };

  function ensureControls(){
    const banner=byId('workerBanner');
    if(!banner||byId('localWorkerControl'))return;
    const box=document.createElement('div');
    box.className='worker-controls';
    box.innerHTML='<button id="localWorkerControl" class="worker-control-btn install" type="button">Détecter le PC…</button><span id="localAgentState" class="worker-agent-state">Agent PC : détection…</span>';
    banner.appendChild(box);
    byId('localWorkerControl').onclick=handleLocalWorkerClick;
  }

  function renderAgentControl(){
    ensureControls();
    const b=byId('localWorkerControl'),s=byId('localAgentState');
    if(!b||!s)return;
    b.disabled=!!agentState.busy;
    b.className='worker-control-btn';
    if(agentState.busy){
      b.textContent='Patiente…';
      s.textContent='Agent PC : opération en cours';
      return;
    }
    if(!agentState.online){
      b.classList.add('install');
      b.textContent='⬇ Installer le worker PC';
      s.textContent='Agent PC : non installé';
      return;
    }
    if(agentState.workerRunning){
      b.classList.add('stop');
      b.textContent='■ Arrêter le worker PC';
      s.textContent='Agent PC : worker démarré';
      return;
    }
    b.textContent='▶ Démarrer le worker PC';
    s.textContent='Agent PC : prêt';
  }

  async function pollAgent(){
    ensureControls();
    try{
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),1400);
      const r=await fetch(LOCAL_AGENT_URL+'/status',{cache:'no-store',mode:'cors',signal:controller.signal});
      clearTimeout(timer);
      if(!r.ok)throw new Error('agent offline');
      const data=await r.json();
      agentState.online=!!data.agent;
      agentState.workerRunning=!!data.workerRunning;
    }catch{
      agentState.online=false;
      agentState.workerRunning=false;
    }
    renderAgentControl();
  }

  function downloadInstaller(){
    const a=document.createElement('a');
    a.href=INSTALLER_URL;
    a.download='INSTALL_AUTO_DIRECTOR_WORKER.bat';
    document.body.appendChild(a);a.click();a.remove();
    notify('Installateur téléchargé. Ouvre-le une seule fois, puis reviens ici.');
  }

  async function agentPost(path,body={}){
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),22000);
    try{
      const r=await fetch(LOCAL_AGENT_URL+path,{method:'POST',mode:'cors',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await r.json().catch(()=>({}));
      if(!r.ok||!data.ok)throw new Error(data.error||`Agent ${r.status}`);
      return data;
    }finally{clearTimeout(timer)}
  }

  async function handleLocalWorkerClick(){
    if(agentState.busy)return;
    if(!agentState.online){downloadInstaller();return;}
    agentState.busy=true;renderAgentControl();
    try{
      if(agentState.workerRunning){
        await agentPost('/stop');
        notify('Worker PC arrêté. Render reprend automatiquement en secours.');
      }else{
        const session=localStorage.getItem('ad_token')||'';
        if(!session)throw new Error('Reconnecte-toi au Studio avant de lancer le worker PC.');
        await agentPost('/start',{studioUrl:location.origin,token:session});
        notify('Worker PC en démarrage. Le profil matériel et les dépendances sont vérifiés automatiquement.');
      }
    }catch(e){
      notify(e.message||'Impossible de contrôler le worker PC.','error');
    }finally{
      agentState.busy=false;
      setTimeout(pollAgent,600);
      setTimeout(pollWorker,1400);
    }
  }

  function markStudioOnline(){
    const dot=byId('statusDot'),service=byId('serviceLabel');
    if(dot)dot.className='ok';
    if(service)service.textContent='Services en ligne';
    const brand=document.querySelector('.brand span');
    if(brand)brand.textContent='Studio V8.5';
  }

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
    const statAi=byId('statAi');
    const queue=byId('workerQueuePill');
    if(!label||!detail||!led)return;
    try{
      const controller=new AbortController();
      const timer=setTimeout(()=>controller.abort(),5000);
      const r=await fetch(STATUS_URL,{cache:'no-store',signal:controller.signal,credentials:'same-origin'});
      clearTimeout(timer);
      if(!r.ok)throw new Error(`status ${r.status}`);
      const h=await r.json();
      markStudioOnline();
      const info=h.worker||{};
      const kind=h.activeWorker;
      if(!h.ok||!kind){
        paintOffline(h.queueDepth>0?`Aucun worker actif pour le moment · ${h.queueDepth} job(s) conservé(s).`:'Aucun worker actif pour le moment.');
        if(statAi)statAi.textContent='V8';
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
        if(statAi)statAi.textContent=localAI?'Local AI':'V8 local';
      }else{
        detail.textContent=agentState.online&&agentState.workerRunning?'Le worker PC démarre ou se prépare. Render reste actif jusqu’au heartbeat local.':'Le worker Render est vivant et traite les jobs tant que le PC local n’est pas connecté.';
        if(profile)profile.textContent='Fallback '+safe(info.profile||'cloud-safe');
        if(render)render.textContent=renderLabel(info);
        if(ai)ai.textContent='Director V8 local';
        if(statAi)statAi.textContent='V8 local';
      }
      if(queue)queue.textContent=`File ${Number(h.queueDepth||0)} job(s)`;
    }catch(e){
      paintOffline('État du worker temporairement indisponible.');
    }
  }

  ensureControls();
  pollAgent();
  pollWorker();
  setInterval(pollAgent,3000);
  setInterval(pollWorker,5000);
})();
