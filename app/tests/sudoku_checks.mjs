import assert from 'node:assert/strict';
import {PEERS,LEVELS,createPuzzle,countSolutions,conflicts,solved,validSavedGame} from '../web/sudoku-core.mjs';
let seed=12345;const random=()=>((seed=(seed*1664525+1013904223)>>>0)/4294967296);
for(const level of Object.keys(LEVELS))for(let iteration=0;iteration<6;iteration++) {
 const puzzle=createPuzzle(level,random);
 assert.equal(solved(puzzle.solution),true);assert.equal(countSolutions(puzzle.givens),1);assert.ok(puzzle.clues>=LEVELS[level]&&puzzle.clues<=LEVELS[level]+5);
 assert.equal(puzzle.givens.filter(Boolean).length,puzzle.clues);assert.ok(puzzle.givens.every((value,index)=>!value||value===puzzle.solution[index]));
}
assert.equal(PEERS.length,81);assert.ok(PEERS.every((list,index)=>list.length===20&&!list.includes(index)&&new Set(list).size===20));
assert.equal(countSolutions(Array(81).fill(0)),2);assert.equal(countSolutions(null),0);assert.equal(solved(null),false);
const invalid=Array(81).fill(0);invalid[0]=invalid[8]=5;assert.equal(countSolutions(invalid),0);assert.equal(conflicts(invalid)[0],true);
const puzzle=createPuzzle('easy',random),game={...puzzle,version:1,board:[...puzzle.givens],notes:Array(81).fill(0),elapsed:0,hints:0};assert.equal(validSavedGame(game),true);
for(const changes of [{solution:null},{elapsed:-1},{level:'unknown'},{notes:Array(81).fill(999)},{version:2}])assert.equal(validSavedGame({...game,...changes}),false);
const given=game.givens.findIndex(Boolean),changed=[...game.board];changed[given]=0;assert.equal(validSavedGame({...game,board:changed}),false);
assert.throws(()=>createPuzzle('unknown'));
console.log('PASS: 18 generated Sudoku puzzles have one solution; solution validity, difficulty ranges, peer conflicts, and save validation checked.');
