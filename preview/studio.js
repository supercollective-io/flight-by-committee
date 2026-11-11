import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = (id) => document.getElementById(id);
const viewport = $('viewport');
const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
viewport.append(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#e9e8e1');
const plane = new THREE.Group(); scene.add(plane);
const ambient = new THREE.HemisphereLight(0xffffff, 0x747b85, 1.5);scene.add(ambient);
const key = new THREE.DirectionalLight(0xffffff, 2.2);key.position.set(-30,60,50);scene.add(key);
const fill = new THREE.DirectionalLight(0xd8e4ff, .8);fill.position.set(20,25,-45);scene.add(fill);
const camera = new THREE.PerspectiveCamera(34, 1, .1, 1000);
const ortho = new THREE.OrthographicCamera(-45,45,25,-25,.1,1000);
const left = ortho.clone(), right = ortho.clone();
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.minDistance=20; controls.maxDistance=230;
const target = new THREE.Vector3(6,5,0);
controls.target.copy(target);
let mode='perspective', liveTexture, pinnedTexture, currentRevision, shown='live';
const skins = new Set(); let gear;
let selectedName, currentName, pinnedName, pinnedRevision;
let catalogue=[];
const textureURL=(name,revision)=>'/texture.png?livery='+encodeURIComponent(name)+'&v='+revision;
const perspectiveViews=new Set(['perspective','quarter-front-right','quarter-rear-left','quarter-rear-right']);
const views={perspective:[-76,33,90],'quarter-front-right':[-76,33,-90],'quarter-rear-left':[88,33,90],'quarter-rear-right':[88,33,-90],port:[6,5,120],starboard:[6,5,-120],front:[-120,5,0],rear:[120,5,0],top:[6,120,0],bottom:[6,-120,0]};
const labels={perspective:'FRONT LEFT QUARTER','quarter-front-right':'FRONT RIGHT QUARTER','quarter-rear-left':'REAR LEFT QUARTER','quarter-rear-right':'REAR RIGHT QUARTER',port:'PORT / LEFT',starboard:'STARBOARD / RIGHT',front:'FRONT',rear:'REAR',top:'ABOVE',bottom:'BELOW',both:'PORT / LEFT'};
function setView(view){
  mode=view; controls.enabled=perspectiveViews.has(view);
  const c=perspectiveViews.has(view)?camera:ortho;
  const p=views[view]||views.port;c.position.set(...p);
  c.up.set(view==='top'||view==='bottom'?-1:0,view==='top'||view==='bottom'?0:1,0);
  c.lookAt(target);
  if(perspectiveViews.has(view)){controls.target.copy(target);controls.update();}
  $('view-label').textContent=labels[view];$('split-label').hidden=view!=='both';
  $('view-label').style.bottom=view==='both'?'calc(50% + 20px)':'22px';
  $('interaction').textContent=perspectiveViews.has(view)?'Drag to orbit · scroll to zoom · right-drag to pan':'Fixed orthographic view · select Orbit to explore';
  document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-pressed',b.dataset.view===view);});
  resize();
}
function fit(c, aspect, height=48){c.left=-height*aspect/2;c.right=height*aspect/2;c.top=height/2;c.bottom=-height/2;c.updateProjectionMatrix();}
function resize(){const w=viewport.clientWidth,h=viewport.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.fov=2*Math.atan(Math.tan(17*Math.PI/180)/Math.min(1,w/h))*180/Math.PI;camera.updateProjectionMatrix();const overhead=mode==='top'||mode==='bottom';const endOn=mode==='front'||mode==='rear';fit(ortho,w/h,Math.max(overhead?84:32,(endOn?76:84)/(w/h)));for(const c of [left,right])fit(c,w/(h/2),Math.max(32,84/(w/(h/2))));}
new ResizeObserver(resize).observe(viewport);
function render(){requestAnimationFrame(render);controls.update();const w=viewport.clientWidth,h=viewport.clientHeight;
  renderer.setScissorTest(false);
  if(mode==='both'){
    renderer.setScissorTest(true);
    for(const [i,c] of [left,right].entries()){c.position.set(6,5,i===0?120:-120);c.lookAt(target);renderer.setViewport(0,i===0?h/2:0,w,h/2);renderer.setScissor(0,i===0?h/2:0,w,h/2);renderer.render(scene,c);}
    renderer.setScissorTest(false);
  }else{renderer.setViewport(0,0,w,h);renderer.render(scene,perspectiveViews.has(mode)?camera:ortho);}
}
function applyTexture(texture){for(const material of skins){material.map=texture;material.needsUpdate=true;}}
async function getTexture(name,revision){const t=await new THREE.TextureLoader().loadAsync(textureURL(name,revision));t.flipY=false;t.colorSpace=THREE.SRGBColorSpace;t.anisotropy=renderer.capabilities.getMaxAnisotropy();return t;}
function show(which){shown=which;applyTexture(which==='live'?liveTexture:pinnedTexture);$('compare-label').hidden=which==='live';for(const name of ['live','pinned']){$(name).classList.toggle('active',name===which);$(name).setAttribute('aria-pressed',name===which);}}
async function refresh(state){
  if(state.name!==selectedName)return;
  $('error').hidden=!state.error;$('error').textContent=state.error?'Build failed — showing the last good texture. '+state.error:'';
  const status=state.error?'SVG needs attention':'Watching for changes';if($('status').textContent!==status)$('status').textContent=status;$('status-dot').className=state.error?'bad':'good';
  if(state.revision&&(state.revision!==currentRevision||state.name!==currentName)){
    const next=await getTexture(state.name,state.revision);
    if(state.name!==selectedName){next.dispose();return;}
    const previous=liveTexture;liveTexture=next;currentRevision=state.revision;currentName=state.name;
    if(shown==='live')applyTexture(next);
    if(previous&&previous!==pinnedTexture)previous.dispose();
    $('texture-map').src=textureURL(currentName,currentRevision);$('texture-link').href=textureURL(currentName,currentRevision);$('build-time').textContent=`Built in ${state.build_ms} ms`;
  }
  $('source').textContent=state.name+'.svg ↗';$('source').href='/source/'+state.name+'.svg';
  $('pin').disabled=!state.revision;
}
async function poll(){try{const response=await fetch('/state?livery='+encodeURIComponent(selectedName));if(!response.ok)throw new Error('Server unavailable');await refresh(await response.json());}catch(e){$('status').textContent='Preview disconnected';$('status-dot').className='bad';$('error').hidden=false;$('error').textContent='Start the preview server again to reconnect. '+e.message;}finally{setTimeout(poll,650);}}
async function start(){
  const response=await fetch('/state');if(!response.ok)throw new Error('Could not connect to the preview server');const state=await response.json();
  selectedName=state.name;catalogue=state.designs;
  for(const design of catalogue){const option=document.createElement('option');option.value=design.name;option.textContent=design.label;$('design').append(option);}
  $('design').value=selectedName;
  const assetErrors=[];const manager=new THREE.LoadingManager();
  manager.onError=url=>assetErrors.push(url);
  const loader=new GLTFLoader(manager).setResourcePath(new URL('/model/',location.href).href);const loaded=new Map();
  for(const part of state.parts){if(!loaded.has(part.url))loaded.set(part.url,loader.loadAsync(part.url));}
  for(const part of state.parts){
    const object=(await loaded.get(part.url)).scene.clone(true);object.position.set(...part.position);
    object.traverse(n=>{if(n.isMesh){const materials=Array.isArray(n.material)?n.material:[n.material];for(const m of materials){m.roughness=.75;m.metalness=0;m.side=THREE.DoubleSide;if("specularIntensity" in m)m.specularIntensity=.3;if(m.userData.livery)skins.add(m);}n.castShadow=true;}});
    plane.add(object);if(part.name==='747-400_gear')gear=object;
  }
  if(assetErrors.length)throw new Error('Missing aircraft textures: '+assetErrors.join(', '));
  if(!skins.size)throw new Error('No paintable materials found in the aircraft');
  await refresh(state);$('loading').hidden=true;$('design').disabled=false;$('pin').disabled=false;$('export').disabled=false;poll();
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
$('design').onchange=()=>{selectedName=$('design').value;show('live');$('pin').disabled=true;};
$('reset').onclick=()=>setView(mode);
$('gear').onchange=()=>{if(gear)gear.visible=$('gear').checked;};
$('wireframe').onchange=()=>plane.traverse(n=>{if(n.isMesh)for(const m of Array.isArray(n.material)?n.material:[n.material])m.wireframe=$('wireframe').checked;});
$('light').onchange=()=>{const value=$('light').value;scene.background.set(value==='dusk'?'#353b4a':value==='daylight'?'#dbe7ed':'#e9e8e1');key.color.set(value==='dusk'?'#ffb580':'#ffffff');key.intensity=value==='dusk'?1.2:2.2;ambient.intensity=value==='dusk'?.8:1.5;renderer.toneMappingExposure=value==='daylight'?1.5:1.05;};
$('pin').onclick=()=>{if(pinnedTexture&&pinnedTexture!==liveTexture)pinnedTexture.dispose();pinnedTexture=liveTexture;pinnedName=currentName;pinnedRevision=currentRevision;$('compare-label').textContent='PINNED · '+(catalogue.find(d=>d.name===pinnedName)?.label||pinnedName);$('comparison').hidden=false;$('pin').textContent='Replace pinned design';show('live');};
$('live').onclick=()=>show('live');$('pinned').onclick=()=>show('pinned');
$('export').onclick=()=>{const a=document.createElement('a');a.download=`${shown==='pinned'?pinnedName:currentName}-${mode}-${shown}-${(shown==='pinned'?pinnedRevision:currentRevision).slice(0,7)}.png`;a.href=renderer.domElement.toDataURL('image/png');a.click();};
setView('perspective');render();
start().catch(e=>{$('loading').textContent='Could not load the aircraft: '+e.message;$('status').textContent='Preview unavailable';$('status-dot').className='bad';});
