const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const sockets=[];
class Socket{
 static OPEN=1;
 constructor(url){this.url=url;this.readyState=0;sockets.push(this);queueMicrotask(()=>{this.readyState=1;this.onopen();});}
 close(){this.readyState=3;if(this.onclose)this.onclose();}
 send(data){this.sent=JSON.parse(data);queueMicrotask(()=>this.onmessage({data:JSON.stringify({epoch:'epoch',challenge:'fresh',count:0})}));}
}
const context={window:{},WebSocket:Socket,URLSearchParams,location:{origin:'https://flight.supercollective.io',search:'?key=participant'},Promise,JSON,Error,encodeURIComponent};
vm.createContext(context);
vm.runInContext(fs.readFileSync('scripts/phone/relay.js','utf8'),context);
async function request(path, controls={roll:1}){return context.window.flightRequest(path,{signal:new AbortController().signal,body:JSON.stringify({challenge:'old',controls,release_brakes:true})});}
(async()=>{
 await request('/input');
 assert.equal(sockets[0].sent.controls,null,'new connections must handshake');
 assert.equal(sockets[0].sent.release_brakes,false);
 await request('/input');
 assert.equal(sockets[0].sent.controls.roll,1);
 assert.equal(sockets[0].sent.epoch,'epoch');
 sockets[0].close();
 await request('/input');
 assert.equal(sockets[1].sent.controls,null,'reconnect must discard queued control');
 await request('/status');
 assert.deepEqual(sockets[1].sent,{kind:'status'},'observers send no control message');
 console.log('Hosted transport: authenticated socket, reconnect handshake, observer role passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
