// Six art-directed evolutions. All detail stays on the existing skinned meshes.
export const designs = {
 18:{kind:1,name:'Obsidien',stages:['Verre volcanique','Obsidienne azur','Or sous la roche','Cœur de réacteur','Noyau de supernova'],notes:['Roche noire polie, éclats violets.','Veines de saphir sous la roche.','Fissures dorées et pointes métalliques.','Cœur acide sous une croûte sombre.','Fissures incandescentes, verre cosmique et cristaux allongés.'],palettes:[['#171b2a','#39334f','#a489db'],['#071a32','#163e73','#61d9ff'],['#231807','#6a481a','#ffcd62'],['#102017','#24491f','#c9ff3b'],['#090c27','#302052','#ff947c']]},
 19:{kind:2,name:'Géodelle',stages:['Améthyste brute','Géode de saphir','Citrine impériale','Cristal d’uranium','Opale astrale'],notes:['Corps améthyste, cristaux laiteux.','Couches de saphir et facettes bleues.','Citrine profonde, inclusions et arêtes dorées.','Couches émeraude et cœur lumineux.','Cristaux opalins agrandis, strates multicolores et éclat intérieur.'],palettes:[['#533066','#bb79ca','#ebd2ff'],['#102858','#398acc','#b8faff'],['#683819','#d99a32','#fff2af'],['#163824','#64b835','#dfff82'],['#172c61','#ac73df','#84f4e5']]},
 32:{kind:3,name:'Phénicendre',stages:['Braise vivante','Flamme bleue','Phénix solaire','Feu alchimique','Phénix stellaire'],notes:['Plumage de cuivre et braises sous la peau.','Flammes bleues dessinées dans le corps.','Plumage d’or déployé et cœur de feu.','Feu vert et pointes de plumes sombres.','Ailes élargies, plumes incandescentes et corps de nuit traversé de flammes.'],palettes:[['#58180e','#ca4720','#ffb351'],['#081d50','#175dbd','#7ae7ff'],['#6e2509','#ee931b','#ffec9e'],['#173c16','#8fbd22','#ecff85'],['#100e32','#673465','#ffa969']]},
 37:{kind:4,name:'Aurorine',stages:['Givre nacré','Glace boréale','Aurore solaire','Aurore ionique','Nuit polaire'],notes:['Peau glacée et couronne satinée.','Glace profonde et reflets turquoise.','Nacre dorée et lignes de lumière.','Reflets vert électrique sous la glace.','Aurores fluides incrustées dans le corps et crête irisée.'],palettes:[['#397c91','#a6d5d6','#e0fcff'],['#103957','#4facc8','#bcfaff'],['#64503a','#d9bc81','#fff2c5'],['#143b3e','#5bbd84','#d9ff9b'],['#071b38','#366282','#87ffdf']]},
 90:{kind:5,name:'Séraphine',stages:['Plume de nacre','Séraphine azurée','Séraphine souveraine','Séraphine émeraude','Séraphine céleste'],notes:['Nacre rosée et ailes douces.','Porcelaine bleue et nervures argentées.','Ailes plus amples, filigranes d’or et poitrine nacrée.','Jade lumineux et plumes aux pointes d’émeraude.','Grandes ailes opalines, nervures dorées et reflets célestes dans la nacre.'],palettes:[['#aa8296','#eed4dc','#fff1da'],['#406e9c','#c3e4f2','#e9f9ff'],['#9b6830','#f1daa5','#fff0c8'],['#326458','#b3e5ba','#e5ffd4'],['#696799','#e0d8ef','#b8fff1']]},
 96:{kind:6,name:'Astraroi',stages:['Prince astral','Roi de saphir','Empereur solaire','Roi alchimiste','Souverain du cosmos'],notes:['Velours prune et insignes royaux.','Saphir royal et ornements argentés.','Plastron d’or gravé et diadème renforcé.','Armure noire et émeraude lumineuse.','Corps bleu nuit, plastron céleste, ailes déployées et diadème opalin.'],palettes:[['#312045','#79507d','#e3ba75'],['#0d234c','#305e9e','#a6d9ff'],['#39250f','#ad7427','#ffe19b'],['#10281f','#42673a','#d6fb73'],['#080f2d','#273465','#f7d6a0']]}
};
export const linearColor = h => h.slice(1).match(/../g).map(x=>Math.pow(parseInt(x,16)/255,2.2));

export const designVertexUniforms = `
uniform highp int uDesign; uniform float uTier,uPart,uBodyTop;
out vec3 vRest;
vec3 evolve(vec3 p) {
 if(uDesign==0) return p;
 float level=uTier/4.;
 // Enlarge the existing crown above the forehead; facial vertices stay fixed.
 float crown=smoothstep(uBodyTop*.88,uBodyTop*1.13,p.y);
 if(uDesign==1||uDesign==2){p.y+=max(0.,p.y-uBodyTop*.86)*level*.55;p.x*=1.+crown*level*.10;}
 if(uDesign==3||uDesign==5||uDesign==6){
  float side=smoothstep(.58,.98,abs(p.x))*(1.-smoothstep(.2,.55,p.z));
  p.x+=sign(p.x)*max(0.,abs(p.x)-.55)*side*level*.28;
  p.y+=side*level*.20;
  if(uDesign==6)p.y+=max(0.,p.y-uBodyTop)*level*.32;
 }
 if(uDesign==4){p.y+=max(0.,p.y-uBodyTop*.85)*level*.28;p.x*=1.+crown*level*.1;}
 return p;
}`;

export const designFragmentUniforms = `
uniform highp int uDesign;
uniform float uTier,uPart,uClock,uBodyTop;
uniform vec3 uDeep,uLight,uGlow;
in vec3 vRest;
float hash21(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
float noise3(vec3 p){vec3 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
 float a=hash21(i.xy+i.z*37.),b=hash21(i.xy+vec2(1,0)+i.z*37.),c=hash21(i.xy+vec2(0,1)+i.z*37.),d=hash21(i.xy+1.+i.z*37.);
 float e=hash21(i.xy+(i.z+1.)*37.),g=hash21(i.xy+vec2(1,0)+(i.z+1.)*37.),h=hash21(i.xy+vec2(0,1)+(i.z+1.)*37.),j=hash21(i.xy+1.+(i.z+1.)*37.);
 return mix(mix(mix(a,b,f.x),mix(c,d,f.x),f.y),mix(mix(e,g,f.x),mix(h,j,f.x),f.y),f.z);}
float fbm(vec3 p){return noise3(p)*.57+noise3(p*2.04)*.28+noise3(p*4.1)*.15;}
float seam(vec2 p){vec2 cell=floor(p),f=fract(p);float d1=10.,d2=10.;
 for(int y=-1;y<=1;y++)for(int x=-1;x<=1;x++){vec2 o=vec2(float(x),float(y));vec2 rnd=vec2(hash21(cell+o),hash21(cell+o+17.));float d=length(o+rnd-f);if(d<d1){d2=d1;d1=d;}else d2=min(d2,d);}
 return 1.-smoothstep(.018,.055,d2-d1);}
// Returns albedo; separate emission/roughness keep the face readable.
vec3 designSurface(vec3 N,vec3 V,out vec3 glow,out float rough,out float metal){
 vec3 p=vRest;float level=uTier/4.,y=p.y/max(.1,uBodyTop);
 bool body=uPart<.5;
 bool facial=uPart>2.5&&uPart<5.5&&!(abs(p.x)>.65&&p.z<.25);
 glow=vec3(0);rough=.3;metal=.25;
 if(facial){rough=.18;metal=.05;return vec3(-1);}
 float f=fbm(p*3.),rim=pow(1.-max(dot(N,V),0.),2.5);
 float face=1.-smoothstep(.34,.60,p.z)*(1.-smoothstep(.45,.65,abs(p.x)))*smoothstep(.30,.48,y)*(1.-smoothstep(.68,.87,y));
 vec3 a=mix(uDeep,uLight,.30+.35*f);float mask=0.;
 if(uDesign==1){
  float cracks=seam(p.xy*3.8+vec2(f*.9,p.z*1.8));
  a=mix(uDeep,uLight,pow(f,2.)*.5);mask=cracks*face;
  rough=.16+f*.18;metal=.48;
  if(!body){a=mix(uDeep,uLight,.18+.7*abs(N.y));mask*=.4;}
 }
 if(uDesign==2){
  float bands=.5+.5*sin(y*32.+f*8.+p.x*4.);
  a=mix(uDeep,uLight,smoothstep(.2,.85,bands));
  mask=pow(bands,18.)*face;rough=.12;metal=.3;
  if(!body){a=mix(uLight,uGlow,.25+.35*abs(N.x));mask=pow(max(0.,1.-abs(N.y)),5.)*.35;}
 }
 if(uDesign==3){
  float angle=atan(p.x,p.z);
  float tongue=pow(.5+.5*sin(angle*9.+sin(y*7.-uClock*.4)*.6),3.);
  float edge=.19+.30*tongue;
  float ember=1.-smoothstep(edge-.03,edge+.025,y);
  mask=exp(-abs(y-edge)*70.)*face;
  a=mix(uDeep,uLight,.12+ember*.70);rough=.24;metal=.36;
  if(!body){float rib=pow(.5+.5*sin(y*36.+abs(p.x)*9.),22.);mask=rib*.48;
   a=mix(uLight,uDeep,smoothstep(.65,1.9,abs(p.x))*.8);a=mix(a,uGlow,rib*.45);rough=.2;}
 }
 if(uDesign==4){
  float wave=.5+.5*sin(p.x*5.+y*9.+f*4.+uClock*.3);
  vec3 violet=vec3(.32,.12,.65),mint=vec3(.08,.85,.54);
  vec3 aurora=mix(violet,mint,wave);
  a=mix(uDeep,uLight,.2+.45*wave);
  if(uTier>2.5)a=mix(a,aurora,.24*face+.25*rim);
  mask=pow(wave,9.)*face*.7;rough=.16;metal=.15;
 }
 if(uDesign==5){
  float chevron=abs(sin(y*34.+abs(p.x)*11.));
  a=mix(uDeep,uLight,.48+.20*f);a=mix(a,uGlow,rim*.16);
  mask=pow(chevron,30.)*face*.32;rough=.24;metal=.28;
  if(!body){a=mix(uLight,uDeep,smoothstep(.8,1.95,abs(p.x))*.6);mask=pow(chevron,24.)*.30;metal=.55;
   if(uTier>1.5)a=mix(a,vec3(.82,.53,.16),mask*.85);}
  if(uPart>6.5){a=uTier>1.5?vec3(.72,.46,.13):uLight;metal=.8;rough=.16;}
  if(uTier>3.5)a+=vec3(.12,.03,.20)*rim;
 }
 if(uDesign==6){
  float breast=abs(y-.38-abs(p.x)*.27);
  float filigree=pow(.5+.5*cos(p.x*22.+sin(y*22.)*2.),22.);
  mask=(1.-smoothstep(.014,.035,breast))+filigree*.22*face;
  a=mix(uDeep,uLight,.12+.35*f);rough=.22;metal=.6;
  if(!body){a=mix(uLight,uGlow,.45+.4*abs(N.y));mask*=.3;metal=.8;}
 }
 // Normal is rich but calm; each tier unlocks stronger inlaid detail and finish.
 float detail=.10+level*.75;
 a=mix(a,uGlow,clamp(mask*detail*.55,0.,.7));
 glow=uGlow*mask*(.08+level*.72)*(1.+.08*sin(uClock*1.4+y*5.));
 if(uTier>3.5){
  float stars=step(.994,hash21(floor(p.xy*65.+p.z*7.)))*face;
  if(uDesign!=1&&uDesign!=3)glow+=uGlow*stars*.55;
  glow+=uGlow*rim*.08;
 }
 if(uTier>1.5&&uTier<2.5){metal=max(metal,.72);rough*=.72;}
 return a;
}`;
