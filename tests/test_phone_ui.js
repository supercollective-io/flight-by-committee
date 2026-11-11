// Exercise touch lifecycles without requiring a browser or listening socket.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('scripts/phone/index.html', 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    listeners: {}, style: {}, value: 0, disabled: false,
    classList: {add(){},remove(){},toggle(){}},
    addEventListener(event, fn){this.listeners[event]=fn;},
    setPointerCapture(){}, getBoundingClientRect(){return {left:0,top:0,width:200,height:200};},
  });
  return elements.get(id);
}
const context = vm.createContext({
  document:{getElementById:element,querySelectorAll:()=>[],addEventListener(){},hidden:false},
  window:{addEventListener(){}},location:{search:'?key=test'},URLSearchParams,
  sessionStorage:{getItem:()=> 'a'.repeat(32)},performance:{now:()=>0},
  AbortController,fetch:()=>new Promise(()=>{}),setTimeout(){},clearTimeout(){},setInterval(){},
});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
const run = code => vm.runInContext(code, context);
const pointer = (id,x=100,y=100)=>({pointerId:id,clientX:x,clientY:y,preventDefault(){}});
assert.equal(run('joined'),false);
element('join-controls').listeners.click();
assert.equal(run('joined'),true);
run('availability(true)');
element('pad').listeners.pointerdown(pointer(1,190,190));
assert.equal(run('values.roll'),1);
assert.equal(run('values.pitch'),1); // Profile inverts elevator so pulling raises nose.
element('pad').listeners.pointerdown(pointer(2,10,10));
assert.equal(run('values.roll'),1); // Second finger cannot steal the pad.
element('pad').listeners.pointercancel(pointer(1));
assert.equal(run('values.roll'),0);
assert.equal(run('values.pitch'),0);
element('brake').listeners.pointerdown(pointer(3));
assert.equal(run('values.brake'),1);
element('brake').listeners.lostpointercapture(pointer(3));
assert.equal(run('values.brake'),0);
element('left').listeners.pointerdown(pointer(4));
assert.equal(run('values.rudder'),-1);
run("lost('Disconnected')");
assert.equal(run('values.rudder'),0);
assert.equal(run('challenge'),null);
assert.equal(run('enabled'),false);
element('right').listeners.pointerdown(pointer(5));
assert.equal(run('values.rudder'),0);
assert(!html.includes('id="reset"'));
assert(!html.includes('id="pause"'));
console.log('Phone UI: touch, release, cancellation, disconnect and control-only layout passed.');
run('availability(true)');
element('brake').listeners.pointerdown(pointer(6));
element('brake').listeners.pointerup(pointer(6));
assert.equal(run('values.brake'),0);
element('brake').listeners.pointerdown(pointer(7));
element('release-brakes').listeners.click();
assert.equal(run('values.brake'),0);
assert.equal(run('releasePending'),true);
assert.equal(run("pointers.has('brake')"),false);
run("lost('Disconnected')");
assert.equal(run('releasePending'),false);
assert(!html.includes('<h1>Flight by committee</h1>'));
assert(!html.includes('Release to centre steering'));
assert(html.includes('writing-mode:vertical-lr;direction:rtl'));
console.log('Vertical throttle layout and explicit brake release passed.');

// Pitch/roll remain held while the other thumb changes throttle.
run('availability(true)');
element('pad').listeners.pointerdown(pointer(9,190,10));
element('throttle').value=.7;
element('throttle').listeners.input();
assert.equal(run('values.roll'),1);
assert.equal(run('values.pitch'),-1);
assert.equal(run('values.throttle'),.7);
element('pad').listeners.pointerup(pointer(9));
assert.equal(run('values.roll'),0);
assert.equal(run('values.throttle'),.7);
assert(html.includes('id="group-dot"'));
assert(html.includes('id="group-power-marker"'));
console.log('Simultaneous pad and throttle controls passed.');
// Keyboard inputs release on key-up, focus loss and connection loss.
const key = value => ({key:value,preventDefault(){}});
element('pad').listeners.keydown(key('ArrowLeft'));
element('pad').listeners.keydown(key('ArrowUp'));
assert.equal(run('values.roll'),-1);
assert.equal(run('values.pitch'),-1);
element('pad').listeners.keyup(key('ArrowLeft'));
assert.equal(run('values.roll'),0);
element('pad').listeners.blur();
assert.equal(run('values.pitch'),0);
element('brake').listeners.keydown(key(' '));
assert.equal(run('values.brake'),1);
element('brake').listeners.keyup(key(' '));
assert.equal(run('values.brake'),0);
element('left').listeners.keydown(key('Enter'));
assert.equal(run('values.rudder'),-1);
element('left').listeners.blur();
assert.equal(run('values.rudder'),0);
element('pad').listeners.keydown(key('ArrowRight'));
run("lost('Disconnected')");
assert.equal(run('values.roll'),0);
assert.equal(run('padKeys.size'),0);
element('brake').listeners.keydown(key(' '));
assert.equal(run('values.brake'),0);
run('availability(true)');
console.log('Keyboard steering and braking release safely.');
(async()=>{
  run('values.throttle=null');
  context.fetch=async()=>({ok:true,json:async()=>({simulator:true,ready:true,active:true,
    count:2,resync:false,challenge:'fresh',personal_throttle:.7,throttle:.45,
    collective:{roll:0,pitch:.5,rudder:0,brake:0,throttle:.5},inputs:[]})});
  await run('exchange()');
  assert.equal(element('throttle').value,.7);
  assert.equal(element('group-power').textContent,'Group 50%');
  assert.equal(element('group-dot').style.top,'72.5%');
  assert.equal(element('status').textContent,'Controlling · 2 active');
  assert.equal(run('enabled'),true);
  element('observe').listeners.click();
  assert.equal(run('joined'),false);
  assert.equal(run('enabled'),false);
  console.log('Personal throttle and collective feedback remain distinct.');
  element('join-controls').listeners.click();
  let reply;
  context.fetch=path=>path.startsWith('/leave')?Promise.resolve({ok:true}):new Promise(resolve=>{reply=resolve;});
  const pending=run('exchange()');
  element('observe').listeners.click();
  reply({ok:true,json:async()=>({simulator:true,ready:true,active:true,count:1,resync:false,challenge:'old',personal_throttle:.7,throttle:.45,collective:{roll:1,pitch:0,rudder:0,brake:0,throttle:.5},inputs:[]})});
  await pending;
  assert.equal(run('enabled'),false,'an old input response must not restore control after observing');
  assert.equal(run('challenge'),null);
  console.log('Observer transition rejects an outstanding control response.');
})().catch(error=>{console.error(error);process.exitCode=1;});
