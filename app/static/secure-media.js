(()=>{
  // Navigation must stay operational even if another optional frontend module fails.
  const titles={studio:'Studio de création',pipeline:'Pipeline de production',gallery:'Galerie finale',intelligence:'Content Intelligence',learning:'Performance Memory',publication:'Centre de publication'};
  function activateTab(name){
    const target=document.getElementById(`tab-${name}`);
    if(!target)return;
    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('#nav button[data-tab]').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));
    target.classList.add('active');
    const title=document.getElementById('pageTitle');if(title)title.textContent=titles[name]||'Studio';
    if(name==='learning'&&typeof loadLearning==='function')Promise.resolve(loadLearning()).catch(()=>{});
  }
  document.querySelectorAll('#nav button[data-tab]').forEach(button=>{
    if(button.dataset.navFallbackBound==='1')return;
    button.addEventListener('click',()=>activateTab(button.dataset.tab));
    button.dataset.navFallbackBound='1';
  });

  const cache=new Map();
  async function mediaUrl(id){
    const now=Date.now();const hit=cache.get(id);
    if(hit&&hit.expires>now+30000)return hit.url;
    const r=await request(`/api/media-ticket/${id}`,{method:'POST'});
    const url=`/api/media/${id}?ticket=${encodeURIComponent(r.ticket)}`;
    cache.set(id,{url,expires:now+Math.max(240000,(Number(r.expiresIn||600)-60)*1000)});
    return url;
  }

  renderGallery=function(){
    const renders=state.assets.filter(a=>a.kind==='render'),el=$('gallery');
    if(!renders.length){el.dataset.signature='';el.innerHTML='<div class="empty-state">Tes rendus apparaîtront ici après le premier job terminé.</div>';return}
    const signature=renders.map(a=>`${a.id}:${a.size}`).join('|');
    if(el.dataset.signature===signature)return;
    el.dataset.signature=signature;
    el.innerHTML=renders.map(a=>{
      const j=state.jobs.find(j=>(j.outputAssetIds||[]).includes(a.id));
      return `<article class="render-card" data-render-id="${a.id}"><div class="video-shell"><video controls preload="metadata" data-media="${a.id}"></video></div><div class="render-info"><h4>${esc(a.name)}</h4><div class="job-meta">${(a.size/1048576).toFixed(1)} Mo ${j?.criticScore!=null?`· <span class="score">${Number(j.criticScore).toFixed(1)}/100</span>`:''}</div><div class="render-actions"><a class="btn tiny ghost" data-view="${a.id}" href="#">Voir</a><a class="btn tiny secondary" data-download="${a.id}" href="#" download="${esc(a.name)}">Télécharger</a></div></div></article>`
    }).join('');
    renders.forEach(async a=>{
      try{
        const url=await mediaUrl(a.id);const card=el.querySelector(`[data-render-id="${a.id}"]`);if(!card)return;
        const v=card.querySelector('video');if(v&&!v.src)v.src=url;
        const view=card.querySelector('[data-view]');if(view){view.href=url;view.target='_blank';view.rel='noopener'}
        const dl=card.querySelector('[data-download]');if(dl)dl.href=url;
      }catch(e){console.warn('Media ticket failed',e)}
    });
  };
})();
