(()=>{
  const tab=document.getElementById('tab-publication');
  if(!tab)return;
  const style=document.createElement('link');style.rel='stylesheet';style.href='/static/publication.css?v=8.6';document.head.appendChild(style);
  let currentId='';let cache=[];
  const token=()=>localStorage.getItem('ad_token')||'';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const notify=(m,t='ok')=>{try{if(typeof toast==='function')return toast(m,t)}catch{}console.log(m)};
  async function api(url,opts={}){
    const headers={...(opts.headers||{}),'Authorization':'Bearer '+token()};
    if(opts.body && !(opts.body instanceof FormData) && !headers['Content-Type'])headers['Content-Type']='application/json';
    const r=await fetch(url,{...opts,headers,cache:'no-store'});let p=null;try{p=await r.json()}catch{p=await r.text()}
    if(!r.ok)throw Error(p?.detail||p||`Erreur ${r.status}`);return p;
  }
  function install(){
    tab.innerHTML=`<div class="section-title"><div><span class="eyebrow">PUBLISHING</span><h1>Centre de publication</h1></div></div>
      <div id="publicationCapability" class="publish-status"><i></i><div><b>Vérification TikTok…</b><span>Connexion au moteur de publication.</span></div></div>
      <div class="publish-layout">
        <section class="card publish-card">
          <div class="card-head"><div><span class="step">01</span><h3>Préparer un rendu</h3></div><span class="muted">TikTok</span></div>
          <div class="publish-form">
            <div class="field"><label>Rendu</label><select id="publicationAsset"></select></div>
            <div class="publish-actions"><button id="publicationPreviewBtn" class="btn ghost">Aperçu du pack</button><button id="publicationPrepareBtn" class="btn primary">Ajouter à la file</button></div>
          </div>
          <div id="publicationEditor" class="publication-pack editor hidden">
            <label>Caption<textarea id="publicationCaption" maxlength="2200"></textarea></label>
            <label>Hashtags<input id="publicationTags" placeholder="#gaming #fyp"></label>
            <label>CTA<input id="publicationCta" maxlength="300" placeholder="Dis-moi ce que tu aurais fait 👇"></label>
            <div class="publish-actions"><button id="publicationSaveBtn" class="btn ghost">Enregistrer</button><button id="publicationPublishBtn" class="btn secondary">Publier maintenant</button></div>
            <div class="publish-schedule"><div class="field"><label>Planifier</label><input id="publicationWhen" type="datetime-local"></div><button id="publicationScheduleBtn" class="btn primary">Planifier</button></div>
          </div>
          <p class="publish-note"><strong>Publication automatique :</strong> uniquement via l’API officielle TikTok Content Posting et une autorisation OAuth utilisateur. Aucune simulation de publication n’est marquée comme réussie.</p>
        </section>
        <section class="card publish-card">
          <div class="card-head"><div><span class="step">02</span><h3>File de publication</h3></div><button id="publicationRefreshBtn" class="btn tiny ghost">↻</button></div>
          <div id="publicationQueue" class="publication-queue"><div class="publication-empty">Chargement…</div></div>
        </section>
      </div>`;
    bind();
    try{if(typeof renderSelectors==='function')renderSelectors()}catch{}
  }
  function tagsArray(){return (document.getElementById('publicationTags')?.value||'').split(/\s+/).filter(Boolean).slice(0,12)}
  function fillEditor(pack,id=''){
    currentId=id||currentId;
    document.getElementById('publicationCaption').value=pack.caption||'';
    document.getElementById('publicationTags').value=(pack.hashtags||[]).join(' ');
    document.getElementById('publicationCta').value=pack.cta||'';
    document.getElementById('publicationEditor').classList.remove('hidden');
  }
  async function preview(){
    const id=document.getElementById('publicationAsset').value;if(!id)return notify('Choisis un rendu.','error');
    try{fillEditor(await api('/api/publication/'+id),'');currentId='';notify('Pack généré. Tu peux le modifier avant de l’ajouter à la file.')}catch(e){notify(e.message,'error')}
  }
  async function prepare(){
    const asset=document.getElementById('publicationAsset').value;if(!asset)return notify('Choisis un rendu.','error');
    const editor=document.getElementById('publicationEditor');
    const body=editor.classList.contains('hidden')?{}:{caption:document.getElementById('publicationCaption').value,hashtags:tagsArray(),cta:document.getElementById('publicationCta').value};
    try{const r=await api('/api/publications/prepare/'+asset,{method:'POST',body:JSON.stringify(body)});fillEditor(r.pack,r.id);notify('Publication ajoutée à la file.');await loadQueue()}catch(e){notify(e.message,'error')}
  }
  async function save(){
    if(!currentId)return notify('Ajoute d’abord ce pack à la file.','error');
    try{await api('/api/publications/'+currentId,{method:'PATCH',body:JSON.stringify({caption:document.getElementById('publicationCaption').value,hashtags:tagsArray(),cta:document.getElementById('publicationCta').value})});notify('Publication enregistrée.');await loadQueue()}catch(e){notify(e.message,'error')}
  }
  async function schedule(){
    if(!currentId)return notify('Ajoute d’abord ce pack à la file.','error');
    const value=document.getElementById('publicationWhen').value;if(!value)return notify('Choisis une date et une heure.','error');
    try{await save();await api('/api/publications/'+currentId+'/schedule',{method:'POST',body:JSON.stringify({scheduledAt:new Date(value).toISOString()})});notify('Publication planifiée.');await loadQueue()}catch(e){notify(e.message,'error')}
  }
  async function publish(id=currentId){
    if(!id)return notify('Ajoute d’abord ce pack à la file.','error');
    try{if(id===currentId)await save();await api('/api/publications/'+id+'/publish',{method:'POST'});notify('Publication envoyée à TikTok.');await loadQueue()}catch(e){notify(e.message,'error')}
  }
  async function connectTikTok(){
    try{const r=await api('/api/tiktok/connect',{method:'POST'});if(!r.authorizationUrl)throw Error('URL OAuth TikTok absente');location.href=r.authorizationUrl}catch(e){notify(e.message,'error')}
  }
  async function disconnectTikTok(){
    if(!confirm('Déconnecter le compte TikTok du Studio ?'))return;
    try{await api('/api/tiktok/disconnect',{method:'POST'});notify('TikTok déconnecté.');await loadCapabilities()}catch(e){notify(e.message,'error')}
  }
  function loadItem(id){
    const x=cache.find(v=>v.id===id);if(!x)return;currentId=x.id;fillEditor(x,x.id);const select=document.getElementById('publicationAsset');if(select)select.value=x.assetId;window.scrollTo({top:0,behavior:'smooth'});
  }
  function renderQueue(){
    const el=document.getElementById('publicationQueue');if(!el)return;
    if(!cache.length){el.innerHTML='<div class="publication-empty">Aucune publication préparée.</div>';return}
    el.innerHTML=cache.map(x=>`<article class="publication-item"><div class="publication-item-head"><div><h4>${esc(x.assetName||'Rendu')}</h4><small>${esc(x.projectName||'Projet')} · TikTok</small></div><span class="publication-status-badge ${esc(x.status)}">${esc(x.status)}</span></div><p>${esc(x.caption||'')}</p><div class="publication-meta">${x.scheduledAt?'Planifiée : '+new Date(x.scheduledAt).toLocaleString('fr-FR'):x.createdAt?'Créée : '+new Date(x.createdAt).toLocaleString('fr-FR'):''}</div><div class="publication-item-actions"><button class="btn tiny ghost" data-load-publication="${x.id}">Modifier</button><button class="btn tiny secondary" data-publish-publication="${x.id}">Publier</button></div></article>`).join('');
    el.querySelectorAll('[data-load-publication]').forEach(b=>b.onclick=()=>loadItem(b.dataset.loadPublication));
    el.querySelectorAll('[data-publish-publication]').forEach(b=>b.onclick=()=>publish(b.dataset.publishPublication));
  }
  async function loadQueue(){
    if(!token())return;try{const r=await api('/api/publications');cache=r.items||[];renderQueue()}catch(e){const el=document.getElementById('publicationQueue');if(el)el.innerHTML='<div class="publication-empty">'+esc(e.message)+'</div>'}
  }
  async function loadCapabilities(){
    if(!token())return;const el=document.getElementById('publicationCapability');if(!el)return;
    try{
      const x=await api('/api/publications/capabilities');el.className='publish-status '+(x.autoPublishReady?'ready':'');
      let title='TikTok en mode préparation',detail='Application TikTok Developer non configurée.',action='';
      if(x.officialOAuthConfigured&&!x.oauthConnected){title='TikTok prêt à être connecté';detail='OAuth officiel configuré · autorise ton compte TikTok.';action='<button id="tiktokConnectBtn" class="btn tiny primary">Connecter TikTok</button>'}
      if(x.oauthConnected&&!x.autoPublishReady){title='TikTok connecté';detail='Connexion chiffrée active · le scope video.publish manque encore.';action='<button id="tiktokDisconnectBtn" class="btn tiny ghost">Déconnecter</button>'}
      if(x.autoPublishReady){title='TikTok connecté · Direct Post autorisé';detail='Le scope video.publish est présent. Validation des paramètres de publication encore requise.';action='<button id="tiktokDisconnectBtn" class="btn tiny ghost">Déconnecter</button>'}
      el.innerHTML=`<i></i><div><b>${title}</b><span>${detail}</span></div>${action}`;
      document.getElementById('tiktokConnectBtn')?.addEventListener('click',connectTikTok);document.getElementById('tiktokDisconnectBtn')?.addEventListener('click',disconnectTikTok);
    }catch(e){el.innerHTML='<i></i><div><b>État TikTok indisponible</b><span>'+esc(e.message)+'</span></div>'}
  }
  function bind(){
    document.getElementById('publicationPreviewBtn').onclick=preview;
    document.getElementById('publicationPrepareBtn').onclick=prepare;
    document.getElementById('publicationSaveBtn').onclick=save;
    document.getElementById('publicationScheduleBtn').onclick=schedule;
    document.getElementById('publicationPublishBtn').onclick=()=>publish();
    document.getElementById('publicationRefreshBtn').onclick=()=>{loadQueue();loadCapabilities()};
    document.querySelector('[data-tab="publication"]')?.addEventListener('click',()=>setTimeout(()=>{loadQueue();loadCapabilities()},40));
  }
  install();
  if(token()){loadQueue();loadCapabilities()}
})();
