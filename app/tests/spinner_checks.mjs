import assert from 'node:assert/strict';
import {COLORS,SLICE,normalize,pointerIndex,sectorPath,randomIndex,createSpinPlan,easeOut,labelColor,luminance} from '../web/spinner-core.mjs';
assert.equal(COLORS.length,16);
assert.equal(new Set(COLORS.map(color=>color.hex)).size,16);
assert.equal(new Set(COLORS.map(color=>color.name)).size,16);
assert.equal(SLICE,22.5);
for(let index=0;index<16;index++) {
  for(const start of [0,13.7,359.99,10524.2,-22.5])for(const jitter of [-SLICE*.3,0,SLICE*.3]) {
    const plan=createSpinPlan(index,start,9,jitter);
    assert.equal(pointerIndex(plan.end),index);
    assert.equal(pointerIndex(normalize(plan.end)),index);
    assert.ok(plan.end-plan.start>=9*360);
  }
  assert.ok(!sectorPath(index).includes('NaN'));
  const color=COLORS[index],text=labelColor(color.hex),levels=[luminance(color.hex),luminance(text)].sort((a,b)=>a-b);
  assert.ok((levels[1]+.05)/(levels[0]+.05)>=4.5,`${color.name} label contrast`);
}
for(let index=0;index<16;index++)assert.equal(randomIndex(16,{getRandomValues(array){array[0]=index;}}),index);
let attempt=0;assert.equal(randomIndex(3,{getRandomValues(array){array[0]=attempt++===0?4294967295:5;}}),2);assert.equal(attempt,2);
assert.equal(easeOut(0),0);assert.equal(easeOut(1),1);assert.equal(easeOut(2),1);
const distances=Array.from({length:10},(_,index)=>easeOut((index+1)/10)-easeOut(index/10));
for(let index=1;index<distances.length;index++)assert.ok(distances[index]<distances[index-1]);
assert.ok(createSpinPlan(3,0,0).end<360);
for(const index of [-1,16,.5])assert.throws(()=>createSpinPlan(index));
assert.throws(()=>createSpinPlan(0,0,9,SLICE));
console.log('PASS: spinner geometry for all 16 colors, 240 landing plans, contrast, random choice, reduced-motion landing, and smooth deceleration.');
