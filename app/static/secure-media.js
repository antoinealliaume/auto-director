(()=>{
  const cache=new Map();
  async function mediaUrl(id){const now=Date.now(),hit=cache.get(id);if(hit&&hit.expires>now+30000)return hit.url;const r=await request(`/api/media-ticket/${id}`,{method:'POST'});const url=`/api/media/${id}?ticket=${encodeURIComponent(r.ticket)}`;cache.set(id,{url,expires:now+Math.max(240000,(Number(r.expiresIn||600)-60)*1000)});return url}
  renderGallery=function(){
    const renders=typeof galleryFiltered==='function'?galleryFiltered():state.assets.filter(a=>a.kind==='render'),el=$('gallery');
    if(!el)return;
    if(!renders.length){el.dataset.signature='';el.innerHTML='<div class="empty-state">Aucun rendu correspondant.</div>';return}
    const signature=renders.map(a=>`${a.id}:${a.size}`).join('|');if(el.dataset.signature===signature)return;el.dataset.signature=signature;
    el.innerHTML=renders.map(a=>{const j=state.jobs.find(j=>(j.outputAssetIds||[]).includes(a.id));const strategy=j?.strategy||a.metadata?.strategy||'Director V9';const score=j?.criticScore??a.metadata?.score;return `<article class="render-card" data-render-id="${a.id}"><div class="video-shell"><video controls preload="metadata" data-media="${a.id}"></video></div><div class="render-info"><span class="manual-export-badge">Prêt · publication manuelle</span><h4>${esc(a.name)}</h4><div class="job-meta" data-export-meta>${esc(strategy)} · ${(a.size/1048576).toFixed(1)} Mo ${score!=null?`· <span class="score">${Number(score).toFixed(1)}/100</span>`:''}</div><div class="render-actions"><a class="btn tiny ghost" data-view="${a.id}" href="#">Voir</a><a class="btn tiny secondary" data-download="${a.id}" href="#" download="${esc(a.name)}">Télécharger la vidéo</a></div></div></article>`}).join('');
    renders.forEach(async a=>{try{const [url,manifest]=await Promise.all([mediaUrl(a.id),request(`/api/exports/${a.id}`)]),card=el.querySelector(`[data-render-id="${a.id}"]`);if(!card)return;const v=card.querySelector('video');if(v&&!v.src)v.src=url;const view=card.querySelector('[data-view]');if(view){view.href=url;view.target='_blank';view.rel='noopener'}const dl=card.querySelector('[data-download]');if(dl){dl.href=url;dl.download=manifest.filename;dl.title=`Enregistrer ${manifest.filename}`}const meta=card.querySelector('[data-export-meta]');if(meta)meta.insertAdjacentHTML('beforeend',`<br><span class="export-filename">${esc(manifest.filename)}</span>`)}catch(e){console.warn('Manual export preparation failed',e)}})
  };
  // Navigation fallback: a secondary module must never make the workspace unusable.
  document.querySelectorAll('#nav button[data-tab]').forEach(btn=>{if(btn.dataset.v9SafeNav==='1')return;btn.addEventListener('click',()=>{try{switchTab(btn.dataset.tab)}catch(e){console.error(e)}});btn.dataset.v9SafeNav='1'});
})();
