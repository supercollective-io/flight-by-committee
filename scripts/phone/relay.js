'use strict';
// One outstanding exchange, no offline queue. A new connection starts a handshake.
let flightSocket=null, flightEpoch=null;
window.flightRequest=async function(path,options){
 if(!flightSocket || flightSocket.readyState!==WebSocket.OPEN){
  flightEpoch=null;
  flightSocket=new WebSocket(location.origin.replace(/^http/,'ws')+'/ws/participant?key='+encodeURIComponent(new URLSearchParams(location.search).get('key')));
  const socket=flightSocket;
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;options.signal.addEventListener('abort',()=>{socket.close();reject(Error('Connection timed out'));},{once:true});});
 }
 const socket=flightSocket;
 const observer=path.startsWith('/status');
 const input=observer?null:JSON.parse(options.body);
 const data=observer?{kind:'status'}:{kind:'input',epoch:flightEpoch,challenge:flightEpoch?input.challenge:null,controls:flightEpoch?input.controls:null,release_brakes:flightEpoch?input.release_brakes:false};
 return await new Promise((resolve,reject)=>{
  const abort=()=>{socket.close();reject(Error('Exchange timed out'));};
  const clean=()=>options.signal.removeEventListener('abort',abort);
  options.signal.addEventListener('abort',abort,{once:true});
  socket.onclose=()=>{clean();reject(Error('Disconnected'));};
  socket.onerror=()=>{clean();reject(Error('Disconnected'));};
  socket.onmessage=event=>{clean();const value=JSON.parse(event.data);flightEpoch=value.epoch;resolve({ok:true,json:async()=>value});};
  socket.send(JSON.stringify(data));
 });
};
