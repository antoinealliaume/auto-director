// V4: solid, articulated scene geometry. No orbit/point-sprite fallback.
// Everything is evaluated from clip time, including assembly and disintegration.
const TAU = Math.PI * 2;
const clamp = x => Math.max(0, Math.min(1, x));
const smooth = x => { x=clamp(x); return x*x*(3-2*x); };
const pulse = (u,a,b) => Math.sin(Math.PI*clamp((u-a)/(b-a)));
const fract = x => x-Math.floor(x);
const titles = [
 'Germination en deux feuilles','Lotus qui se déploie','Trèfle à quatre battants','Frondes qui se déroulent','Salve d’aiguilles','Champignon à soufflet','Branches qui poussent','Piège de ronces',
 'Coquille qui claque','Corail en croissance','Vague qui déferle','Projecteur abyssal','Coquille télescopique','Nageoires en vol','Branchies en éventail','Tentacules préhensiles',
 'Piliers de quartz','Faille d’obsidienne','Géode qui éclot','Cubes qui s’assemblent','Miroirs à bascule','Bouclier d’ardoise','Prison d’ambre','Attraction de lingots',
 'Langues de braise','Éruption de caldeira','Cheminée de charbon','Fouet de flammes','Rideau de cendres','Coulée de lave','Bombes de scorie','Renaissance du phénix',
 'Bois de givre','Igloo qui se construit','Flocon ramifié','Iceberg qui surgit','Rideaux d’aurore','Défenses jaillissantes','Avalanche de neige','Banquise qui se fracture',
 'Moustaches à percussion','Double saut du lapin','Éventail de queues','Alvéoles qui se ferment','Élytres lumineux','Carapace qui se verrouille','Métamorphose papillon','Piqué du dragon',
 'Donut qui rebondit','Macaron qui se sépare','Mochi qui s’étire','Gaufre en dominos','Cerises pendulaires','Chantilly qui se visse','Popcorn qui éclate','Sorbet qui fond',
 'Envol de chauves-souris','Drap spectral','Lanternes à volets','Mâchoire de citrouille','Œil qui focalise','Plumes en rafale','Mâchoires du loup','Croissant qui tranche',
 'Jets de venin','Champignons qui sporulent','Branchies qui expulsent','Pinces qui cisaillent','Cloche de méduse','Sangsue qui rampe','Pustules qui éclatent','Hydre à trois souffles',
 'Boulons à percussion','Engrenages emboîtés','Batteries à pistons','Aimant qui soulève','Hélice qui décolle','Radar à panneaux','Cloche qui oscille','Horloge à échappement',
 'Satellite déployable','Météores en chute','Comète traversante','Nova à huit pointes','Planète à anneau brisé','Astéroïdes en collision','Pulsar à deux jets','Éclipse qui se referme',
 'Couronne qui se forge','Six ailes séraphiques','Corne de foudre','Dragon du ciel','Stèles qui s’éveillent','Griffes du griffon','Pyramide du sphinx','Trône astral qui se bâtit'
];
const moves = ['bond enraciné','ouverture et suspension','bascule latérale','ondulation','recul puis projection','compression puis détente','élévation progressive','fermeture puis libération'];
const tiers = ['croissance naturelle','dédoublement en écho','assemblage mécanique','rupture et repousse','pliage spatial'];
export const signatures = titles.map((title,i)=>({id:`s${String(i+1).padStart(3,'0')}`,title,movement:moves[i%8],mechanism:i+1}));
export function describe(number,tier,clip='Idle') {
 const s=signatures[number-1];
 const action={Idle:'La structure respire et se transforme.',Move:`Déplacement : ${s.movement}.`,Attack:'Préparation, déploiement offensif, puis repli.',Special:'Déploiement complet de la structure.',React:'La structure se brise et se reconstitue.',Interact:'La créature présente et replie sa signature.',Spawn:'La structure se construit avec la créature.'}[clip];
 return `${s.title} · ${tiers[tier]}. ${action}`;
}
export function motion(number,tier,t,duration,clip,reduced=false) {
 if(reduced)return {translation:[0,0,0],scale:[1,1,1],angle:0};
 const u=clamp(t/duration), k=(number-1)%8, f=Math.floor((number-1)/8), a=TAU*t/(2.4+f*.13), hit=pulse(u,.3,.8);
 let x=0,y=0,z=0,sx=1,sy=1,angle=0;
 if(clip==='Move') {
  switch(k){
   case 0:y=.36*Math.abs(Math.sin(a));z=.2*Math.sin(a);sy=1-.16*Math.cos(a*2);break;
   case 1:y=.22+.12*Math.sin(a);angle=.12*Math.sin(a);break;
   case 2:x=.34*Math.sin(a);angle=-.18*Math.sin(a);break;
   case 3:z=.3*Math.sin(a);sx=1+.12*Math.sin(a);sy=1-.1*Math.sin(a);break;
   case 4:z=.48*Math.sin(a)**3;angle=.1*Math.cos(a);break;
   case 5:y=.22*Math.abs(Math.sin(a));sx=1+.2*Math.cos(a*2);sy=1-.2*Math.cos(a*2);break;
   case 6:y=.25+.2*Math.sin(a*.65);x=.18*Math.cos(a*.65);break;
   case 7:x=.22*Math.sin(a);z=.25*Math.sin(a*2);angle=.15*Math.cos(a);break;
  }
 } else if(['Attack','Special'].includes(clip)) {
  const prep=pulse(u,0,.4), release=pulse(u,.35,.85);
  sx+=prep*.12;sy-=prep*.16;
  if(k===0||k===5){y=hit*(.35+f*.025);z=release*.3;}
  else if(k===1||k===6){y=hit*.3;sy+=release*.18;}
  else if(k===2||k===7){angle=release*(k===2?-.25:.25);x=release*.2;}
  else {z=release*.5-prep*.12;angle=release*.12;}
 } else if(clip==='React'){z=-pulse(u,0,.65)*.25;angle=pulse(u,0,.6)*.22;}
 else if(clip==='Spawn'){const g=smooth(u/.7);y=(1-g)*(k%2?1.5:-.35);sx=sy=.06+.94*g;angle=(1-g)*(k-3)*.2;}
 else if(clip==='Interact'){angle=.12*Math.sin(TAU*u);y=.1*pulse(u,0,1);}
 else {sy+=.015*Math.sin(a+k);angle=.015*Math.sin(a*.7+k);}
 // Mutation changes timing/physical response, never adds a common orbit.
 if(tier===1){x*=.7;y*=1.25;}
 if(tier===2){angle=Math.round(angle*30)/30;}
 if(tier===3){sx+=.025*Math.sin(a*3+k);sy-=.025*Math.sin(a*3+k);}
 if(tier===4&&clip==='Move'){const jump=smooth((fract(t/(1.3+f*.1))-.72)/.16);sx*=1-.72*Math.sin(jump*Math.PI);x+=(jump-.5)*.2*(k%2?1:-1);}
 return {translation:[x,y,z],scale:[sx,sy,1],angle};
}

export function buildFrame({number,tier,time,duration=3.2,clip='Idle',radius=1,intensity=1,quality=1,reduced=false,colors,accessories=true}) {
 const out={points:[],triangles:[],rings:[],mechanism:number,version:4};
 if(intensity<=0)return out;
 const t=reduced?0:time,u=reduced?.25:clamp(time/duration),n=number;
 const active=['Attack','Special'].includes(clip), hit=active?pulse(u,.25,.85):0;
 const special=clip==='Special'?1.35:1;
 const cycle=.5+.5*Math.sin(t*2.1+n*.27), open=.35+.25*cycle+.75*hit;
 const spawn=clip==='Spawn'?.03+.97*smooth(u/.75):1;
 const react=clip==='React'?pulse(u,0,.8):0;
 const grow=spawn*(.82+tier*.055), reach=(.8+.22*tier)*special;
 const C=colors||[[.4,.9,.65],[.8,.95,1],[1,.65,.3]];
 const alpha=clamp(.63*intensity)*(reduced?.8:1);
 const root=motion(number,tier,t,duration,clip,reduced);
 const detail=quality<.7?5:9;
 const transform=p=>{
  let [x,y,z]=p;
  if(tier===1){y+=.06*Math.sin(t*1.5+z*3+n);}
  if(tier===2){y=Math.round(y*28)/28;}
  if(tier===3){const q=1+.10*Math.sin(t*3+Math.floor(y*4)+n);x*=q;z*=q;y+=.05*Math.sin(x*7+t*2);}
  if(tier===4){const twist=.22*Math.sin(t*1.4+n*.4+y*2);const ox=x;x=x*Math.cos(twist)-z*Math.sin(twist);z=ox*Math.sin(twist)+z*Math.cos(twist);}
  const spread=1+react*.5;x*=spread*grow;y*=grow;z*=spread*grow;
  const ca=Math.cos(root.angle),sa=Math.sin(root.angle),xx=x*root.scale[0],yy=y*root.scale[1];
  return [(xx*ca-yy*sa+root.translation[0])*radius,(xx*sa+yy*ca+root.translation[1])*radius,(z+root.translation[2])*radius];
 };
 const tri=(a,b,c,col=C[0],shade=1)=>{for(const p of [a,b,c])out.triangles.push(...transform(p),...col.map(v=>v*shade),alpha);};
 const quad=(a,b,c,d,col=C[0],shade=1)=>{tri(a,b,c,col,shade);tri(a,c,d,col,shade);};
 const box=(x,y,z,w,h,d,col=C[0],a=0)=>{
  const p=[];for(const [i,j,k]of [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]]){const xx=i*w/2,yy=j*h/2;p.push([x+xx*Math.cos(a)-yy*Math.sin(a),y+xx*Math.sin(a)+yy*Math.cos(a),z+k*d/2]);}
  for(const [i,f]of [[0,[0,1,2,3]],[1,[4,7,6,5]],[2,[0,4,5,1]],[3,[3,2,6,7]],[4,[0,3,7,4]],[5,[1,5,6,2]]])quad(...f.map(j=>p[j]),col,.55+i*.08);
 };
 const spear=(a,b,w,col=C[0],sides=5)=>{
  const v=b.map((x,i)=>x-a[i]),l=Math.hypot(...v)||1,axis=v.map(x=>x/l),ref=Math.abs(axis[1])>.9?[1,0,0]:[0,1,0];
  const cross=(x,y)=>[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]];
  let e=cross(axis,ref);const el=Math.hypot(...e);e=e.map(x=>x/el);const f=cross(axis,e),ring=[];
  for(let i=0;i<sides;i++){const a0=i*TAU/sides;ring.push(a.map((x,j)=>x+w*(e[j]*Math.cos(a0)+f[j]*Math.sin(a0))));}
  for(let i=0;i<sides;i++){tri(ring[i],ring[(i+1)%sides],b,col,.6+.4*i/sides);tri(ring[(i+1)%sides],ring[i],a,col,.45);}
 };
 const leaf=(a,b,w,col=C[0],bend=.15)=>{const m=a.map((x,i)=>(x+b[i])/2);m[2]+=bend;const l=[m[0]-w,m[1],m[2]],r=[m[0]+w,m[1],m[2]];tri(a,l,m,col,.7);tri(l,b,m,col,.95);tri(b,r,m,col,1);tri(r,a,m,col,.65);};
 const path=(fn,w,col=C[0],steps=detail)=>{for(let i=0;i<steps;i++){const a=fn(i/steps),b=fn((i+1)/steps);spear(a,b,w*(1-.65*i/steps),col,4);}};
 const fan=(x,y,z,count,span,len,col=C[0],phase=0)=>{for(let i=0;i<count;i++){const a=-span/2+span*i/Math.max(1,count-1)+phase;leaf([x,y,z],[x+Math.sin(a)*len,y+Math.cos(a)*len,z+.12*Math.sin(i+t)],.14,col);}};
 const wings=(count,len,flap,col=C[0])=>{for(let side of [-1,1])for(let i=0;i<count;i++){const y=.9+i*.18;leaf([side*.35,y,-.15],[side*(.7+len*Math.cos(flap+i*.18)),y+len*Math.sin(flap+i*.18),-.25-i*.13],.22,col,.3);}};
 const flower=(count,y,r,col=C[0],fold=0)=>{for(let i=0;i<count;i++){const a=i*TAU/count;const base=[Math.cos(a)*.22,y,Math.sin(a)*.22];leaf(base,[Math.cos(a)*r,y+fold,Math.sin(a)*r],.22,col,.1);}};
 const dome=(x,y,z,r,h,col=C[0],cut=TAU)=>{const steps=detail*2;for(let i=0;i<steps;i++){const a=i*cut/steps,b=(i+1)*cut/steps;for(let j=0;j<4;j++){const q=j*Math.PI/8,v=(j+1)*Math.PI/8;const p=(aa,bb)=>[x+r*Math.cos(bb)*Math.cos(aa),y+h*Math.sin(bb),z+r*Math.cos(bb)*Math.sin(aa)];quad(p(a,q),p(b,q),p(b,v),p(a,v),col,.6+.1*j);}}};
 const arch=(x,y,z,r,w,start=0,end=TAU,col=C[0],vertical=false)=>{const steps=detail*3;for(let i=0;i<steps;i++){const a=start+(end-start)*i/steps,b=start+(end-start)*(i+1)/steps;const p=(a,r)=>vertical?[x+Math.cos(a)*r,y+Math.sin(a)*r,z]:[x+Math.cos(a)*r,y,z+Math.sin(a)*r];quad(p(a,r-w),p(a,r+w),p(b,r+w),p(b,r-w),col);}};
 const curtain=(x,z,w,h,col=C[0],phase=0)=>{for(let i=0;i<detail;i++){const a=i/detail,b=(i+1)/detail,p=(q,v)=>[x+(q-.5)*w,.15+v*h,z+Math.sin(q*7+t+phase)*.2*v];quad(p(a,0),p(b,0),p(b,1),p(a,1),col,.65+.35*i/detail);}};
 const burstBlocks=(count,y,col=C[0])=>{for(let i=0;i<count;i++){const a=i*2.399,q=fract(t*.55+i*.137),r=.4+q*.9;box(Math.cos(a)*r,y+Math.sin(q*Math.PI)*.7,Math.sin(a)*r,.12,.12,.12,col,a+q);}};
 // Species are explicitly authored; no hash-selected preset or modulo fallback.
 switch(n){
 case 1: for(let s of [-1,1]){path(q=>[s*q*.55,.1+q*(.8+open),0],.06,C[1]);leaf([s*.3,.65,0],[s*(.55+open*.25),1.4+hit*.4,0],.32,C[0]);}break;
 case 2: flower(8,.28,1.2,C[0],open*.8);flower(5,.48,.85,C[1],1-open);break;
 case 3: for(let i=0;i<4;i++){const a=i*Math.PI/2;leaf([0,1,-.3],[Math.cos(a)*(.65+open*.3),1+Math.sin(a)*.6,-.2],.32,C[i%2]);}box(0,.5,-.3,.06,1,.06,C[1]);break;
 case 4: for(let s of [-1,1])path(q=>[s*(q*.75),.3+Math.sin(q*2.5)*(.8+open*.4),-.25],.06,C[0]);for(let i=0;i<6;i++)fan((i%2?1:-1)*i*.09,.45+i*.15,-.25,3,1.7,.33,C[1],i*.15);break;
 case 5: for(let i=0;i<11;i++){const a=i*2.399,r=.65+hit*reach; spear([Math.cos(a)*r,.4+(i%3)*.3,Math.sin(a)*r],[Math.cos(a)*(r+.35),.55+(i%3)*.3,Math.sin(a)*(r+.35)],.06,C[i%2]);}break;
 case 6: box(0,.6,-.45,.18,.9,.18,C[1]);dome(0,1.05,-.45,.85+open*.15,.3,C[0]);for(let i=0;i<5;i++)spear([-.6+i*.3,.95,-.4],[-.6+i*.3,.5-hit*.4,-.4],.06,C[2]);break;
 case 7: path(q=>[.18*Math.sin(q*3),.2+q*1.65,-.5],.1,C[1]);for(let i=0;i<5;i++){const s=i%2?1:-1;path(q=>[s*q*(.4+i*.07),.65+i*.2+q*.3,-.5],.06,C[1]);leaf([s*.25,.8+i*.2,-.5],[s*(.6+hit*.3),1+i*.2,-.5],.25,C[0]);}break;
 case 8: for(let s of [-1,1])path(q=>[s*(1-q*open*.75),.05+q*1.6,.25*Math.sin(q*4)],.09,C[0]);for(let i=0;i<8;i++){const s=i%2?1:-1;spear([s*.9,.2+i*.17,0],[s*(.5-hit*.3),.35+i*.17,.1],.09,C[1]);}break;
 case 9: for(let s of [-1,1])fan(0,.4,.45,7,2.5,.85,C[s===1?0:1],s*(.4+open));spear([0,.5,.6],[0,.7,.9+hit*1.4],.2,C[2],8);break;
 case 10: for(let i=0;i<5;i++){const x=(i-2)*.35;path(q=>[x+Math.sin(q*3+i)*.12,.1+q*(.7+i%2*.4+hit*.3),-.4],.1,C[i%2]);fan(x,.7,-.4,3,1.8,.38,C[0]);}break;
 case 11: curtain(0,.35-hit*1.5,2,.5+open,C[0]);for(let i=0;i<5;i++)leaf([-.9+i*.45,1,.2-hit],[-.9+i*.45,.7,.65-hit],.23,C[1]);break;
 case 12: spear([0,1.45,.2],[0,.4,1.2+hit*1.5],.45,C[0],8);box(0,1.5,.1,.28,.32,.25,C[1]);break;
 case 13: for(let i=0;i<7;i++)arch(0,.45+i*.12*open,-.3,.9-i*.1,.12,i*.35,i*.35+5.3,C[i%2]);break;
 case 14: wings(3,1.05,Math.sin(t*2)*.45+hit*.6,C[0]);break;
 case 15: for(let s of [-1,1])fan(s*.5,.75,0,5,1.5,.6+hit*.45,C[s===1?0:1],s*.9);break;
 case 16: for(let i=0;i<6;i++){const a=i*TAU/6;path(q=>[Math.cos(a)*(.6+q*.5*Math.cos(open*2)),.15+q*.95,Math.sin(a)*(.6+q*.5)],.1,C[i%2]);}break;
 case 17: for(let i=0;i<7;i++){const a=i*TAU/7,h=.45+(i%3)*.3+hit*.65;spear([Math.cos(a)*.9,.05,Math.sin(a)*.9],[Math.cos(a),h,Math.sin(a)],.18,C[i%2]);}break;
 case 18: for(let s of [-1,1])for(let i=0;i<6;i++){const z=-1+i*.4,gap=.22+hit*.6;box(s*(.65+gap),.03,z,.65,.08,.36,C[1],s*hit*.25);spear([s*gap,.02,z],[s*(gap+.2),.35+hit*(i%3+1)*.3,z],.13,C[0]);}break;
 case 19: for(let i=0;i<9;i++){const a=i*TAU/9;spear([Math.cos(a)*.65,.3,Math.sin(a)*.65],[Math.cos(a)*(1+open*.35),.7+open*.7,Math.sin(a)*(1+open*.35)],.22,C[i%2]);}break;
 case 20: for(let i=0;i<8;i++){const a=(i%4-1.5)*.42;box(a*(1.5-open*.5),.3+Math.floor(i/4)*.7,-.45,.32,.32,.32,C[i%2],(1-open)*.7);}break;
 case 21: for(let i=0;i<5;i++)box((i-2)*.38,1,-.4,.34,.95,.035,C[i%3],Math.sin(t+i)*.35+hit*.8);break;
 case 22: for(let s of [-1,1])for(let i=0;i<3;i++)box(s*(.65-hit*.3),.4+i*.4,.2,.4,.36,.12,C[i%2],s*(.2+hit*.6));break;
 case 23: dome(0,.05,0,1.05,.55+open*.65,C[0],Math.PI*1.6);spear([0,1.8,0],[0,1.1-hit*.5,0],.22,C[1]);break;
 case 24: for(let i=0;i<6;i++){const a=i*TAU/6,r=1.2-hit*.7;box(Math.cos(a)*r,.25+hit*.6,Math.sin(a)*r,.2,.36,.16,C[i%2],a*hit);}break;
 case 25: for(let i=0;i<5;i++)leaf([-.6+i*.3,.15,-.3],[-.5+i*.3+Math.sin(t*3+i)*.15,.9+cycle*.4+hit*.7,-.25],.19,C[i%2]);break;
 case 26: arch(0,.08,0,.85,.22,0,TAU,C[1]);for(let i=0;i<7;i++){const a=i*2.399,q=fract(t*.65+i*.14);spear([Math.cos(a)*q,.2+Math.sin(q*Math.PI)*(1+hit),Math.sin(a)*q],[Math.cos(a)*q,.3+Math.sin(q*Math.PI)*(1+hit),Math.sin(a)*q],.13,C[0]);}break;
 case 27: for(let i=0;i<5;i++)box(Math.sin(i+t*.4)*.2,.3+i*.3,-.5,.5-i*.06,.28,.4,C[i%2],i*.2);dome(0,1.65,-.5,.4+cycle*.2,.25,C[2]);break;
 case 28: path(q=>[Math.sin(q*5+t*2)*q*(.7+hit),.5+q*.7,.3+q*reach],.16,C[0],detail*2);break;
 case 29: for(let i=0;i<4;i++)curtain((i-1.5)*.35,-.45-i*.12,.5,1.1+cycle*.4,C[i%3],i);break;
 case 30: for(let i=0;i<4;i++)path(q=>[(i-1.5)*.35+Math.sin(q*4+t)*.12,.04+Math.max(0,.7-q*1.5),q*(1+hit)],.15,C[i%2]);break;
 case 31: for(let i=0;i<5;i++){const q=fract(t*.5+i*.2),a=i*2.4;spear([Math.cos(a)*q,.2+Math.sin(q*Math.PI)*(1+hit),Math.sin(a)*q],[Math.cos(a)*q+.15,.35+Math.sin(q*Math.PI)*(1+hit),Math.sin(a)*q],.23,C[i%2]);}break;
 case 32: wings(5,1.3,Math.sin(t*2)*.5+hit*.7,C[0]);fan(0,.35,-.4,5,1.2,.9,C[1],Math.PI);break;
 case 33: for(let s of [-1,1]){path(q=>[s*(.3+q*.55),.8+q*.9,-.35],.09,C[0]);for(let i=0;i<3;i++)spear([s*(.4+i*.14),1+i*.2,-.35],[s*(.3+i*.18),1.35+i*.2+hit*.25,-.3],.08,C[1]);}break;
 case 34: for(let j=0;j<3;j++)for(let i=0;i<7;i++){const a=i*Math.PI/6;box(Math.cos(a)*(1-j*.2),.15+j*.3,Math.sin(a)*(1-j*.2)-.5,.38,.26,.27,C[j%2],hit*.2);}break;
 case 35: for(let i=0;i<6;i++){const a=i*TAU/6;path(q=>[Math.cos(a)*q,.95+Math.sin(a)*q,-.5],.05,C[0]);for(let s of [-1,1])spear([Math.cos(a)*.6,.95+Math.sin(a)*.6,-.5],[Math.cos(a+s*.4)*(.8+hit*.3),.95+Math.sin(a+s*.4)*(.8+hit*.3),-.5],.05,C[1]);}break;
 case 36: spear([0,.04,-.5],[.25,1.5+hit,-.5],.7,C[0],4);spear([-.7,.04,.1],[-.8,.7+hit*.4,.1],.3,C[1],4);break;
 case 37: for(let i=0;i<3;i++)curtain(0,-.65-i*.18,2.4,1.4+hit*.6,C[i],i*1.8);break;
 case 38: for(let s of [-1,1])path(q=>[s*(.6-q*.2),.8-q*.8+q*q*.6,.4+q*(.8+hit)],.14,C[0]);break;
 case 39: for(let i=0;i<6;i++){const q=fract(t*.35+i*.16);box((i-2.5)*.35,.12+q*.25,-1+q*2,.4,.28,.4,C[i%2],q*2);}break;
 case 40: for(let i=0;i<6;i++){const a=i*TAU/6;box(Math.cos(a)*(.7+hit*.4),.08,Math.sin(a)*(.7+hit*.4),.6,.12,.5,C[i%2],hit*(i%2?.25:-.25));}break;
 case 41: for(let s of [-1,1])for(let i=0;i<3;i++)path(q=>[s*(.25+q*.9),.8+(i-1)*q*.25+Math.sin(t*4)*q*.08,.45+hit*q*.6],.035,C[i%2]);break;
 case 42: for(let s of [-1,1]){leaf([s*.35,1,-.2],[s*(.4+hit*.25),1.8+cycle*.3,-.2],.18,C[0]);box(s*.7,.1+Math.abs(Math.sin(t*2+s))*.25,.15,.35,.14,.5,C[1]);}break;
 case 43: for(let i=0;i<3;i++)path(q=>[(i-1)*q*.6,.3+Math.sin(q*2)*(.8+hit*.5),-.3-q*.7],.24,C[i%2]);break;
 case 44: for(let i=0;i<5;i++){const x=(i-2)*.4;arch(x,1+Math.abs(i-2)*.12,-.6,.26,.085,0,TAU,C[i%2],true);}wings(1,.65,Math.sin(t*12)*.45,C[1]);break;
 case 45: for(let s of [-1,1])leaf([s*.25,.85,-.2],[s*(.8+open*.4),1.35,-.4],.4,C[0]);box(0,.6,-.65,.4,.5,.4,C[2]);break;
 case 46: for(let s of [-1,1])dome(s*(.35+open*.25),.55,-.25,.48,.6,C[s===1?0:1],Math.PI);spear([0,1,.35],[0,1.7,.65+hit*.6],.14,C[2]);break;
 case 47: wings(2,1.25,Math.sin(t*2.4)*.65,C[0]);for(let s of [-1,1])leaf([s*.3,.7,0],[s*(.9+hit*.3),.1,-.2],.35,C[1]);break;
 case 48: wings(1,.8,-.3+hit*.8,C[0]);spear([0,.9,.3],[0,.7,.9+hit*1.1],.2,C[1]);path(q=>[Math.sin(q*4)*.3,.3+q*.4,-.4-q],.1,C[2]);break;
 case 49: arch(0,.45+Math.abs(Math.sin(t*2))*.5,.15,.7,.22,0,TAU,C[0],true);for(let i=0;i<6;i++)box(Math.cos(i)*.68,.9+Math.sin(i)*.3,.16,.13,.06,.08,C[1],i);break;
 case 50: for(let s of [-1,1])dome(0,.8+s*(.2+hit*.45),-.4,.75,s*.22,C[s===1?0:1]);box(0,.8,-.4,1.1,.12,.6,C[2]);break;
 case 51: dome(0,.12,-.35,.8+cycle*.2,.55+hit*.65,C[0]);for(let s of [-1,1])leaf([0,.15,-.3],[s*1.1,.25,-.4],.28,C[1]);break;
 case 52: for(let i=0;i<5;i++)for(let j=0;j<3;j++)box((j-1)*.42,.45+i*.15,-.7+i*.32,.38,.13,.28,C[(i+j)%2],hit*Math.max(0,1-i*.15));break;
 case 53: for(let s of [-1,1]){const x=s*(.55+.2*Math.sin(t*2));path(q=>[x*q,1.6-q*.9,-.3],.04,C[1]);dome(x,.5,-.3,.3,.4,C[0]);}break;
 case 54: for(let i=0;i<8;i++){const a=i*.9+t*.3;box(Math.cos(a)*(.5-i*.05),.4+i*.14,-.4+Math.sin(a)*(.5-i*.05),.35-i*.025,.18,.3-i*.025,C[i%2],a*.2);}break;
 case 55: burstBlocks(12,.25,C[0]);for(let i=0;i<4;i++)dome((i-1.5)*.3,.3,-.4,.18,.18,C[1]);break;
 case 56: spear([0,.2,-.4],[0,1,-.4],.5,C[1],6);dome(0,1,-.4,.6,.3+open*.2,C[0]);for(let i=0;i<4;i++)box((i-1.5)*.2,.7-hit*.3,.05,.09,.45+hit*.4,.08,C[2]);break;
 case 57: for(let i=0;i<3;i++){const x=(i-1)*.85,y=1.3+Math.sin(t*3+i)*.2;for(let s of [-1,1])tri([x,y,-.4],[x+s*.5,y+.25*Math.sin(t*4+i),-.35],[x+s*.25,y-.2,-.4],C[i%2]);}break;
 case 58: curtain(0,-.35,1.5,1.6,C[0]);for(let i=0;i<5;i++)leaf([-.6+i*.3,.4,-.3],[-.6+i*.3+Math.sin(t+i)*.2,.1,-.2],.16,C[1]);break;
 case 59: for(let s of [-1,1]){box(s*.85,1.05,-.3,.35,.55,.28,C[0]);for(let j of [-1,1])box(s*.85+j*(.2+open*.1),1.05,-.1,.15,.5,.04,C[1],j*open*.5);}break;
 case 60: for(let s of [-1,1])fan(0,.65+s*open*.3,.2,5,2,.8,C[0],s*Math.PI/2);box(0,1.4,-.2,.12,.35,.12,C[1],.25);break;
 case 61: arch(0,1,.45,.5,.14,0,TAU,C[0],true);spear([0,1,.5],[0,1,.7+hit*2],.14+hit*.16,C[1],8);break;
 case 62: for(let i=0;i<7;i++){const q=fract(t*.35+i*.14);leaf([-.9+i*.3,1.1-q*.6,-.4+hit],[ -.7+i*.3,1.5-q*.6,-.5+hit*1.7],.12,C[i%2]);}break;
 case 63: for(let s of [-1,1])for(let i=0;i<5;i++)spear([-.6+i*.3,.8+s*(.15+open*.25),.35],[-.6+i*.3,.8+s*.05,.7+hit*.4],.12,C[s===1?0:1]);break;
 case 64: arch(.2*Math.sin(t),1,-.4,.9,.18,-1.1,1.1,C[0],true);spear([.6,.5,.1],[.6-hit*1.5,1.3,.3],.12,C[1]);break;
 case 65: for(let s of [-1,1])path(q=>[s*(.3+q*.3),.7+Math.sin(q*Math.PI)*.6-q*.6,.3+q*(.6+hit*1.2)],.13,C[0]);break;
 case 66: for(let i=0;i<5;i++){const x=(i-2)*.35,h=.55+(i%2)*.3;box(x,h/2,-.4,.08,h,.08,C[1]);dome(x,h,-.4,.28,.18+hit*.2,C[0]);}break;
 case 67: for(let s of [-1,1])for(let i=0;i<4;i++)leaf([s*.4,.65+i*.15,0],[s*(.9+hit*.6),.35+i*.35,.2+hit*.4],.15,C[i%2]);break;
 case 68: for(let s of [-1,1]){path(q=>[s*(.4+q*.5),.3+q*.4,.1+q*.4],.13,C[1]);for(let j of [-1,1])spear([s*.9,.7,.5],[s*(.9+j*(.2+.25*(1-hit))),.9,1.1],.18,C[0]);}break;
 case 69: dome(0,1.25,-.3,.8,.4,C[0]);for(let i=0;i<7;i++)path(q=>[(i-3)*.2+Math.sin(q*5+t*2+i)*.12,1.2-q*(.8+hit*.3),-.3],.055,C[1]);break;
 case 70: for(let i=0;i<9;i++)box((i-4)*.2,.3+Math.sin(i*.6-t*3)*.15,.3,.22,.28,.3,C[i%2],Math.cos(i*.6-t*3)*.2);break;
 case 71: for(let i=0;i<7;i++){const a=i*2.4,r=.65+hit*.7;dome(Math.cos(a)*r,.5+(i%2)*.35,Math.sin(a)*r,.22*(1-hit*.5),.3,C[i%2]);}break;
 case 72: for(let i=0;i<3;i++){const x=(i-1)*.65;path(q=>[x*q,.3+q,.1+Math.sin(q*3+t+i)*.12],.14,C[i]);spear([x,1.3,.2],[x,1.1,.4+hit*(1.3+i*.2)],.16,C[i]);}break;
 case 73: for(let s of [-1,1]){box(s*(.7+hit*.35),.75,.1,.25,.35,.35,C[0]);spear([s*.5,.75,.1],[s*(1.1+hit*.4),.75,.1],.15,C[1],6);}break;
 case 74: for(let s of [-1,1]){arch(s*.65,.85,-.3,.42,.15,0,TAU,C[0],true);for(let i=0;i<8;i++){const a=i*TAU/8+s*t;box(s*.65+Math.cos(a)*.46,.85+Math.sin(a)*.46,-.3,.15,.18,.16,C[1],a);}}break;
 case 75: for(let s of [-1,1]){box(s*.7,.75,-.25,.3,.85,.35,C[0]);box(s*.7,1.2+cycle*.2+hit*.3,-.25,.17,.25,.17,C[1]);}break;
 case 76: arch(0,1,-.3,.7,.18,0,Math.PI,C[0],true);for(let s of [-1,1])box(s*.7,.65,-.3,.35,.65,.3,C[1]);box(0,.15+hit*.5,.3,.4,.16,.25,C[2]);break;
 case 77: for(let i=0;i<3;i++){const a=t*6+i*TAU/3;leaf([0,1.6,0],[Math.cos(a)*1.15,1.6,Math.sin(a)*1.15],.18,C[i%2]);}box(0,1.4,0,.12,.4,.12,C[1]);break;
 case 78: for(let i=0;i<5;i++)box((i-2)*.28,1.35+Math.abs(i-2)*.08,-.4,.25,.6,.06,C[i%2],Math.sin(t)*.2);spear([0,1.2,-.2],[Math.sin(t)*1.1,1.2,1.2+hit],.1,C[2]);break;
 case 79: dome(Math.sin(t*2)*.25,1.15,-.3,.6,.5,C[0]);path(q=>[Math.sin(t*2+q)*q*.3,1.2-q*.7,-.3],.07,C[1]);break;
 case 80: arch(0,1,-.5,.75,.12,0,TAU,C[0],true);for(let i=0;i<2;i++){const a=Math.floor(t*(i?4:1))*Math.PI/6;spear([0,1,-.42],[Math.sin(a)*(.6-i*.2),1+Math.cos(a)*(.6-i*.2),-.42],.055,C[1]);}break;
 case 81: box(0,1.3,-.4,.35,.35,.35,C[1]);for(let s of [-1,1])for(let i=0;i<3;i++)box(s*(.4+i*.27)*open,1.3,-.4,.25,.5,.04,C[0],s*(1-open));break;
 case 82: for(let i=0;i<5;i++){const q=fract(t*.45+i*.19),x=(i-2)*.48;spear([x+.25*(1-q),2.5*(1-q),-.4],[x,.1+2*(1-q),-.2],.17+hit*.06,C[i%2]);}break;
 case 83: {const q=fract(t*.3),x=-1.7+q*3.4;spear([x,.9,.1],[x+.35,1,.1],.22,C[0]);for(let i=0;i<3;i++)leaf([x,.9,.1],[x-.9,1+(i-1)*.3,-.1],.1,C[i]);}break;
 case 84: for(let i=0;i<8;i++){const a=i*TAU/8;const r=.5+open*.55;spear([Math.cos(a)*.3,1+Math.sin(a)*.3,-.4],[Math.cos(a)*r,1+Math.sin(a)*r,-.4],.17,C[i%3]);}break;
 case 85: dome(0,.85,-.5,.55,.55,C[0]);for(let i=0;i<3;i++)arch(0,.7+i*.12,-.5,1,.10,i*2.1+hit*.2,i*2.1+1.5,C[1]);break;
 case 86: for(let s of [-1,1]){const x=s*(1-hit*.7);spear([x,.7,-.3],[x-s*.25,.95,-.1],.38,C[0],5);}burstBlocks(4,.2,C[1]);break;
 case 87: for(let s of [-1,1])spear([0,1,-.4],[0,1+s*(.7+hit*1.1),-.4],.3,C[s===1?0:1],8);arch(0,1,-.4,.5,.12,0,TAU,C[2]);break;
 case 88: for(let s of [-1,1])arch(s*(1-open)*.6,1,-.5,.9,.32,s===1?-Math.PI/2:Math.PI/2,s===1?Math.PI/2:Math.PI*1.5,C[s===1?0:1],true);break;
 case 89: arch(0,1.3,-.3,.7,.14,0,TAU,C[1]);for(let i=0;i<5;i++){const a=i*TAU/5;spear([Math.cos(a)*.7,1.3,Math.sin(a)*.7-.3],[Math.cos(a)*.7,1.7+hit*.5,Math.sin(a)*.7-.3],.16,C[0]);}break;
 case 90: wings(6,1.2,Math.sin(t*1.3)*.25+hit*.45,C[0]);break;
 case 91: path(q=>[Math.sin(q*8)*.09,.95+q*(1+hit*.4),.2+q*.3],.14,C[0]);for(let s of [-1,1])path(q=>[s*q*.9,1.4+Math.sin(q*12+t*5)*.12,.4],.035,C[1]);break;
 case 92: path(q=>[Math.sin(q*7+t)*(.6+hit*.4),.1+q*1.8,-.65],.17,C[0],detail*2);fan(.2,1.65,-.5,3,1.5,.5,C[1]);break;
 case 93: for(let i=0;i<3;i++){const x=(i-1)*.9;box(x,.65+hit*.25,-.6,.45,1.2,.18,C[0]);for(let j=0;j<3;j++)spear([x-.12,.3+j*.3,-.48],[x+.12,.5+j*.3,-.48],.045,C[1]);}break;
 case 94: wings(2,.9,.3+hit*.4,C[1]);for(let s of [-1,1])for(let i=0;i<3;i++)path(q=>[s*(.65+i*.1),.55-q*.35,.1+q*(.5+hit)],.075,C[0]);break;
 case 95: spear([0,.05,-.6],[0,1.65+hit*.4,-.6],.95,C[0],4);for(let i=0;i<4;i++)box(0,.08+i*.1,.5-i*.15,1.6-i*.3,.12,.35,C[1]);break;
 case 96: box(0,.3,-.6,1.4,.2,.85,C[1]);box(0,1.2,-.9,1.2,1.6,.18,C[0]);for(let s of [-1,1]){box(s*.75,.65,-.55,.18,.9,.7,C[1]);fan(s*.6,1.4,-.95,4,1.4,.8+hit*.4,C[2],s*.6);}break;
 default: throw new Error(`Missing V4 choreography: ${number}`);
 }
 // Echo duplicates the authored solid structure; high tiers alter its physical
 // construction above. No identical decorative aura is added to all species.
 if(tier===1&&accessories){const original=out.triangles.slice();for(let i=0;i<original.length;i+=7)out.triangles.push(original[i]*1.08,original[i+1]+.08,original[i+2]-.18,original[i+3],original[i+4],original[i+5],original[i+6]*.20);}
 return out;
}
