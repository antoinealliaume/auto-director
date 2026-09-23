import { I, mul, trs, slerp, persp, lookAt } from './math.js';
import {buildFrame as buildV4, motion as motionV4, describe as describeV4, signatures as signaturesV4} from './vfx.js?v=4.0.3';


const $ = id => document.getElementById(id);
const canvas = $('scene');
const stage = $('stage');
const mutationColors = ['#aed1a8','#6bbbf2','#e5bd62','#c6ed62','#b49de4'];
let manifest, meta, asset, binary, raw, meshes=[], textures=[], gl;
let nodes=[], worlds=[], binds=[], parents=[], inverse=[], jointNodes=[], animation;
let skin=new Float32Array(32*16), time=0, playing=true, speed=1, mutation=0, generation=0;
let theta=-.36, elevation=.19, distance=6.8, target=[0,1.,-.15], automatic=false;
let program, floorMesh, particleProgram, particleVAO, particleBuffer, lineProgram, lineVAO, lineBuffer;
let height=1, width=1, ready=false, compatible=false, last=performance.now(), fxCount=0;
let currentBounds={top:2.,radius:1.7}, cache=new Map(), toastTimer, transientURLs=[];
window.__viewer = { ready:false, mode:'loading' };

function notify(text) {
  $('toast').textContent=text; $('toast').classList.add('show');
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').classList.remove('show'),3000);
}
function loading(text) { $('loading').hidden=false; $('load-text').textContent=text; $('retry').hidden=true; }
function problem(error) {
  console.error(error); $('load-text').textContent='Le modèle n’a pas pu être chargé. Vérifiez votre connexion puis réessayez.';
  $('loading').hidden=false; $('retry').hidden=false;
}
function createProgram(vertex,fragment) {
  const p=gl.createProgram();
  for(const [type,source] of [[gl.VERTEX_SHADER,vertex],[gl.FRAGMENT_SHADER,fragment]]) {
    const s=gl.createShader(type); gl.shaderSource(s,source);gl.compileShader(s);
    if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(s));
    gl.attachShader(p,s);gl.deleteShader(s);
  }
  gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(p));
  const u={};for(let i=0;i<gl.getProgramParameter(p,gl.ACTIVE_UNIFORMS);i++) {
    const v=gl.getActiveUniform(p,i);u[v.name]=gl.getUniformLocation(p,v.name);
  }
  return {p,u};
}
const vs=`#version 300 es
precision highp float;
layout(location=0) in vec3 aP;layout(location=1) in vec3 aN;layout(location=2) in vec2 aUV;layout(location=3) in vec4 aJ;layout(location=4) in vec4 aW;
uniform mat4 uVP;uniform mat4 uBones[32];uniform bool uSkinned;
out vec3 vP;out vec3 vN;out vec2 vUV;
void main(){mat4 M=mat4(1.);if(uSkinned){ivec4 j=ivec4(aJ);M=uBones[j.x]*aW.x+uBones[j.y]*aW.y+uBones[j.z]*aW.z+uBones[j.w]*aW.w;}vec4 p=M*vec4(aP,1.);vP=p.xyz;vN=transpose(inverse(mat3(M)))*aN;vUV=aUV;gl_Position=uVP*p;}`;
const fs=`#version 300 es
precision highp float;
in vec3 vP;in vec3 vN;in vec2 vUV;out vec4 color;
uniform sampler2D uMap;uniform bool uTextured;uniform vec3 uBase,uEmission,uEye;uniform float uRough,uMetal;uniform bool uFloor;
vec3 tone(vec3 x){x=max(x,vec3(0.));return pow(clamp((x*(2.51*x+.03))/(x*(2.43*x+.59)+.14),0.,1.),vec3(1./2.2));}
void main(){vec3 N=normalize(vN);if(!gl_FrontFacing)N=-N;vec3 V=normalize(uEye-vP);vec3 a=uBase;if(uTextured)a*=pow(texture(uMap,vUV).rgb,vec3(2.2));
if(uFloor){float d=length(vP.xz);float circle=1.-smoothstep(.009,.017,abs(d-2.25));float contact=1.-.54*exp(-dot(vP.xz/vec2(1.05,.86),vP.xz/vec2(1.05,.86))*1.6);vec3 c=vec3(.020,.039,.047)*contact+circle*vec3(.024,.068,.062);color=vec4(tone(c),1.);return;}
vec3 L=normalize(vec3(-.65,.9,.8)), F=normalize(vec3(.7,.4,.8)), R=normalize(vec3(.5,.75,-.7));
float nl=max(dot(N,L),0.),fill=max(dot(N,F),0.),rim=max(dot(N,R),0.);
vec3 diffuse=a*(.28+.86*nl+.38*fill+.24*rim);vec3 H=normalize(L+V);
float shin=mix(90.,8.,uRough);float spec=pow(max(dot(N,H),0.),shin)*(.22+.42*uMetal);
float fres=pow(1.-max(dot(N,V),0.),3.);vec3 c=diffuse*(1.-.35*uMetal)+mix(vec3(1.,.97,.87),a,uMetal)*spec;
c+=mix(vec3(.11,.24,.28),a,uMetal)*fres*.3;c+=uEmission*.45;
color=vec4(tone(c),1.);}`;
const pvs=`#version 300 es
precision highp float;layout(location=0) in vec3 aP;layout(location=1) in vec4 aC;layout(location=2) in float aS;
uniform mat4 uVP;uniform float uHeight;out vec4 vC;void main(){gl_Position=uVP*vec4(aP,1.);gl_PointSize=clamp(aS*uHeight/gl_Position.w,2.,110.);vC=aC;}`;
const pfs=`#version 300 es
precision highp float;in vec4 vC;out vec4 color;void main(){float d=length(gl_PointCoord*2.-1.);if(d>1.)discard;float a=pow(1.-d,2.);color=vec4(vC.rgb,vC.a*a);}`;
const lvs=`#version 300 es
precision highp float;layout(location=0) in vec3 aP;uniform mat4 uVP;void main(){gl_Position=uVP*vec4(aP,1.);}`;
const lfs=`#version 300 es
precision highp float;uniform vec4 uColor;out vec4 color;void main(){color=uColor;}`;

function attr(location,data,size,kind=gl.FLOAT) {
  const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);
  gl.enableVertexAttribArray(location);gl.vertexAttribPointer(location,size,kind,false,0,0);return b;
}
function makeFloor() {
  const vao=gl.createVertexArray();gl.bindVertexArray(vao);
  attr(0,new Float32Array([-25,-.03,-25,25,-.03,-25,25,-.03,25,-25,-.03,-25,25,-.03,25,-25,-.03,25]),3);
  attr(1,new Float32Array(Array.from({length:6},()=>[0,1,0]).flat()),3);attr(2,new Float32Array(12),2);
  gl.bindVertexArray(null);return vao;
}
function initGL() {
  gl=canvas.getContext('webgl2',{antialias:true,alpha:true,preserveDrawingBuffer:true});
  if(!gl) return false;
  program=createProgram(vs,fs);floorMesh=makeFloor();particleProgram=createProgram(pvs,pfs);lineProgram=createProgram(lvs,lfs);
  particleVAO=gl.createVertexArray();gl.bindVertexArray(particleVAO);particleBuffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,particleBuffer);
  gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,32,0);
  gl.enableVertexAttribArray(1);gl.vertexAttribPointer(1,4,gl.FLOAT,false,32,12);
  gl.enableVertexAttribArray(2);gl.vertexAttribPointer(2,1,gl.FLOAT,false,32,28);
  lineVAO=gl.createVertexArray();gl.bindVertexArray(lineVAO);lineBuffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,lineBuffer);gl.enableVertexAttribArray(0);gl.vertexAttribPointer(0,3,gl.FLOAT,false,0,0);gl.bindVertexArray(null);
  canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();ready=false;fallbackMode();});
  return true;
}
function accessor(index) {
  if(cache.has(index)) return cache.get(index);
  const a=asset.accessors[index],v=asset.bufferViews[a.bufferView],C={5126:Float32Array,5125:Uint32Array,5123:Uint16Array,5121:Uint8Array}[a.componentType];
  const size={SCALAR:1,VEC2:2,VEC3:3,VEC4:4,MAT4:16}[a.type];
  const value=new C(binary,v.byteOffset+(a.byteOffset||0),a.count*size);cache.set(index,value);return value;
}
function parse(data) {
  const dv=new DataView(data);if(dv.getUint32(0,true)!==0x46546c67) throw Error('GLB incorrect');
  const jsLen=dv.getUint32(12,true);asset=JSON.parse(new TextDecoder().decode(new Uint8Array(data,20,jsLen)));
  const offset=20+jsLen;binary=data.slice(offset+8,offset+8+dv.getUint32(offset,true));cache.clear();
}
async function imageTexture(image,token) {
  const view=asset.bufferViews[image.bufferView];const blob=new Blob([binary.slice(view.byteOffset,view.byteOffset+view.byteLength)],{type:image.mimeType});
  const bitmap=await createImageBitmap(blob,{imageOrientation:'none',premultiplyAlpha:'none',colorSpaceConversion:'none'});
  if(token!==generation){bitmap.close();return null;}
  const t=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,t);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,bitmap);bitmap.close();gl.generateMipmap(gl.TEXTURE_2D);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR_MIPMAP_LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);return t;
}
function disposeModel() {
  for(const m of meshes){gl.deleteVertexArray(m.vao);for(const b of m.buffers)gl.deleteBuffer(b);}
  meshes=[];for(const t of textures)if(t)gl.deleteTexture(t);textures=[];
}
function loadGeometry() {
  for(const primitive of asset.meshes[0].primitives) {
    const vao=gl.createVertexArray();gl.bindVertexArray(vao);const at=primitive.attributes,b=[];
    for(const [id,key,size] of [[0,'POSITION',3],[1,'NORMAL',3],[2,'TEXCOORD_0',2],[3,'JOINTS_0',4],[4,'WEIGHTS_0',4]]) b.push(attr(id,accessor(at[key]),size,key==='JOINTS_0'?gl.UNSIGNED_SHORT:gl.FLOAT));
    const indices=accessor(primitive.indices),ib=gl.createBuffer();gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,ib);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,indices,gl.STATIC_DRAW);b.push(ib);
    meshes.push({vao,buffers:b,count:indices.length,type:asset.accessors[primitive.indices].componentType,primitive});
  }
  gl.bindVertexArray(null);nodes=asset.nodes;parents=nodes.map(()=>-1);
  nodes.forEach((n,i)=>(n.children||[]).forEach(c=>parents[c]=i));
  binds=nodes.map(n=>({t:n.translation||[0,0,0],r:n.rotation||[0,0,0,1],s:n.scale||[1,1,1]}));
  jointNodes=asset.skins[0].joints;const inv=accessor(asset.skins[0].inverseBindMatrices);inverse=jointNodes.map((_,i)=>inv.slice(i*16,i*16+16));
  const all=asset.meshes[0].primitives.map(p=>asset.accessors[p.attributes.POSITION]);
  currentBounds={top:Math.max(...all.map(a=>a.max[1])),radius:Math.max(...all.map(a=>Math.max(Math.abs(a.min[0]),a.max[0],Math.abs(a.min[2]),a.max[2])))};
}
function sample(sampler,t,path) {
  const ts=accessor(sampler.input),values=accessor(sampler.output),n=path==='rotation'?4:3;
  let i=0;while(i<ts.length-2 && ts[i+1]<t)i++;
  const f=Math.max(0,Math.min(1,(t-ts[i])/(ts[i+1]-ts[i]||1))),a=Array.from(values.slice(i*n,i*n+n)),b=Array.from(values.slice((i+1)*n,(i+2)*n));
  return path==='rotation'?slerp(a,b,f):a.map((v,k)=>v+(b[k]-v)*f);
}
function pose() {
  const local=binds.map(b=>({t:[...b.t],r:[...b.r],s:[...b.s]}));
  if(animation)for(const c of animation.channels) {
    const path=c.target.path,key={translation:'t',rotation:'r',scale:'s'}[path];local[c.target.node][key]=sample(animation.samplers[c.sampler],time,path);
  }
  worlds=[];const calculate=i=>{
    if(worlds[i])return worlds[i];let mat=trs(local[i].t,local[i].r,local[i].s);if(parents[i]>=0)mat=mul(calculate(parents[i]),mat);return worlds[i]=mat;
  };
  nodes.forEach((n,i)=>calculate(i));skin.fill(0);
  let scene=I();
  if(rv.enabled && $('effects').checked && rv.intensity>0) {
    const m=motionV4(meta.number,mutation,time,DUR(),animation?.name,rv.reduced);
    const r=rvClamp(currentBounds.radius,.8,1.45);
    scene=trs(m.translation.map(v=>v*r),[0,0,Math.sin(m.angle/2),Math.cos(m.angle/2)],m.scale);
  }
  worlds=worlds.map(w=>mul(scene,w));
  jointNodes.forEach((j,i)=>skin.set(mul(worlds[j],inverse[i]),i*16));
}
function point(name,offset=[0,0,0]) {
  const i=nodes.findIndex(n=>n.name===name),m=worlds[i]||I(),[x,y,z]=offset;
  return [m[0]*x+m[4]*y+m[8]*z+m[12],m[1]*x+m[5]*y+m[9]*z+m[13],m[2]*x+m[6]*y+m[10]*z+m[14]];
}
function lines(vp,list,color,width=1) {
  if(!list.length)return;gl.useProgram(lineProgram.p);gl.uniformMatrix4fv(lineProgram.u.uVP,false,vp);gl.uniform4fv(lineProgram.u.uColor,color);
  gl.bindVertexArray(lineVAO);gl.bindBuffer(gl.ARRAY_BUFFER,lineBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(list),gl.DYNAMIC_DRAW);gl.lineWidth(width);gl.drawArrays(gl.LINES,0,list.length/3);gl.bindVertexArray(null);
}
function ring(list,c,r,y=0,angle=0) {
  for(let i=0;i<80;i++) {
    const a=i*Math.PI/40,b=(i+1)*Math.PI/40;
    list.push(c[0]+r*Math.cos(a),c[1]+y+r*Math.sin(a)*Math.sin(angle),c[2]+r*Math.sin(a)*Math.cos(angle),c[0]+r*Math.cos(b),c[1]+y+r*Math.sin(b)*Math.sin(angle),c[2]+r*Math.sin(b)*Math.cos(angle));
  }
}
function effects(vp) { renderRarityVFX(vp); }

function render() {
  if(!ready||compatible||!gl)return;
  pose();const rect=stage.getBoundingClientRect(),dpr=Math.min(1.6,window.devicePixelRatio||1);width=Math.max(1,Math.round(rect.width*dpr));height=Math.max(1,Math.round(rect.height*dpr));
  if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
  const eye=[target[0]+Math.sin(theta)*Math.cos(elevation)*distance,target[1]+Math.sin(elevation)*distance,target[2]+Math.cos(theta)*Math.cos(elevation)*distance];
  const vp=mul(persp(36*Math.PI/180,width/height,.05,90),lookAt(eye,target));
  gl.viewport(0,0,width,height);gl.clearColor(0,0,0,0);gl.depthMask(true);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.disable(gl.BLEND);gl.enable(gl.CULL_FACE);gl.cullFace(gl.BACK);
  gl.useProgram(program.p);const un=program.u;gl.uniformMatrix4fv(un.uVP,false,vp);gl.uniform3fv(un.uEye,eye);gl.uniform1i(un.uFloor,true);gl.uniform1i(un.uSkinned,false);gl.bindVertexArray(floorMesh);gl.drawArrays(gl.TRIANGLES,0,6);
  gl.uniform1i(un.uFloor,false);gl.uniform1i(un.uSkinned,true);gl.uniformMatrix4fv(un['uBones[0]'],false,skin);
  for(const m of meshes){
    const mapping=m.primitive.extensions.KHR_materials_variants.mappings.find(v=>v.variants.includes(mutation));const mat=asset.materials[mapping.material],pbr=mat.pbrMetallicRoughness;
    gl.uniform3fv(un.uBase,(pbr.baseColorFactor||[1,1,1,1]).slice(0,3));gl.uniform3fv(un.uEmission,mat.emissiveFactor||[0,0,0]);gl.uniform1f(un.uRough,pbr.roughnessFactor);gl.uniform1f(un.uMetal,pbr.metallicFactor);
    gl.uniform1i(un.uTextured,Boolean(pbr.baseColorTexture));if(pbr.baseColorTexture){gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,textures[asset.textures[pbr.baseColorTexture.index].source]);gl.uniform1i(un.uMap,0);}
    gl.bindVertexArray(m.vao);gl.drawElements(gl.TRIANGLES,m.count,m.type,0);
  }
  gl.bindVertexArray(null);effects(vp);
  if($('skeleton').checked){const list=[];for(const j of jointNodes)if(jointNodes.includes(parents[j]))list.push(...worlds[j].slice(12,15),...worlds[parents[j]].slice(12,15));gl.disable(gl.DEPTH_TEST);lines(vp,list,[.46,1.,.85,1.]);gl.enable(gl.DEPTH_TEST);}
}
function DUR(){return meta?.clips.find(c=>c.id===animation?.name)?.duration||3;}
function timeline(){ $('timeline').max=DUR();$('timeline').value=time;$('time').textContent=`${time.toFixed(2).replace('.',',')} / ${DUR().toFixed(2).replace('.',',')} s`;$('play').textContent=playing?'Pause':'Lire';$('state').textContent=playing?'LECTURE':'PAUSE'; }
function selectClip(name) {
  if(!asset)return;animation=name==='Spawn'?{name:'Spawn',channels:[]}:asset.animations.find(a=>a.name===name)||asset.animations[0];time=0;playing=true;$('loop').checked=Boolean(meta.clips.find(c=>c.id===animation.name)?.loop);$('animation').value=animation.name;
  $('clip-description').textContent=describeV4(meta.number,mutation,animation.name);$('clip-label').textContent=meta.clips.find(c=>c.id===animation.name).label;timeline();rvSyncUI();render();
}
function mutationUI(){
  document.querySelectorAll('[data-mutation]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.mutation===mutation)));
  $('mutation-description').textContent=describeV4(meta.number,mutation,animation?.name);$('subtitle').textContent=`${meta.signature} · ${manifest.mutations[mutation]}`;
  if(compatible)$('fallback').src=`./previews/${meta.id}-${mutation}.jpg`;
  rv.previewTime = 0; rvSyncUI(); if (compatible) rvPreview(0, true);
}
function setMutation(v) {mutation=Math.max(0,Math.min(4,Math.trunc(Number(v)||0)));mutationUI();saveAddress();render();}
function saveAddress(){const url=new URL(location.href);url.hash=`${meta.id}/${mutation}`;history.replaceState(null,'',url);}
function resetCamera(){
 const r=rvClamp(currentBounds.radius,.8,1.45),aspect=Math.max(.5,stage.clientWidth/stage.clientHeight);
 let top=currentBounds.top,bottom=0,extent=currentBounds.radius;
 for(const t of [0,.6,1.2,1.8,2.4]) {
  const f=buildV4({number:meta.number,tier:mutation,time:t,clip:'Special',radius:r,quality:.5});
  for(let i=0;i<f.triangles.length;i+=7){extent=Math.max(extent,Math.abs(f.triangles[i]),Math.abs(f.triangles[i+2]));top=Math.max(top,f.triangles[i+1]);bottom=Math.min(bottom,f.triangles[i+1]);}
 }
 target=[0,(top+bottom)*.5,-.05];distance=Math.max(4.9,extent/(Math.tan(Math.PI/10)*aspect),(top-bottom)*.5/Math.tan(Math.PI/10))*1.24;
 theta=-.36;elevation=.19;automatic=false;$('rotate').setAttribute('aria-pressed','false');
}

function fallbackMode(){
  compatible=true;canvas.hidden=true;$('fallback').hidden=false;$('render-state').textContent='APERÇU FIXE · WEBGL INDISPONIBLE';
  for(const id of ['play','restart','timeline','animation','speed','skeleton','effects','accessories','loop','rotate','reset']){$(id).disabled=true;}
  document.querySelectorAll('[data-view]').forEach(b=>b.disabled=true);
  $('fallback').src=`./previews/${meta.id}-${mutation}.jpg`;
  $('clip-description').textContent='Aperçu fixe du véritable modèle. L’animation nécessite un navigateur avec WebGL 2.';ready=true;window.__viewer.ready=true;window.__viewer.mode='static-preview';$('loading').hidden=true;rvSyncUI();rvPreview(0,true);
}
async function loadSpecies(id) {
  const item=manifest.species.find(s=>s.id===id)||manifest.species[0];const token=++generation;ready=false;window.__viewer.ready=false;meta=item;
  loading(`Chargement de ${meta.name}…`);$('title').textContent=meta.name;$('biome').textContent=meta.biome;$('rarity').textContent=meta.rarity;$('species-number').textContent=`ESPÈCE ${String(meta.number).padStart(3,'0')} / 096`;
  $('triangles').textContent=meta.triangles.toLocaleString('fr-FR');$('bones').textContent=meta.bones;
  $('animation').innerHTML=meta.clips.map(c=>`<option value="${c.id}">${c.label}</option>`).join('');
  document.querySelectorAll('[data-species]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.species===meta.id)));mutationUI();saveAddress();
  try{
    const response=await fetch(`./${meta.model}`);if(!response.ok)throw Error('Model HTTP '+response.status);const data=await response.arrayBuffer();if(token!==generation)return;
    raw=data;parse(raw);
    if(!gl||compatible){fallbackMode();return;}
    disposeModel();loadGeometry();const loadedTextures=await Promise.all(asset.images.map(i=>imageTexture(i,token)));if(token!==generation){loadedTextures.forEach(t=>t&&gl.deleteTexture(t));return;}textures=loadedTextures;
    resetCamera();ready=true;rvSyncUI();$('render-state').textContent='3D TEMPS RÉEL';selectClip('Idle');$('loading').hidden=true;
    Object.assign(window.__viewer,{ready:true,mode:'webgl',clips:meta.clips.map(c=>c.id)});
  }catch(error){if(token===generation)problem(error);}
}
function exportMutation(){
  if(!raw)return;const view=new DataView(raw);const len=view.getUint32(12,true),json=JSON.parse(new TextDecoder().decode(new Uint8Array(raw,20,len)));
  for(const mesh of json.meshes)for(const p of mesh.primitives)p.material=p.extensions.KHR_materials_variants.mappings.find(m=>m.variants.includes(mutation)).material;
  json.asset.extras={...json.asset.extras,selectedMutation:manifest.mutations[mutation]};let bytes=new TextEncoder().encode(JSON.stringify(json));const padded=(bytes.length+3)&~3,oldOffset=20+len;const binLength=view.getUint32(oldOffset,true);
  const out=new ArrayBuffer(12+8+padded+8+binLength),dv=new DataView(out),arr=new Uint8Array(out);dv.setUint32(0,0x46546c67,true);dv.setUint32(4,2,true);dv.setUint32(8,out.byteLength,true);dv.setUint32(12,padded,true);dv.setUint32(16,0x4e4f534a,true);arr.fill(32,20,20+padded);arr.set(bytes,20);dv.setUint32(20+padded,binLength,true);dv.setUint32(24+padded,0x004e4942,true);arr.set(new Uint8Array(raw,oldOffset+8,binLength),28+padded);
  const url=URL.createObjectURL(new Blob([out],{type:'model/gltf-binary'})),a=document.createElement('a');a.href=url;a.download=`${meta.id}_${meta.name}_${manifest.mutations[mutation]}.glb`;a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);
}
$('animation').onchange=e=>selectClip(e.target.value);
$('play').onclick=()=>{playing=!playing;timeline();};$('restart').onclick=()=>{time=0;playing=true;timeline();};
$('timeline').oninput=e=>{time=+e.target.value;playing=false;timeline();render();};$('speed').onchange=e=>speed=+e.target.value;
$('reset').onclick=()=>{resetCamera();render();};$('rotate').onclick=()=>{automatic=!automatic;$('rotate').setAttribute('aria-pressed',String(automatic));};
for(const e of document.querySelectorAll('[data-view]'))e.onclick=()=>{automatic=false;$('rotate').setAttribute('aria-pressed','false');theta={front:0,side:Math.PI/2,back:Math.PI}[e.dataset.view];render();};
$('download').onclick=exportMutation;$('retry').onclick=()=>loadSpecies(meta?.id||'blob');
$('share').onclick=async()=>{const url=new URL(location.href);url.search='';url.hash=`${meta.id}/${mutation}`;$('share-url').hidden=false;$('share-url').value=url.href;try{await navigator.clipboard.writeText(url.href);notify('Lien direct copié');}catch{$('share-url').focus();$('share-url').select();notify('Copiez le lien affiché');}};
const fingers=new Map();let lastPinch=0;
canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);fingers.set(e.pointerId,[e.clientX,e.clientY]);automatic=false;$('rotate').setAttribute('aria-pressed','false');};
canvas.onpointermove=e=>{if(!fingers.has(e.pointerId))return;const old=fingers.get(e.pointerId);fingers.set(e.pointerId,[e.clientX,e.clientY]);if(fingers.size===2){const a=[...fingers.values()];const dist=Math.hypot(a[0][0]-a[1][0],a[0][1]-a[1][1]);if(lastPinch)distance=Math.max(2,Math.min(18,distance*lastPinch/dist));lastPinch=dist;}else{theta-=(e.clientX-old[0])*.009;elevation=Math.max(-.02,Math.min(1.15,elevation+(e.clientY-old[1])*.006));}render();};
canvas.onpointerup=canvas.onpointercancel=e=>{fingers.delete(e.pointerId);lastPinch=0;};canvas.onwheel=e=>{e.preventDefault();distance=Math.min(18,Math.max(2,distance*Math.exp(e.deltaY*.001)));render();};
window.__creatures={getState:()=>({species:meta?.id,mutation,clip:animation?.name,time,playing,fxCount,ready,mode:compatible?'static':'webgl'}),select:loadSpecies,mutation:setMutation,clip:selectClip,seek:t=>{time=Math.max(0,Math.min(DUR(),Number(t)||0));playing=false;render();timeline();},render, camera:(t,e,d)=>{theta=t;elevation=e;distance=d;render();}};
window.addEventListener('keydown',e=>{if(['INPUT','SELECT','BUTTON'].includes(document.activeElement?.tagName))return;if(e.code==='Space'){e.preventDefault();$('play').click();}});

function normalizeSearch(v){return String(v).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();}
function renderCatalogue(){
 if(!manifest)return;const query=normalizeSearch($('search').value),family=$('family').value;
 const filtered=manifest.species.filter(s=>(family==='all'||s.family===family)&&normalizeSearch(`${s.name} ${s.signature} ${s.biome} ${s.id} ${s.number}`).includes(query));
 $('results-count').textContent=`${filtered.length} / 96`;$('empty').hidden=filtered.length>0;
 $('species').innerHTML=filtered.map(s=>`<button class="species-card" data-species="${s.id}" aria-pressed="${s.id===meta?.id}"><span class="number">${String(s.number).padStart(3,'0')}</span><img src="./previews/${s.id}-0.jpg" alt="" loading="lazy" width="160" height="160"><strong>${s.name}</strong><small>${s.biome}</small></button>`).join('');
 document.querySelectorAll('[data-species]').forEach(b=>b.onclick=()=>{loadSpecies(b.dataset.species);document.body.classList.remove('catalog-open');$('catalog-toggle').setAttribute('aria-expanded','false');});
}
$('search').oninput=renderCatalogue;$('family').onchange=renderCatalogue;
$('clear-filters').onclick=()=>{$('search').value='';$('family').value='all';renderCatalogue();};
$('catalog-toggle').onclick=()=>{const open=document.body.classList.toggle('catalog-open');$('catalog-toggle').setAttribute('aria-expanded',String(open));};
window.addEventListener('hashchange',()=>{const [id,v]=location.hash.slice(1).split('/');mutation=/^[0-4]$/.test(v||'')?+v:0;loadSpecies(id);});

function tick(now){const dt=Math.min(.05,(now-last)/1000);last=now;if(ready&&!compatible){if(playing){time+=dt*speed;if(time>DUR()){if($('loop').checked)time%=DUR();else{time=DUR();playing=false;}}}if(automatic)theta+=dt*.20;render();timeline();}if(compatible)rvPreview(dt);requestAnimationFrame(tick);}
// Slime Atlas: five escalating visual signatures, evaluated from the animation clock.
// Inserted in the original viewer module; the GLBs, skins and material alpha are unchanged.
const RV_VERSION = 'choreography-v4-20260923';
const RV_PROFILES = [
 {name:'Normal',color:'#b5ddba'}, {name:'Bleu',color:'#43baff'},
 {name:'Doré',color:'#ffbe36'}, {name:'Radioactif',color:'#a2ff2c'},
 {name:'Galaxy',color:'#ac7bff'}
];
const rvReducedMedia = matchMedia('(prefers-reduced-motion: reduce)');
const rv = {
  enabled: true, intensity: 1, quality: 'auto', reduced: rvReducedMedia.matches,
  previewTime: 0, previewPlaying: !rvReducedMedia.matches, context: null,
  pointProgram: null, ribbonProgram: null, pointVAO: null, pointBuffer: null,
  ribbonVAO: null, ribbonBuffer: null, overlay: null, points: 0, triangles: 0,
  stateKey: '', lastPreview: -1
};
try {
  const saved = JSON.parse(localStorage.getItem('slime-rarity-settings-v1') || '{}');
  if (typeof saved.enabled === 'boolean') rv.enabled = saved.enabled;
  if (Number.isFinite(saved.intensity)) rv.intensity = Math.max(0, Math.min(1.5, saved.intensity));
  if (['auto', 'light', 'high'].includes(saved.quality)) rv.quality = saved.quality;
  if (typeof saved.reduced === 'boolean') rv.reduced = saved.reduced;
} catch { /* Storage can be unavailable in an embedded or private browser. */ }
const rvClamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const rvFract = v => v - Math.floor(v);
const rvHex = hex => hex.slice(1).match(/../g).map(v => parseInt(v, 16) / 255);
const rvMix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const rvProfile = () => RV_PROFILES[rvClamp(Math.trunc(mutation || 0), 0, 4)];
function rvBudget() {
  const light = rv.quality === 'light' || (rv.quality === 'auto' && (innerWidth < 800 || (navigator.hardwareConcurrency || 4) < 4));
  return (light ? .52 : 1) * (rv.reduced ? .55 : 1);
}
function rvPersist() {
  try { localStorage.setItem('slime-rarity-settings-v1', JSON.stringify({ enabled: rv.enabled, intensity: rv.intensity, quality: rv.quality, reduced: rv.reduced })); } catch { /* Optional preference persistence. */ }
}
function rvRefresh() {
  rv.lastPreview = -1;
  rvSyncUI();
  rvPersist();
  if (compatible) rvPreview(0, true); else render();
}
function rvSyncUI() {
  const p = rvProfile();
  const on = rv.enabled && rv.intensity > 0;
  document.documentElement.style.setProperty('--rarity-color', p.color);
  stage.dataset.rarity = String(mutation);
  stage.dataset.rarityOn = String(on);
  if ($('rv-title')) {
    $('rv-title').textContent = meta ? signaturesV4[meta.number-1].title : 'Chorégraphies V4';
    $('rv-summary').textContent = meta ? describeV4(meta.number,mutation,animation?.name) : '96 structures animées';
    $('rv-signature').textContent = 'V4 · volumes articulés · apparition, déplacement, attaque et impact';
    $('rv-level').textContent = `${mutation + 1} / 5 · ${p.name}`;
    $('rv-bars').innerHTML = RV_PROFILES.map((_, i) => `<i class='${i <= mutation ? 'lit' : ''}'></i>`).join('');
    $('rv-mode').textContent = compatible
      ? 'Modèle fixe · projection 2D des formes V4. Animations du modèle disponibles en WebGL 2.'
      : 'Effets 3D liés au modèle et à sa timeline. Pause et ralenti restent synchronisés.';
    $('rv-preview-pause').hidden = !compatible;
    $('rv-preview-pause').textContent = rv.previewPlaying ? 'Figer les formes 2D' : 'Animer les formes 2D';
    $('rv-intensity-value').textContent = `${Math.round(rv.intensity * 100)} %`;
  }
  if (rv.overlay) rv.overlay.hidden = !compatible || !ready || !on;
  // The original static fallback disables these; 2D aura controls remain meaningful.
  if (compatible) {
    $('effects').disabled = false;
    $('accessories').disabled = false;
    if (ready) $('render-state').textContent = 'MODÈLE FIXE · EFFETS 2D';
  }
  rv.stateKey = `${meta?.id}/${mutation}`;
}
function initRarityControls() {
  const panel = document.createElement('div');
  panel.className = 'rarity-panel';
  panel.innerHTML = `
    <div class='rarity-top'><span id='rv-level'></span><label class='check'><input id='rv-enabled' type='checkbox'> Effets activés</label></div>
    <div id='rv-bars' class='rarity-bars' aria-hidden='true'></div>
    <h4 id='rv-title'></h4><p id='rv-summary' class='note'></p><p id='rv-signature' class='note rarity-signature'></p>
    <details class='rarity-settings'><summary>Réglages des effets</summary>
      <label for='rv-intensity'>Intensité <output id='rv-intensity-value'></output></label>
      <input id='rv-intensity' type='range' min='0' max='150' step='5' aria-label='Intensité des effets de rareté'>
      <label for='rv-quality'>Qualité des effets</label>
      <select id='rv-quality'><option value='auto'>Auto · adaptée à l’écran</option><option value='light'>Légère</option><option value='high'>Élevée</option></select>
      <label class='check'><input id='rv-reduced' type='checkbox'> Mouvements et éclats réduits</label>
    </details>
    <button id='rv-preview-pause' type='button' hidden>Figer l’aura 2D</button>
    <p id='rv-mode' class='note'></p>`;
  $('mutation-description').after(panel);
  $('rv-enabled').checked = rv.enabled;
  $('rv-intensity').value = Math.round(rv.intensity * 100);
  $('rv-quality').value = rv.quality;
  $('rv-reduced').checked = rv.reduced;
  $('rv-enabled').onchange = e => { rv.enabled = e.target.checked; rvRefresh(); };
  $('rv-intensity').oninput = e => { rv.intensity = rvClamp(Number(e.target.value) / 100, 0, 1.5); rvRefresh(); };
  $('rv-quality').onchange = e => { rv.quality = e.target.value; rvRefresh(); };
  $('rv-reduced').onchange = e => { rv.reduced = e.target.checked; rvRefresh(); };
  $('rv-preview-pause').onclick = () => { rv.previewPlaying = !rv.previewPlaying; rvRefresh(); };
  for (const id of ['effects', 'accessories']) $(id).addEventListener('change', rvRefresh);
  rv.overlay = document.createElement('canvas');
  rv.overlay.id = 'rarity-preview';
  rv.overlay.setAttribute('aria-hidden', 'true');
  rv.overlay.hidden = true;
  stage.append(rv.overlay);
  rvSyncUI();
  window.__rarity = {
    version: RV_VERSION,
    getState: () => ({ tier: mutation, name: rvProfile().name, enabled: rv.enabled, intensity: rv.intensity, quality: rv.quality, reduced: rv.reduced, signature:meta?signaturesV4[meta.number-1].title:null,particles: rv.points, triangles: rv.triangles, mode: compatible ? '2d-over-fixed-model' : '3d', previewTime: rv.previewTime, previewPlaying: rv.previewPlaying }),
    inspect: () => rvBuildFrame(compatible),
    seekPreview: t => { rv.previewTime = Math.max(0, Number(t) || 0); rv.previewPlaying = false; rvPreview(0, true); }
  };
}

// All particles and ribbons are pure functions of the selected specimen, tier and time.
// No accumulated simulation means scrubbing backwards cannot leave old trails behind.
function v4Colors() {
 const palettes=[['#66cf79','#d8e8a1','#faafcb'],['#4cd4e6','#a5f5e3','#f4d0ff'],['#ba77ed','#6889e8','#eff4ff'],['#ff743d','#ffcf65','#fae49d'],['#84dcea','#d0f5ff','#849ef0'],['#b5d66b','#f8d59c','#f3b4dc'],['#ee92b6','#ffe0a1','#9adde2'],['#9882cd','#c3bfef','#72b2d3'],['#9adb3e','#e4f67c','#48beac'],['#e4b367','#b0ccda','#5ccfeb'],['#a785ec','#74d9f0','#fff2c5'],['#f1d385','#fbefbd','#bda1e8']];
 const colors=palettes[Math.floor((meta.number-1)/8)].map(rvHex);
 const accent=rvHex(rvProfile().color);
 return colors.map((c,i)=>rvMix(c,accent,mutation===4?.32:mutation===3?.3:mutation===2?.25:mutation===1?.2:0));
}
function rvBuildFrame(preview = false) {
  const empty = {points:[],triangles:[],rings:[]};
  if (!meta || !ready || !rv.enabled || !$('effects').checked || rv.intensity <= 0) return empty;
  return buildV4({number:meta.number,tier:mutation,time:preview?rv.previewTime:time,
    duration:DUR(),clip:preview?'Idle':animation?.name,radius:preview?1:rvClamp(currentBounds.radius,.8,1.45),
    intensity:rv.intensity,quality:rvBudget(),reduced:rv.reduced,
    colors:v4Colors(),accessories:$('accessories').checked});
}

function rvInitGL() {
  if (rv.context === gl && rv.pointProgram) return;
  rv.context = gl;
  rv.pointProgram = createProgram(`#version 300 es
precision highp float;
layout(location=0) in vec3 aP;
layout(location=1) in vec4 aC;
layout(location=2) in float aS;
layout(location=3) in float aK;
uniform mat4 uVP;
uniform float uHeight;
out vec4 vC;
out float vK;
void main(){gl_Position=uVP*vec4(aP,1.);gl_PointSize=clamp(aS*uHeight/max(.1,gl_Position.w),1.,220.);vC=aC;vK=aK;}`, `#version 300 es
precision highp float;
in vec4 vC;
in float vK;
out vec4 color;
void main(){
  vec2 p=gl_PointCoord*2.-1.;float d=length(p);if(d>1.)discard;
  float a=pow(max(0.,1.-d),2.);
  if(vK>.5&&vK<1.5)a=exp(-d*d*17.)*.8+pow(max(0.,1.-d),4.)*.3;
  if(vK>1.5&&vK<2.5)a=exp(-pow((d-.70)*17.,2.))*.70+exp(-length(p-vec2(-.25,-.33))*18.)*.8+a*.10;
  if(vK>2.5&&vK<3.5)a=pow(max(0.,1.-d),1.8)*(.72+.28*sin(p.x*11.+p.y*8.));
  if(vK>3.5)a=exp(-d*d*19.)+exp(-abs(p.x)*42.)*pow(1.-abs(p.y),2.)*.85+exp(-abs(p.y)*42.)*pow(1.-abs(p.x),2.)*.85;
  color=vec4(vC.rgb,min(.90,vC.a*a));
}`);
  rv.ribbonProgram = createProgram(`#version 300 es
precision highp float;
layout(location=0) in vec3 aP;layout(location=1) in vec4 aC;
uniform mat4 uVP;out vec4 vC;
void main(){gl_Position=uVP*vec4(aP,1.);vC=aC;}`, `#version 300 es
precision highp float;in vec4 vC;out vec4 color;void main(){color=vC;}`);
  rv.pointVAO = gl.createVertexArray(); gl.bindVertexArray(rv.pointVAO);
  rv.pointBuffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, rv.pointBuffer);
  for (const [i, n, offset] of [[0, 3, 0], [1, 4, 12], [2, 1, 28], [3, 1, 32]]) { gl.enableVertexAttribArray(i); gl.vertexAttribPointer(i, n, gl.FLOAT, false, 36, offset); }
  rv.ribbonVAO = gl.createVertexArray(); gl.bindVertexArray(rv.ribbonVAO);
  rv.ribbonBuffer = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, rv.ribbonBuffer);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 28, 0);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 4, gl.FLOAT, false, 28, 12);
  gl.bindVertexArray(null);
}
function renderRarityVFX(vp) {
  const frame = rvBuildFrame(false);
  rv.points = fxCount = frame.points.length; rv.triangles = frame.triangles.length / 21;
  if (!frame.points.length && !frame.triangles.length) return;
  rvInitGL();
  gl.enable(gl.DEPTH_TEST); gl.depthMask(false); gl.disable(gl.CULL_FACE);
  gl.enable(gl.BLEND); gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
  if (frame.triangles.length) {
    gl.useProgram(rv.ribbonProgram.p); gl.uniformMatrix4fv(rv.ribbonProgram.u.uVP, false, vp);
    gl.bindVertexArray(rv.ribbonVAO); gl.bindBuffer(gl.ARRAY_BUFFER, rv.ribbonBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(frame.triangles), gl.DYNAMIC_DRAW);
    gl.drawArrays(gl.TRIANGLES, 0, frame.triangles.length / 7);
  }
  if (frame.points.length) {
    const packed = new Float32Array(frame.points.length * 9);
    frame.points.forEach((v, i) => packed.set([...v.p, ...v.c, v.a, v.s, v.k], i * 9));
    gl.useProgram(rv.pointProgram.p); gl.uniformMatrix4fv(rv.pointProgram.u.uVP, false, vp);
    gl.uniform1f(rv.pointProgram.u.uHeight, height);
    gl.bindVertexArray(rv.pointVAO); gl.bindBuffer(gl.ARRAY_BUFFER, rv.pointBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, packed, gl.DYNAMIC_DRAW); gl.drawArrays(gl.POINTS, 0, frame.points.length);
  }
  gl.bindVertexArray(null); gl.disable(gl.BLEND); gl.depthMask(true); gl.enable(gl.CULL_FACE);
}

// Explicit 2D ambient preview for browsers without WebGL. The underlying model
// remains a fixed render: no simulated attack or false 3D occlusion is advertised.
function rvPreview(dt, force = false) {
  if (!compatible || !rv.overlay) return;
  if (!ready) { rv.overlay.hidden = true; return; }
  if (rv.stateKey !== `${meta?.id}/${mutation}`) { rv.previewTime = 0; rvSyncUI(); }
  if (rv.previewPlaying && !document.hidden) rv.previewTime += dt;
  const stamp = rv.reduced ? 0 : rv.previewTime;
  if (!force && stamp === rv.lastPreview) return;
  rv.lastPreview = stamp;
  rv.overlay.hidden = !rv.enabled || rv.intensity <= 0;
  const rect = stage.getBoundingClientRect(), dpr = Math.min(devicePixelRatio || 1, 1.5);
  const W = Math.max(1, Math.round(rect.width * dpr)), H = Math.max(1, Math.round(rect.height * dpr));
  if (rv.overlay.width !== W || rv.overlay.height !== H) { rv.overlay.width = W; rv.overlay.height = H; }
  const ctx = rv.overlay.getContext('2d');
  if (!ctx) return;
  ctx.clearRect(0, 0, W, H);
  const frame = rvBuildFrame(true); rv.points = fxCount = frame.points.length; rv.triangles = frame.triangles.length / 21;
  const scale = Math.min(W / 5.2, H / 4.3), cx = W * .5, cy = H * .58;
  const project = p => [cx + (p[0] - p[2] * .20) * scale, cy - (p[1] - .88) * scale + p[2] * scale * .16];
  const rgb = c => c.map(v => Math.round(rvClamp(v) * 255)).join(',');
  ctx.save();ctx.globalCompositeOperation = 'source-over';
  const faces=[];
  for(let i=0;i<frame.triangles.length;i+=21)faces.push(frame.triangles.slice(i,i+21));
  faces.sort((a,b)=>(b[2]+b[9]+b[16])-(a[2]+a[9]+a[16]));
  for(const face of faces){ctx.beginPath();face.forEach((_,i)=>{if(i%7===0){const q=project(face.slice(i,i+3));if(i===0)ctx.moveTo(...q);else ctx.lineTo(...q);}});ctx.closePath();ctx.fillStyle=`rgba(${rgb(face.slice(3,6))},${face[6]})`;ctx.fill();}

  // Leave the fixed character's central face/body clear, keeping the aura peripheral.
  // Soft silhouette protection is applied after drawing; never a hard-edged cutout.
  for (const v of frame.points.slice().sort((a,b) => b.p[2] - a.p[2])) {
    const [x, y] = project(v.p), radius = Math.max(1, v.s * scale * 1.8), c = rgb(v.c);
    const gradient = ctx.createRadialGradient(x, y, 0, x, y, radius);
    gradient.addColorStop(0, `rgba(${c},${v.a * (v.k === 3 ? .30 : 1)})`);
    gradient.addColorStop(.30, `rgba(${c},${v.a * .34})`);gradient.addColorStop(1, `rgba(${c},0)`);
    ctx.fillStyle = gradient;ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    if (v.k === 2) {ctx.strokeStyle=`rgba(${c},${v.a * .8})`;ctx.lineWidth=Math.max(.7,dpr*.75);ctx.beginPath();ctx.arc(x,y,radius*.64,0,Math.PI*2);ctx.stroke();}
    if (v.k === 4) {ctx.strokeStyle=`rgba(${c},${v.a})`;ctx.lineWidth=dpr;ctx.beginPath();ctx.moveTo(x-radius*.6,y);ctx.lineTo(x+radius*.6,y);ctx.moveTo(x,y-radius*.6);ctx.lineTo(x,y+radius*.6);ctx.stroke();}
  }
  for (const ring of frame.rings) {
    ctx.beginPath();
    for (let i=0;i<=80;i++) {
      const a=ring.start+i*ring.length/80,x=Math.cos(a)*ring.radius,z=Math.sin(a)*ring.radius;
      const pos=[ring.c[0]+x*Math.cos(ring.spin)-z*Math.cos(ring.tilt)*Math.sin(ring.spin),ring.c[1]+z*Math.sin(ring.tilt),ring.c[2]+x*Math.sin(ring.spin)+z*Math.cos(ring.tilt)*Math.cos(ring.spin)];
      const q=project(pos);if(i===0)ctx.moveTo(...q);else ctx.lineTo(...q);
    }
    ctx.strokeStyle=`rgba(${rgb(ring.color)},${Math.min(.7,ring.alpha)})`;
    ctx.lineWidth=Math.max(.65,ring.w*scale*2);ctx.stroke();
  }
  ctx.restore();

}

initRarityControls();
try {
  const r=await fetch('./catalog.json');if(!r.ok)throw Error('Manifest inaccessible');manifest=await r.json();manifest.species.forEach(s=>s.clips.push({id:'Spawn',label:'Apparition V4',duration:2.4,loop:false,events:[]}));
  $('family').innerHTML='<option value="all">Toutes les familles</option>'+manifest.families.map(f=>`<option value="${f.id}">${f.name} · 8</option>`).join('');
  renderCatalogue();
  $('mutations').innerHTML=manifest.mutations.map((m,i)=>`<button data-mutation="${i}" aria-pressed="false"><span class="swatch" style="background:${mutationColors[i]}"></span>${m}</button>`).join('');
  document.querySelectorAll('[data-mutation]').forEach(b=>b.onclick=()=>setMutation(+b.dataset.mutation));
  const [id,v]=location.hash.slice(1).split('/');mutation=/^[0-4]$/.test(v||'')?+v:0;
  try{if(new URLSearchParams(location.search).has('compatible'))compatible=true;else initGL();}catch(e){console.warn('WebGL init',e);compatible=true;}
  await loadSpecies(id);requestAnimationFrame(tick);
}catch(error){problem(error);}
