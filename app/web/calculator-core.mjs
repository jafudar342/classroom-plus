export class Calculator {
  constructor() { this.clear(); }
  clear() { this.display='0'; this.value=null; this.operator=null; this.fresh=true; this.repeat=null; }
  number(key) {
    if(this.fresh || this.display==='Error') { this.display='0'; this.fresh=false; }
    if(key==='.') { if(!this.display.includes('.'))this.display+='.'; }
    else if(this.display.replace(/[-.]/g,'').length<15) this.display=this.display==='0'?key:this.display+key;
    this.repeat=null;
  }
  compute(a,op,b) {
    const value=op==='+'?a+b:op==='-'?a-b:op==='*'?a*b:b===0?NaN:a/b;
    if(!Number.isFinite(value)) { this.clear(); this.display='Error'; return null; }
    this.display=String(Number(value.toPrecision(12))); return Number(this.display);
  }
  operation(op) {
    if(this.display==='Error')return;
    const current=Number(this.display);
    if(this.operator && !this.fresh) { if(this.compute(this.value,this.operator,current)===null)return; }
    this.value=Number(this.display); this.operator=op; this.fresh=true; this.repeat=null;
  }
  equals() {
    if(this.display==='Error')return;
    if(this.operator) {
      const op=this.operator,b=Number(this.display);
      if(this.compute(this.value,op,b)===null)return;
      this.repeat={op,b}; this.operator=null; this.value=null;
    } else if(this.repeat) { if(this.compute(Number(this.display),this.repeat.op,this.repeat.b)===null)return; }
    this.fresh=true;
  }
  press(key) {
    if(/^[0-9.]$/.test(key))this.number(key);
    else if(['+','-','*','/'].includes(key))this.operation(key);
    else if(key==='=')this.equals();
    else if(key==='AC')this.clear();
    else if(key==='⌫') { if(this.display==='Error')this.clear(); else if(!this.fresh)this.display=this.display.length>1?this.display.slice(0,-1):'0'; if(this.display==='-')this.display='0'; }
    else if(key==='±' && this.display!=='Error' && Number(this.display)!==0)this.display=this.display.startsWith('-')?this.display.slice(1):'-'+this.display;
    else if(key==='%' && this.display!=='Error') { this.display=String(Number((Number(this.display)/100).toPrecision(12))); this.repeat=null; }
    return this.display;
  }
}
