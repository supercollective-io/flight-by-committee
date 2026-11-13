'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1) || sessionStorage.getItem('flight-operator-token') || '';
if (location.hash) { sessionStorage.setItem('flight-operator-token', token); history.replaceState(null, '', '/'); }
let catalogue, original = null, base = {}, dirty = false, busy = false, active = false, connected = false, linkSignature = null;
const fields = ['name','description','aircraft','installation','rendering','input','location','position-type','on-ground','latitude_deg','longitude_deg','airport','heading_deg','altitude_m','speed_m_s','wind_m_s','time_of_day','glideslope_deg','frozen','engine_running','initialisation','livery','properties'];
function text(id, value) { if ($(id).textContent !== value) $(id).textContent = value; }
function feedback(text, error = false) { $('feedback').textContent = text; $('feedback').dataset.error = String(error); }
async function api(path, data) {
  const response = await fetch('/api/' + path, {method: data === undefined ? 'GET' : 'POST', headers: {Authorization: 'Bearer ' + token, ...(data === undefined ? {} : {'Content-Type':'application/json'})}, body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(path === 'stop' ? 20000 : 15000), cache:'no-store'});
  if (!response.ok) {
    const text = await response.text();
    let message = text; try { message = JSON.parse(text).error || text; } catch {}
    throw new Error(message);
  }
  return response.json();
}
function controls() {
  for (const id of ['new','duplicate','check','save','launch']) $(id).disabled = busy || !connected || !catalogue || (id !== 'new' && !original) || (id === 'launch' && active);
  $('stop').disabled = $('stop-mobile').disabled = busy || !connected || !active;
  for (const button of document.querySelectorAll('.profile')) button.disabled = busy;
  for (const id of fields) $(id).disabled = busy;
  visibility();
}
async function action(fn) {
  if (busy) return;
  busy = true; controls();
  try { await fn(); } catch (error) { feedback(error.message, true); }
  finally { busy = false; controls(); }
}
function options(id, values, empty) {
  $(id).replaceChildren();
  if (empty !== undefined) $(id).add(new Option(empty, ''));
  for (const value of values) $(id).add(new Option(value, value));
}
function showProfiles() {
  $('profiles').replaceChildren();
  for (const profile of catalogue.profiles) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'profile';
    button.setAttribute('aria-current', String(profile.name === original?.name));
    const name = document.createElement('strong'); name.textContent = profile.name;
    const description = document.createElement('span'); description.textContent = profile.description;
    const type = document.createElement('span'); type.textContent = profile.custom ? 'Local profile' : 'Shipped example'; type.className = 'type';
    button.append(name, description, type);
    button.addEventListener('click', () => void action(async () => {
      if (dirty && !confirm('Discard unsaved edits and open another profile?')) return;
      load(await api('profiles/' + encodeURIComponent(profile.name)));
      feedback('Profile loaded. Check setup before launching.');
    }));
    $('profiles').append(button);
  }
  if (!catalogue.profiles.length) $('profiles').textContent = 'No saved profiles. Create a new profile to begin.';
  $('profiles').setAttribute('aria-busy','false');
  const selected = $('profiles').querySelector('[aria-current=true]');
  if (selected) $('profiles').scrollTop = selected.offsetTop - $('profiles').offsetTop;
}
function locationFields(value) {
  $('position-type').value = value.airport ? 'airport' : 'coordinates';
  for (const id of ['latitude_deg','longitude_deg','airport','heading_deg']) $(id).value = value[id] ?? '';
  $('on-ground').value = String(value.on_ground ?? false);
  visibility();
}
function visibility() {
  const coords = $('position-type').value === 'coordinates', ground = $('on-ground').value === 'true';
  for (const element of document.querySelectorAll('[data-coordinates]')) element.hidden = !coords;
  $('airport-field').hidden = coords;
  $('airport').required = !coords;
  $('latitude_deg').required = $('longitude_deg').required = coords;
  $('altitude-field').hidden = $('glideslope-field').hidden = ground;
  $('altitude_m').required = !ground;
  $('airport').disabled = busy || coords;
  $('latitude_deg').disabled = $('longitude_deg').disabled = busy || !coords;
  $('altitude_m').disabled = $('glideslope_deg').disabled = busy || ground;
}
function load(detail) {
  original = detail; base = structuredClone(detail.profile); dirty = false;
  $('settings').hidden = false;
  $('editor-title').textContent = detail.name;
  $('source').textContent = detail.custom ? 'Local profile · saved on this computer' : 'Shipped example · save changes as a local copy';
  for (const id of fields) if (!['location','position-type','on-ground','properties'].includes(id)) $(id).value = base[id] ?? base.flight?.[id] ?? '';
  $('name').value = detail.name;
  $('properties').value = JSON.stringify(base.properties || {}, null, 2);
  $('location').value = typeof base.location === 'string' ? base.location : '';
  locationFields(detail.location || base.location);
  $('warning').textContent = base.warning || '';
  $('warning').hidden = !base.warning;
  $('dirty').textContent = detail.revision ? 'Settings are unchanged.' : 'New profile · not saved yet.';
  $('effective').replaceChildren();
  if (detail.effective) effective(detail.effective);
  showProfiles(); controls();
}
function markDirty() {
  dirty = true; $('dirty').textContent = 'Unsaved edits · launch uses these settings; saving is separate.';
  $('effective').replaceChildren();
}
function draft() {
  const profile = structuredClone(base);
  for (const id of ['description','aircraft','installation','rendering']) profile[id] = $(id).value.trim();
  for (const id of ['input','initialisation','livery']) { if ($(id).value.trim()) profile[id] = $(id).value.trim(); else delete profile[id]; }
  const number = id => $(id).value === '' ? undefined : Number($(id).value);
  profile.location = {heading_deg:number('heading_deg'), on_ground:$('on-ground').value === 'true'};
  if ($('position-type').value === 'airport') profile.location.airport = $('airport').value.trim();
  else Object.assign(profile.location, {latitude_deg:number('latitude_deg'), longitude_deg:number('longitude_deg')});
  // Retain references only when the selected preset is unchanged.
  if ($('location').value) profile.location = $('location').value;
  profile.flight = {};
  for (const id of ['altitude_m','speed_m_s','wind_m_s','glideslope_deg']) {
    if ($('on-ground').value === 'true' && ['altitude_m','glideslope_deg'].includes(id)) continue;
    const value = number(id); if (value !== undefined) profile.flight[id] = value;
  }
  if ($('time_of_day').value) profile.flight.time_of_day = $('time_of_day').value;
  for (const id of ['frozen','engine_running']) if ($(id).value !== '') profile.flight[id] = $(id).value === 'true';
  try { profile.properties = JSON.parse($('properties').value); } catch { throw new Error('Initial properties must be valid JSON. Use an object of property paths and values.'); }
  const name = $('name').value.trim();
  return {name, profile, ...(original?.custom && original.name === name && original.revision ? {revision:original.revision} : {})};
}
function effective(data) {
  const container = $('effective'); container.replaceChildren();
  const list = document.createElement('dl');
  const command = data.command;
  const flag = prefix => command.findLast(value => value.startsWith(prefix))?.slice(prefix.length);
  const rows = [
    ['Position', data.location.airport || `${data.location.latitude_deg}°, ${data.location.longitude_deg}°`],
    ['Heading', `${data.location.heading_deg}°`],
    ['Altitude', data.location.on_ground ? 'Ground elevation from scenery' : `${data.flight.altitude_m} m above sea level`],
    ['Airspeed', data.flight.speed_m_s === undefined ? 'Simulator default' : `${data.flight.speed_m_s} m/s`],
    ['Weather', data.flight.wind_m_s === undefined ? (flag('--metar=') || flag('--wind=') || 'Rendering preset / simulator default') : `${data.flight.wind_m_s} m/s · fixed weather`],
    ['Time of day', flag('--timeofday=') || 'Simulator default'],
    ['Paused', data.flight.frozen === undefined ? 'Simulator default' : data.flight.frozen ? 'Yes' : 'No'],
    ['Controls', data.input ? 'Phone controls · ' + data.input.layout : 'Simulator controls only'],
    ['Executable', data.installation.binary],
  ];
  for (const [label,value] of rows) { const dt=document.createElement('dt'),dd=document.createElement('dd'); dt.textContent=label;dd.textContent=value;list.append(dt,dd); }
  const title = document.createElement('h3'); title.textContent = 'Launch arguments';
  const pre = document.createElement('pre'); pre.textContent = command.join('\n'); container.append(list,title,pre);
}
function flight(status) {
  active = status.active;
  $('mobile-flight').hidden = !active;
  const labels = {idle:'Idle',starting:'Starting',running:'Process running',loading:'Loading aircraft',ready:'Aircraft ready',stopping:'Stopping',stopped:'Stopped',failed:'Launch failed'};
  text('phase', labels[status.phase] || status.phase);
  text('mobile-phase', labels[status.phase] || status.phase); $('phase').dataset.phase = status.phase;
  $('flight-name').textContent = status.description || status.name || 'No flight launched yet.';
  $('flight-message').textContent = status.phase === 'idle' ? 'The operator stays open between flights.' : status.message;
  const links = $('flight-links');
  const nextLinks = JSON.stringify(status.links || {});
  if (nextLinks !== linkSignature) {
    linkSignature = nextLinks; links.replaceChildren();
    for (const [label,href] of Object.entries(status.links || {})) {
      const url = new URL(href); if (!['http:','https:'].includes(url.protocol)) continue;
      const a=document.createElement('a');a.href=url.href;a.textContent=label;a.target='_blank';a.rel='noopener noreferrer';links.append(a);
    }
  }
  $('logs').hidden = !status.log;
  $('log-paths').replaceChildren();
  for (const path of [status.log,status.simulator_log].filter(Boolean)) { const code=document.createElement('code');code.textContent=path;$('log-paths').append(code); }
  $('active-settings').hidden = !status.settings;
  if (status.settings) $('active-values').textContent = JSON.stringify({location:status.settings.location,flight:status.settings.flight},null,2);
  controls();
}
$('settings').addEventListener('input', event => {
  if (['position-type','on-ground','latitude_deg','longitude_deg','airport','heading_deg'].includes(event.target.id)) $('location').value = '';
  visibility(); markDirty();
});
$('location').addEventListener('change', () => { if ($('location').value) locationFields(catalogue.options.location[$('location').value]); markDirty(); });
$('settings').addEventListener('submit', event => { event.preventDefault(); void action(async () => { feedback('Checking assets and starting flight…'); flight(await api('launch', draft())); feedback('Launch requested. Follow progress in Current flight.'); }); });
$('check').addEventListener('click', () => { if (!$('settings').reportValidity()) return; void action(async () => { feedback('Checking setup…'); const result=await api('check',draft());effective(result.effective);$('effective-panel').open=true;feedback(result.message,!result.ready); }); });
$('save').addEventListener('click', () => { if (!$('settings').reportValidity()) return; void action(async () => {
  const payload=draft(); const result=await api('profiles',payload);catalogue=await api('profiles');load(result);feedback('Local profile saved. The active flight is unchanged.');
}); });
$('duplicate').addEventListener('click', () => {
  if (busy) return;
  $('name').value = $('name').value.replace(/-copy(?:-\d+)?$/, '') + '-copy';
  original = {...original, name:'', custom:true, revision:null};
  $('source').textContent='Local copy · choose a unique name and save';$('editor-title').textContent='Duplicate profile';markDirty();showProfiles();$('name').focus();$('name').select();
});
$('new').addEventListener('click', () => {
  if (busy || (dirty && !confirm('Discard unsaved edits and create a new profile?'))) return;
  load({name:'new-flight',custom:true,profile:{description:'New free flight',aircraft:'ufo',installation:catalogue.options.installation.includes('nightly')?'nightly':catalogue.options.installation[0],rendering:catalogue.options.rendering.includes('ws3-hdr')?'ws3-hdr':catalogue.options.rendering[0],location:{latitude_deg:0,longitude_deg:0,heading_deg:0,on_ground:false},flight:{altitude_m:1000,frozen:true,wind_m_s:0,time_of_day:'noon'}}});
  $('latitude_deg').value='';$('longitude_deg').value='';markDirty();feedback('Choose your coordinates and aircraft. New flights need an in-simulator check.');$('name').focus();
});
for (const id of ['stop', 'stop-mobile']) $(id).addEventListener('click', () => void action(async () => { feedback('Stopping flight…');flight(await api('stop',{}));feedback('Flight stopped. You can launch another profile.'); }));
window.addEventListener('beforeunload', event => { if(dirty){event.preventDefault();event.returnValue='';} });
async function poll() {
  try {
    const status=await api('status');connected=true;text('connection','Connected · this computer');flight(status);
    if (!catalogue) { setTimeout(initialise,1500); return; }
  }
  catch { connected=false;text('connection','Disconnected · check the launcher terminal');text('phase','Status unavailable');text('mobile-phase','Disconnected');$('phase').dataset.phase='unknown';controls(); }
  setTimeout(poll,1500);
}
async function initialise() {
  try {
    catalogue=await api('profiles'); connected=true;
    for(const id of ['installation','rendering']) options(id,catalogue.options[id]);
    options('input',catalogue.options.input,'Simulator controls only');options('initialisation',catalogue.options.initialisation,'None');options('location',Object.keys(catalogue.options.location),'Custom coordinates / airport');
    showProfiles();
    if(catalogue.profiles.length) load(await api('profiles/'+encodeURIComponent(catalogue.profiles[0].name)));
    controls();
  } catch(error){feedback(error.message,true);$('profiles').setAttribute('aria-busy','false');}
  void poll();
}
void initialise();
