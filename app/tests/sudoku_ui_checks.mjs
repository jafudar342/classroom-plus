import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import * as core from '../web/sudoku-core.mjs';
const source=(await fs.readFile(new URL('../web/sudoku.mjs',import.meta.url),'utf8')).replace(/^import[^\n]+\n/,'');
const puzzle=core.createPuzzle('easy'),blank=puzzle.givens.findIndex(value=>!value),given=puzzle.givens.findIndex(Boolean),key='classroom-plus-sudoku-v1';
function setup(values=new Map()) {
 const nodes=new Map(),events={};let now=100000;
 class TestDate extends Date{static now(){return now;}}
 function element(tag='div'){return {tag,children:[],handlers:{},attrs:{},classList:{add(){},toggle(){}},value:'',disabled:false,open:false,hidden:false,
   append(...items){this.children.push(...items);},setAttribute(k,v){this.attrs[k]=String(v);},addEventListener(k,fn){this.handlers[k]=fn;},focus(){this.focused=true;},
   click(){if(!this.disabled)return this.handlers.click?.();},showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},querySelectorAll(selector){return this.children.filter(child=>child.tag===selector);}};}
 const node=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};node('sudoku-difficulty').value='easy';
 const context=vm.createContext({...core,createPuzzle:(level='easy')=>({...puzzle,level,givens:[...puzzle.givens],solution:[...puzzle.solution]}),Date:TestDate,
 document:{hidden:false,getElementById:node,createElement:element,querySelector:()=>node('sudoku-dialog').open?node('sudoku-dialog'):null,addEventListener(k,fn){events[k]=fn;}},
 window:{addEventListener(){}},localStorage:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},setInterval(){}});
 vm.runInContext(source,context);
 const cell=index=>node('sudoku-grid').children[Math.floor(index/9)].children[index%9];
 return {node,cell,events,context,values,game:()=>JSON.parse(values.get(key)),advance:ms=>now+=ms,open:()=>node('sudoku-trigger').click(),
  key(value){node('sudoku-grid').handlers.keydown({key:value,ctrlKey:false,metaKey:false,altKey:false,preventDefault(){}});}};
}
{
 const app=setup();app.open();assert.equal(app.node('sudoku-grid').children.length,9);assert.equal(app.cell(blank).attrs['aria-readonly'],'false');
 app.cell(given).click();app.key('9');assert.deepEqual(app.game().board,puzzle.givens);
 app.cell(blank).click();app.node('sudoku-notes').click();app.key('3');assert.equal(app.game().notes[blank],4);assert.equal(app.game().board[blank],0);
 app.node('sudoku-notes').click();app.key(String(puzzle.solution[blank]));assert.equal(app.game().board[blank],puzzle.solution[blank]);assert.equal(app.game().notes[blank],0);
 app.node('sudoku-undo').click();assert.equal(app.game().board[blank],0);assert.equal(app.game().notes[blank],4);
 app.node('sudoku-hint').click();assert.equal(app.game().board[blank],puzzle.solution[blank]);assert.equal(app.game().hints,1);
 app.advance(5000);app.node('sudoku-dialog').close();assert.equal(app.game().elapsed,5000);
 const resumed=setup(app.values);resumed.open();assert.equal(resumed.game().board[blank],puzzle.solution[blank]);
 resumed.node('sudoku-new').click();assert.equal(resumed.node('sudoku-new-confirm').hidden,false);resumed.node('sudoku-keep').click();assert.equal(resumed.node('sudoku-new-confirm').hidden,true);
 resumed.node('sudoku-new').click();resumed.node('sudoku-replace').click();assert.deepEqual(resumed.game().board,puzzle.givens);
}
{
 const app=setup();app.open();app.cell(blank).click();app.key(String(puzzle.solution[blank]%9+1));app.node('sudoku-check').click();assert.equal(app.cell(blank).attrs['aria-invalid'],'true');
 app.node('sudoku-erase').click();assert.equal(app.game().board[blank],0);
 for(let i=0;i<81;i++)if(!puzzle.givens[i]){app.cell(i).click();app.key(String(puzzle.solution[i]));}
 assert.equal(app.game().won,true);assert.equal(app.node('sudoku-complete').hidden,false);app.node('sudoku-undo').click();assert.equal(app.game().won,false);assert.equal(app.node('sudoku-complete').hidden,true);
}
console.log('PASS: Sudoku interface checks (given-cell protection, notes, undo, hint, timer, saved progress, new-puzzle confirmation, checking, and completion).');
