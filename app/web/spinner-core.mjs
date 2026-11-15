export const COLORS = Object.freeze([
  ['Red','#F05252'],['Coral','#FF7C70'],['Orange','#FF9D43'],['Amber','#F8BD42'],
  ['Yellow','#F5E65B'],['Lime','#BAE869'],['Mint','#77DCA6'],['Emerald','#2FAD78'],
  ['Teal','#279C98'],['Cyan','#4CCDDD'],['Sky','#78B5F4'],['Blue','#4C7FE7'],
  ['Indigo','#6262D9'],['Violet','#9D68DF'],['Lavender','#C6A2EA'],['Pink','#EE92C1']
].map(([name,hex])=>Object.freeze({name,hex})));
export const SLICE = 360 / COLORS.length;
export const normalize = angle => ((angle%360)+360)%360;
export function pointerIndex(rotation) {
  return Math.floor(normalize(-rotation+SLICE/2)/SLICE)%COLORS.length;
}
export function polar(angle,radius=210) {
  const radians=angle*Math.PI/180;
  return [240+radius*Math.cos(radians),240+radius*Math.sin(radians)];
}
export function sectorPath(index) {
  const [x1,y1]=polar(-90+index*SLICE-SLICE/2);
  const [x2,y2]=polar(-90+index*SLICE+SLICE/2);
  return `M 240 240 L ${x1} ${y1} A 210 210 0 0 1 ${x2} ${y2} Z`;
}
export function randomIndex(length=COLORS.length,random=globalThis.crypto) {
  if(!Number.isInteger(length)||length<1||length>4294967296)throw new Error('Invalid random range.');
  const buffer=new Uint32Array(1),limit=4294967296-(4294967296%length);
  do {random.getRandomValues(buffer);} while(buffer[0]>=limit);
  return buffer[0]%length;
}
export function createSpinPlan(index,currentRotation=0,turns=9,jitter=0) {
  if(!Number.isInteger(index)||index<0||index>=COLORS.length||!Number.isFinite(currentRotation)||!Number.isInteger(turns)||turns<0||!Number.isFinite(jitter)||Math.abs(jitter)>SLICE*.3)throw new Error('Invalid spin.');
  const start=normalize(currentRotation),target=normalize(-index*SLICE+jitter);
  return {start,end:start+turns*360+normalize(target-start),index};
}
export const easeOut = progress => 1-Math.pow(1-Math.min(1,Math.max(0,progress)),5);
export function luminance(hex) {
  const channels=hex.match(/[a-f\d]{2}/gi).map(channel=>parseInt(channel,16)/255).map(value=>value<=.04045?value/12.92:Math.pow((value+.055)/1.055,2.4));
  return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
}
export function labelColor(hex) {
  const level=luminance(hex),dark=luminance('#161321');
  return (level+.05)/(dark+.05)>=1.05/(level+.05)?'#161321':'#FFFFFF';
}
