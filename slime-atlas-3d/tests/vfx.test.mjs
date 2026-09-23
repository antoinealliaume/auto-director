import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {buildFrame,motion,signatures} from '../v4/vfx.js';

const clips=['Idle','Move','Attack','Special','React','Interact','Spawn'];
const hash=frame=>createHash('sha256').update(JSON.stringify(frame.triangles.map((v,i)=>i%7<3?+v.toFixed(5):0))).digest('hex');
test('all 96 species, 5 tiers, 7 clips: finite bounded solid geometry',()=>{
 for(let number=1;number<=96;number++)for(let tier=0;tier<5;tier++)for(const clip of clips)for(const time of [0,.9,1.65,3.2]){
  const frame=buildFrame({number,tier,clip,time});
  assert.equal(frame.points.length,0);
  assert.ok(frame.triangles.length>0,`${number}/${tier}/${clip}`);
  assert.equal(frame.triangles.length%21,0);
  assert.ok(frame.triangles.length/21<3000);
  assert.ok(frame.triangles.every(Number.isFinite));
  for(let i=0;i<frame.triangles.length;i+=7)assert.ok(Math.hypot(...frame.triangles.slice(i,i+3))<8);
 }
});
test('every species has distinct geometry, ignoring color, in every tier',()=>{
 assert.equal(new Set(signatures.map(s=>s.title)).size,96);
 for(let tier=0;tier<5;tier++){
  const hashes=signatures.map((_,i)=>hash(buildFrame({number:i+1,tier,time:1.2,clip:'Special'})));
  assert.equal(new Set(hashes).size,96);
 }
});
test('rarity changes geometry, not just color; scrubbing is deterministic',()=>{
 for(let number=1;number<=96;number++){
  assert.equal(new Set(Array.from({length:5},(_,tier)=>hash(buildFrame({number,tier,time:1.1,clip:'Attack'})))).size,5);
  const options={number,tier:4,time:1.3,clip:'Attack'};
  const first=buildFrame(options);buildFrame({...options,time:2.9});
  assert.deepEqual(buildFrame(options),first);
 }
});
test('reduced motion freezes effects and body; disabled intensity removes geometry',()=>{
 for(let number=1;number<=96;number++){
  const args={number,tier:4,reduced:true,clip:'Attack'};
  assert.deepEqual(buildFrame({...args,time:0}),buildFrame({...args,time:2}));
  assert.deepEqual(motion(number,4,0,3.2,'Move',true),motion(number,4,2,3.2,'Move',true));
  assert.equal(buildFrame({number,tier:4,time:1,intensity:0}).triangles.length,0);
 }
});
test('spawn grows geometry; impact and movement change poses; unknown species fail loudly',()=>{
 for(let number=1;number<=96;number++){
  assert.notEqual(hash(buildFrame({number,tier:4,time:0,clip:'Spawn'})),hash(buildFrame({number,tier:4,time:2,clip:'Spawn'})));
  assert.notDeepEqual(motion(number,4,.1,3.2,'Move'),motion(number,4,1.1,3.2,'Move'));
 }
 assert.throws(()=>buildFrame({number:97,tier:0,time:0}),/Missing/);
});
