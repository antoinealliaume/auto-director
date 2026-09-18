(()=>{
  const STATUS_URL='/api/worker-status';
  const LOCAL_AGENT_URL='http://127.0.0.1:8765';
  const INSTALLER_URL='/static/INSTALL_AUTO_DIRECTOR_WORKER.bat?v=2.2';
  const MIN_AGENT_VERSION=2.2;
  const byId=id=>document.getElementById(id);
  const safe=v=>v==null?'—':String(v);
  let agentState={online:false,workerRunning:false,busy:false,version:'',needsUpdate:false,lastError:'',logTail:''};

  const renderLabel=info=>{const r=Array.isArray(info?.resolution)?info.resolution.join('×'):'—';return r+(info?.fps?` @ ${info.fps} fps`:'')};
  const notify=(message,type='ok')=>{try{if(typeof toast==='function')return toast(message,type)}catch{}console.log(message)};
  const shortError=text=>{const s=String(text||'').replace(/[\u0000-\u001f]+/g,' ').replace(/\s+/g,' ').trim();return s.length>220?s.slice(-220):s};

  function ensureControls(){
    const banner=byId('workerBanner');if(!banner)return;
    let button=byId('localWorkerControl');
    if(!button){const box=document.createElement('div');box.className='worker-controls';box.innerHTML='<button id="localWorkerControl" class="worker-control-btn install" type="button">Détecter le PC…</button><span id="localAgentState" class="worker-agent-state">Agent PC : détection…</span>';banner.appendChild(box);button=byId('localWorkerControl')}
    if(button&&button.dataset.bound!=='1'){button.addEventListener('click',handleLocalWorkerClick);button.dataset.bound='1'}
  }

  function renderAgentControl(){
    ensureControls();const b=byId('localWorkerControl'),s=byId('localAgentState');if(!b||!s)return;
    b.disabled=!!agentState.busy;b.className='worker-control-btn';
    if(agentState.busy){b.textContent='Patiente…';s.textContent='Agent PC : opération en cours';return}
    if(!agentState.online){b.classList.add('install');b.textContent='⬇ Installer le worker PC';s.textContent='Agent PC : non installé';return}
    if(agentState.needsUpdate){b.classList.add('install');b.textContent='↻ Mettre à jour le worker PC';s.textContent=`Agent PC ${agentState.version||'ancien'} : mise à jour 2.2 requise`;return}
    if(agentState.workerRunning){b.classList.add('stop');b.textContent='■ Arrêter le worker PC';s.textContent=`Agent PC ${agentState.version} : worker démarré`;return}
    b.textContent='▶ Démarrer le worker PC';
    if(agentState.lastError||agentState.logTail){s.textContent='Dernière erreur : '+shortError(agentState.lastError||agentState.logTail)}
    else{s.textContent=`Agent PC ${agentState.version} : prêt · HTTPS`}
  }

  async function pollAgent(){
    ensureControls();
    try{
      const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),1600);
      const r=await fetch(LOCAL_AGENT_URL+'/status',{cache:'no-store',mode:'cors',signal:controller.signal});clearTimeout(timer);
      if(!r.ok)throw new Error('agent offline');
      const data=await r.json();
      agentState.online=!!data.agent;agentState.workerRunning=!!data.workerRunning;agentState.version=String(data.agentVersion||'');
      agentState.needsUpdate=!agentState.version||Number.parseFloat(agentState.version)<MIN_AGENT_VERSION;
      agentState.lastError=String(data.lastStartError||'');agentState.logTail=String(data.logTail||'');
    }catch{agentState.online=false;agentState.workerRunning=false;agentState.version='';agentState.needsUpdate=false;agentState.lastError='';agentState.logTail=''}
    renderAgentControl();
  }

  function downloadInstaller(){
    const a=document.createElement('a');a.href=INSTALLER_URL;a.download='INSTALL_AUTO_DIRECTOR_WORKER.bat';a.style.display='none';document.body.appendChild(a);a.click();setTimeout(()=>a.remove(),1000);
    notify('Téléchargement lancé. Ouvre le nouveau INSTALL_AUTO_DIRECTOR_WORKER.bat puis reviens dans le Studio.');
  }

  async function agentPost(path,body={}){
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),30000);
    try{const r=await fetch(LOCAL_AGENT_URL+path,{method:'POST',mode:'cors',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json().catch(()=>({}));if(!r.ok||!data.ok)throw new Error(shortError(data.error)||`Agent ${r.status}`);return data}finally{clearTimeout(timer)}
  }

  async function handleLocalWorkerClick(){
    if(agentState.busy)return;
    if(!agentState.online||agentState.needsUpdate){downloadInstaller();return}
    agentState.busy=true;agentState.lastError='';renderAgentControl();
    try{
      if(agentState.workerRunning){await agentPost('/stop');notify('Worker PC arrêté. Render reprend automatiquement en secours.')}
      else{const session=localStorage.getItem('ad_token')||'';if(!session)throw new Error('Reconnecte-toi au Studio avant de lancer le worker PC.');await agentPost('/start',{studioUrl:location.origin,token:session});notify('Worker PC lancé. Le premier démarrage peut prendre 1 à 2 minutes pour préparer Python/FFmpeg.')}
    }catch(e){notify(shortError(e.message)||'Impossible de contrôler le worker PC.','error')}
    finally{agentState.busy=false;setTimeout(pollAgent,700);setTimeout(pollWorker,1200);setTimeout(pollAgent,4500);setTimeout(pollWorker,5200)}
  }

  function markStudioOnline(){const dot=byId('statusDot'),service=byId('serviceLabel');if(dot)dot.className='ok';if(service)service.textContent='Services en ligne';const brand=document.querySelector('.brand span');if(brand)brand.textContent='Studio V8.6'}
  function paintOffline(reason='Aucun heartbeat worker reçu.'){
    const label=byId('workerStatusLabel'),detail=byId('workerStatusDetail'),led=byId('workerStatusLed'),stat=byId('statWorker');const profile=byId('workerProfilePill'),render=byId('workerRenderPill'),ai=byId('workerAiPill'),queue=byId('workerQueuePill');if(!label||!detail||!led)return;
    led.className='worker-led offline';label.textContent='Worker en attente';
    if(agentState.online&&!agentState.workerRunning&&(agentState.lastError||agentState.logTail))detail.textContent='Le worker PC s’est arrêté : '+shortError(agentState.lastError||agentState.logTail);
    else detail.textContent=reason+' Les jobs restent sauvegardés dans PostgreSQL et seront repris automatiquement.';
    if(stat)stat.textContent='Attente';if(profile)profile.textContent='Reprise auto';if(render)render.textContent='—';if(ai)ai.textContent='V8.6 sécurisé';if(queue)queue.textContent='File durable';
  }

  async function pollWorker(){
    const label=byId('workerStatusLabel'),detail=byId('workerStatusDetail'),led=byId('workerStatusLed'),stat=byId('statWorker'),profile=byId('workerProfilePill'),render=byId('workerRenderPill'),ai=byId('workerAiPill'),statAi=byId('statAi'),queue=byId('workerQueuePill');if(!label||!detail||!led)return;
    try{
      const session=localStorage.getItem('ad_token')||'';if(!session)throw new Error('missing session');
      const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),5000);
      const r=await fetch(STATUS_URL,{cache:'no-store',signal:controller.signal,credentials:'same-origin',headers:{'Authorization':'Bearer '+session}});
      clearTimeout(timer);if(!r.ok)throw new Error(`status ${r.status}`);const h=await r.json();markStudioOnline();const info=h.worker||{},kind=h.activeWorker;
      if(!h.ok||!kind){paintOffline(h.queueDepth>0?`Aucun worker actif pour le moment · ${h.queueDepth} job(s) conservé(s).`:'Aucun worker actif pour le moment.');if(statAi)statAi.textContent='V8.6';return}
      const local=kind==='local';led.className='worker-led '+(local?'local':'cloud');label.textContent=local?'PC local prioritaire':'Render en secours';if(stat)stat.textContent=local?'Local':'Cloud';
      if(local){const localAI=!!info.localAI;detail.textContent=info.profile==='starting'?'Ton PC prépare le worker local…':(localAI?'Ton PC traite les jobs via HTTPS avec l’IA locale prudente.':'Ton PC traite les jobs via HTTPS avec le Director V8.6 léger.');if(profile)profile.textContent='Profil '+safe(info.profile||'safe');if(render)render.textContent=renderLabel(info);if(ai)ai.textContent=localAI?`IA ${safe(info.model)}`:'IA lourde désactivée';if(statAi)statAi.textContent=localAI?'Local AI':'V8.6 local'}
      else{detail.textContent=agentState.online&&agentState.workerRunning?'Le worker PC se prépare. Render reste actif jusqu’au heartbeat local.':'Le worker Render traite les jobs tant que le PC local n’est pas connecté.';if(profile)profile.textContent='Fallback '+safe(info.profile||'cloud-safe');if(render)render.textContent=renderLabel(info);if(ai)ai.textContent='Director V8.6';if(statAi)statAi.textContent='V8.6'}
      if(queue)queue.textContent=`File ${Number(h.queueDepth||0)} job(s)`;
    }catch(e){paintOffline('État du worker temporairement indisponible.')}
  }

  ensureControls();pollAgent();pollWorker();setInterval(pollAgent,3000);setInterval(pollWorker,5000);
})();
