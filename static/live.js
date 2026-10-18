/**
 * HKOnTransit live-data client.
 *
 * This IIFE module is the browser-side controller for the "Find Routes & Stops"
 * (Find Routes & Stops) flow. All HTTP requests go through the same-origin
 * FastAPI gateway (server.py) — it never calls external APIs directly.
 *
 * Same-origin API endpoints called (via fetch):
 *   GET  /api/gmb/routes/{region}                       — list GMB routes
 *   GET  /api/gmb/route/{region}/{route_code}           — route variants
 *   GET  /api/gmb/stops/{route_id}/{route_seq}          — stop sequence
 *   GET  /api/gmb/stop/{stop_id}                        — stop coordinates
 *   GET  /api/gmb/eta/{route_id}/{route_seq}/{stop_seq} — live ETA
 *   GET  /api/bus/kmb/stops?route=&direction=&service_type=
 *   GET  /api/bus/kmb/eta?route=&stop_id=&service_type=&direction=
 *   GET  /api/bus/kmb/stop/{stop_id}
 *   GET  /api/bus/ctb/stops?route=&direction=
 *   GET  /api/bus/ctb/eta?route=&stop_id=&direction=
 *   GET  /api/bus/ctb/stop/{stop_id}
 *   GET  /api/mtr/next-train?line=&station=             — MTR Next Train
 *   GET  /api/weather                                   — HKO current weather
 *   GET  /api/lab/summary                               — SQLite snapshot stats
 *
 * The backend (server.py) proxies these to the official Hong Kong
 * open-data APIs (GMB, KMB, CTB, MTR, HKO). No API keys are needed
 * in the browser because the backend handles upstream auth/availability.
 *
 * Element ID contract (DOM elements this module binds to):
 *   operatorSelect, regionSelect, routeSelect, routeInput,
 *   directionSelect, stopSelect, alightSelect,
 *   lookupEta, refreshEta, refreshWeather,
 *   lookupMtr, mtrLine, mtrStation,
 *   liveQueryStatus, etaHealth, etaRouteContext, liveEtaItems,
 *   lastFetched, apiStatus, realLocationPanel, stopLocationTitle,
 *   stopLocationText, officialMapLink, weatherNow, mtrResult,
 *   actualArrivals, labCapture, reportRoute, reportStop,
 *   boarding (screen element), regionWrap, routeSelectWrap, routeInputWrap
 *
 * Maintainer notes:
 *   - The module auto-runs on script load (see wire() at bottom).
 *   - A 60-second interval auto-refreshes ETA when the boarding screen is
 *     visible and the tab is not hidden.
 *   - Stale official data is hidden (not shown as live) per the trust model.
 *   - If the page is opened via file:// protocol (double-clicking index.html),
 *     the module warns the user to start the backend first via run.sh.
 *   - window.configureRideStops?.() is a callback exposed for index.html's
 *     inline ride-mode controller to receive the stop sequence.
 */
(() => {
'use strict';
const $=id=>document.getElementById(id);
const state={provider:'GMB',region:'HKI',route:'',routeId:null,routeSeq:null,
  serviceType:1,direction:'outbound',stops:[],selectedStop:null,requestToken:0,etaToken:0};
let refreshTimer=null;
const HK_TIME={timeZone:'Asia/Hong_Kong',hour:'2-digit',minute:'2-digit',hour12:false};

async function api(url){
  return window.hkRequest(url);
}
function status(message,error=false){const e=$('liveQueryStatus');e.textContent=message;e.className=`note ${error?'error':'ok'}`}
function fill(sel,items,placeholder){sel.replaceChildren();if(placeholder){const o=new Option(placeholder,'');sel.add(o)}items.forEach(it=>sel.add(new Option(String(it.label),String(it.value))))}
function setActiveEta(type,message){const badge=$('etaHealth');badge.textContent=message;badge.className=type==='fresh'?'badge':'badge grey';}
function fmtTime(raw){if(!raw)return 'Unknown';const dt=new Date(raw);return isNaN(dt)?raw:dt.toLocaleTimeString('en-HK',HK_TIME)}
function fmtLocal(raw){return raw?String(raw).replace('T',' ').slice(0,19):'No timestamp'}
function chosenStop(){return state.stops.find(s=>String(s.stop_seq)===$('stopSelect').value)||null}
function chosenVariant(){const idx=Number($('directionSelect').value);return state.variants?.[idx]||null}
function activeRouteName(){return `${state.provider} ${state.route}${state.provider==='GMB'?' ('+state.region+')':''}`}
function configureAlighting(){
 const board=chosenStop(),idx=state.stops.findIndex(s=>s===board),previous=$('alightSelect').value;
 const subsequent=idx<0?[]:state.stops.slice(idx+1);
 fill($('alightSelect'),subsequent.map(s=>({value:s.stop_seq,label:`${s.stop_seq}. ${s.name}`})),subsequent.length?'Select alighting stop':'No subsequent stops');
 if(subsequent.length)$('alightSelect').value=subsequent.some(s=>String(s.stop_seq)===previous)?previous:String(subsequent.at(-1).stop_seq);
 updateRideStops();
}
function updateRideStops(){
 const board=chosenStop();if(!board)return;
 const from=state.stops.indexOf(board),dest=state.stops.findIndex(s=>String(s.stop_seq)===$('alightSelect').value);
 if(from<0||dest<=from)return;
 const routeStops=state.stops.slice(from,dest+1).map((s,i,a)=>`${s.name}${i===0?' · Boarding stop':i===a.length-1?' · Destination':''}`);
 window.configureRideStops?.(routeStops);
}
function reportContext(){
 const stop=chosenStop();
 if(!stop)return;
 $('reportRoute').value=`${activeRouteName()} · ${$('directionSelect').selectedOptions[0]?.textContent||state.direction}`;
 $('reportStop').value=stop.name;
}

async function loadRoutes(){
 const token=++state.requestToken;
 state.stops=[];state.variants=[];state.routeId=null;state.routeSeq=null;state.etaToken++;
 fill($('routeSelect'),[],'Loading…');fill($('directionSelect'),[],'Select a route first');fill($('stopSelect'),[],'Select a direction first');
 try{
  status('Loading official '+state.region+' green minibus routes…');
  const data=await api(`/api/gmb/routes/${state.region}`);if(token!==state.requestToken)return;
  $('apiStatus').textContent='● Official route data connected';$('apiStatus').className='badge';
  const all=data.routes.map(String).sort((a,b)=>a.localeCompare(b,'en',{numeric:true}));
  fill($('routeSelect'),all.map(x=>({value:x,label:x})),'Select route');
  const defaultRoute=all.includes('69')&&state.region==='HKI'?'69':(all[0]||'');
  if(defaultRoute){$('routeSelect').value=defaultRoute;await loadGmbVariants()}
  else status('No routes available in this region.',true);
 }catch(err){if(token!==state.requestToken)return;status('Could not load official routes: '+err.message,true);$('apiStatus').textContent='● API unavailable / Check connection';$('apiStatus').className='badge warn';fill($('routeSelect'),[],'Routes unavailable')}
}
async function loadGmbVariants(){
 const route=$('routeSelect').value;if(!route)return;
 const token=++state.requestToken; state.etaToken++;state.route=route;state.stops=[];
 fill($('directionSelect'),[],'Loading…');fill($('stopSelect'),[],'Select a direction first');
 try{
  status('Loading route variants and directions…');
  const data=await api(`/api/gmb/route/${state.region}/${encodeURIComponent(route)}`);
  if(token!==state.requestToken)return;
  state.variants=data.variants;
  fill($('directionSelect'),data.variants.map((v,i)=>({value:i,
    label:`${v.origin||'Origin'} → ${v.destination||'Destination'} [ID:${v.route_id} / ${v.route_seq}] ${v.description||''}`})), 'Select direction / service variant');
  if(data.variants.length){$('directionSelect').value='0';await loadGmbStops()}
  else status('No variants returned for this route.',true);
 }catch(err){if(token!==state.requestToken)return;status('Could not load route details: '+err.message,true)}
}
async function loadGmbStops(){
 const v=chosenVariant();if(!v)return;
 state.routeId=v.route_id;state.routeSeq=v.route_seq;
 const token=++state.requestToken;state.etaToken++;state.stops=[];fill($('stopSelect'),[],'Loading stops…');
 try{
  status(`Loading ${state.route}: ${v.origin} → ${v.destination} official stop sequence…`);
  const data=await api(`/api/gmb/stops/${v.route_id}/${v.route_seq}`);
  if(token!==state.requestToken)return;
  state.stops=data.stops;
  fill($('stopSelect'),data.stops.map(s=>({value:s.stop_seq,label:`${s.stop_seq}. ${s.name}`})),'Select boarding stop');
  // Use stop_seq identity; circular routes can repeat the same stop_id.
  if(data.stops.length){$('stopSelect').value=String(data.stops[0].stop_seq);configureAlighting();status(`Official route: ${data.stops.length} stops loaded. Choose your boarding stop to check arrivals.`)}
  else status('No official stop data for this route.',true);
 }catch(err){if(token!==state.requestToken)return;status('Could not load stops: '+err.message,true)}
}

async function loadBusStops(){
 const provider=state.provider,route=$('routeInput').value.trim().toUpperCase();
 if(!/^[A-Za-z0-9]{1,12}$/.test(route)){status('Enter a valid bus route number, e.g. 6 or 107',true);return false}
 const direction=$('directionSelect').value;
 if(!['inbound','outbound'].includes(direction)){status('Select direction',true);return false}
 const token=++state.requestToken;
 state.route=route;state.direction=direction;state.stops=[];fill($('stopSelect'),[],'Loading operator stops…');
 const qs=new URLSearchParams({route,direction});if(provider==='KMB')qs.set('service_type','1');
 try{
  status(`Looking up ${provider} ${route} (${direction}) stops…`);
  const d=await api(`/api/bus/${provider.toLowerCase()}/stops?${qs}`);
  if(token!==state.requestToken)return false;
  state.stops=d.stops;
  fill($('stopSelect'),d.stops.map(s=>({value:s.stop_seq,label:`${s.stop_seq}. ${s.name} / ${s.stop_id}`})),'Select bus stop');
  if(d.stops.length){$('stopSelect').value=String(d.stops[0].stop_seq);configureAlighting();void hydrateStopNames(token);status(`${d.stops.length} official stops loaded. Choose a stop to check arrivals.`);return true}
  status('No stops found. Try another direction or route.',true);return false;
 }catch(e){if(token===state.requestToken)status('Could not load bus stops: '+e.message,true);return false}
}

// Citybus exposes names through individual stop endpoints. Resolve progressively
// with bounded concurrency; keep route selection responsive during enrichment.
async function hydrateStopNames(token){
 if(state.provider!=='CTB')return;
 const queue=[...state.stops];
 async function worker(){
  while(queue.length && token===state.requestToken){
   const stop=queue.shift();
   try{
    const data=await api(`/api/bus/ctb/stop/${stop.stop_id}`);
    if(token!==state.requestToken)return;
    if(data.name){
     stop.name=data.name;
     const option=[...$('stopSelect').options].find(o=>o.value===String(stop.stop_seq));
     if(option)option.textContent=`${stop.stop_seq}. ${stop.name}`;
     configureAlighting();
    }
   }catch{/* Keep the stable stop ID when details are unavailable. */}
  }
 }
 await Promise.all(Array.from({length:Math.min(4,queue.length)},worker));
}

async function loadEta(){
 const stop=chosenStop();if(!stop){status('Load a route and select a stop first.',true);return}
 const token=++state.etaToken;
 $('etaRouteContext').textContent=`${activeRouteName()} · ${stop.name} (stop ${stop.stop_seq})`;
 setActiveEta('loading','Checking…');
 $('liveEtaItems').replaceChildren(makeTextBlock('Loading official arrivals…'));
 $('lastFetched').textContent='Fetching data…';
 let url;
 if(state.provider==='GMB')url=`/api/gmb/eta/${state.routeId}/${state.routeSeq}/${stop.stop_seq}`;
 else{
   const q=new URLSearchParams({route:state.route,stop_id:stop.stop_id,direction:state.direction});
   if(state.provider==='KMB')q.set('service_type','1');
   url=`/api/bus/${state.provider.toLowerCase()}/eta?${q}`;
 }
 try{
  const result=await api(url);if(token!==state.etaToken)return;
  $('apiStatus').textContent='● Official data received';$('apiStatus').className='badge';
  const valid=result.status==='fresh'&&Array.isArray(result.etas)&&result.etas.length>0;
  setActiveEta(result.status, result.status==='fresh'?(valid?'Official data · Current':'Official data · No predictions'):
      result.status==='stale'?'Official data is outdated':result.status==='unavailable'?'Arrivals unavailable at this stop':'Timestamp unconfirmed');
  $('lastFetched').textContent=`Generated: ${fmtLocal(result.generated_at)} · ${result.source}`;
  $('liveEtaItems').replaceChildren();
  if(!valid){
    $('liveEtaItems').append(makeTextBlock(result.message||'No fresh arrivals are available. The service may not be running; please try again later.'));
  }else{
    result.etas.forEach((eta,i)=>{
      const wrap=document.createElement('div');wrap.className='eta-block';
      const title=document.createElement('div');title.className='label';title.textContent=`Official arrival · ${i+1}`;
      const val=document.createElement('div');val.className='number';val.textContent=eta.minutes===null?'—':String(eta.minutes);
      if(eta.minutes!==null){const unit=document.createElement('span');unit.className='unit';unit.textContent=' min';val.append(unit)}
      const detail=document.createElement('div');detail.className='help';detail.textContent=`Expected ${fmtTime(eta.timestamp)}${eta.remark?' · '+eta.remark:''}`;
      wrap.append(title,val,detail);$('liveEtaItems').append(wrap);
    });
  }
  status(`${activeRouteName()} · ${stop.name} | ETA status: ${result.status}; Generated: ${fmtLocal(result.generated_at)}`);
  void loadCoordinates(stop);
  void loadLab();
 }catch(e){
   if(token!==state.etaToken)return;
   $('apiStatus').textContent='● Official source unavailable';$('apiStatus').className='badge warn';
   setActiveEta('error','Official data unavailable');$('lastFetched').textContent='Request failed; no live predictions';
   $('liveEtaItems').replaceChildren(makeTextBlock('No verified arrival estimate: '+e.message));
   status('Request failed: '+e.message,true);
 }
}
function makeTextBlock(text){const div=document.createElement('div');div.className='note';div.textContent=text;return div}

async function loadCoordinates(stop){
 const routeAtRequest=state.provider,stopAtRequest=stop.stop_id;
 const panel=$('realLocationPanel'),title=$('stopLocationTitle'),txt=$('stopLocationText'),link=$('officialMapLink');
 title.textContent=stop.name;txt.textContent='Looking up official stop coordinates…';link.hidden=true;
 try{
   const endpoint=routeAtRequest==='GMB'?`/api/gmb/stop/${stop.stop_id}`:
       `/api/bus/${routeAtRequest.toLowerCase()}/stop/${stop.stop_id}`;
   const d=await api(endpoint);
   if(state.provider!==routeAtRequest||chosenStop()?.stop_id!==stopAtRequest)return;
   if(d.latitude==null||d.longitude==null||!Number.isFinite(Number(d.latitude))||!Number.isFinite(Number(d.longitude)))throw Error('No valid coordinates available.');
   const lat=Number(d.latitude),lon=Number(d.longitude);
   if(lat<21.5||lat>23||lon<113||lon>115)throw Error('Coordinates are outside Hong Kong.');
   const actualName=d.name||stop.name;
   title.textContent=actualName;
   const locationBadge=$('realLocationPanel').querySelector('.badge');if(locationBadge)locationBadge.textContent='Official coordinates · Not verified on site';
   const stopBadge=$('boarding').querySelector('.section-head .badge.grey');if(stopBadge)stopBadge.textContent='Official coordinates';
   txt.textContent=`Official coordinates: ${lat.toFixed(6)}, ${lon.toFixed(6)} · ${d.source}. Coordinates have not been checked against stop photos or boarding conditions on site.`;
   link.href=`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`;
   link.hidden=false;
   $('boarding').querySelector('.section-head .section-title').textContent=`${activeRouteName()} · ${actualName}`;
 }catch(err){if(state.provider!==routeAtRequest||chosenStop()?.stop_id!==stopAtRequest)return;txt.textContent='Stop coordinates unavailable: '+err.message+'. Check signs at the stop and official notices.';link.hidden=true;const badge=$('realLocationPanel').querySelector('.badge');if(badge)badge.textContent='Coordinates unavailable';}
}

async function loadWeather(){
 const el=$('weatherNow');el.className='note';el.textContent='Updating official weather…';
 try{
  const d=await api('/api/weather');const t=d.temperature_readings?.[0],hum=d.humidity?.[0];
  el.textContent=`Updated: ${fmtLocal(d.update_time)}. ${t?`${t.place||'Weather station'} ${t.value}°C. `:''}${hum?`Humidity ${hum.value}%. `:''}Weather station observations; not used to adjust arrivals.`;
  el.className='note ok';
 }catch(err){el.textContent='Weather unavailable: '+err.message;el.className='note error'}
}
const mtrStations={TKL:[['TKO','Tseung Kwan O · TKO'],['HAH','Hang Hau · HAH'],['POA','Po Lam · POA']],
 ISL:[['CEN','Central · CEN'],['ADM','Admiralty · ADM'],['QUB','Quarry Bay · QUB']],
 AEL:[['HOK','Hong Kong · HOK'],['KOW','Kowloon · KOW'],['AIR','Airport · AIR']]};
function mtrStationChoices(){fill($('mtrStation'),(mtrStations[$('mtrLine').value]||[]).map(([value,label])=>({value,label})))}
async function loadMtr(){
 const el=$('mtrResult');el.textContent='Loading MTR Next Train…';
 try{
 const d=await api(`/api/mtr/next-train?${new URLSearchParams({line:$('mtrLine').value,station:$('mtrStation').value})}`);
 if(d.status!=='fresh'){el.textContent='MTR data is unavailable or outdated: '+(d.message||'');return}
 el.replaceChildren();const h=document.createElement('strong');h.textContent=`${d.line} · ${d.station} (Updated: ${fmtLocal(d.generated_at)})`;el.append(h);
 const entries=d.trains.filter(r=>Number.isFinite(r.minutes)).slice(0,6);
 if(!entries.length){el.append(makeTextBlock('No train predictions available. Services may not be running.'));return}
 entries.forEach(t=>{const row=document.createElement('div');row.style.marginTop='8px';row.textContent=`${t.direction} to ${t.destination_code||'—'} · ${t.minutes} min · Platform ${t.platform||'—'}`;el.append(row)});
 }catch(err){el.textContent='MTR Official data unavailable: '+err.message}
}
async function loadLab(){try{const d=await api('/api/lab/summary');$('actualArrivals').textContent=d.independent_actual_arrivals||'0';$('labCapture').textContent=`Saved ETA snapshots: ${d.eta_snapshot_rows}; independently observed arrivals: ${d.independent_actual_arrivals}. Model MAE is not available yet.`}catch{ $('labCapture').textContent='SQLite collection status unavailable.' }}

function wire(){
 $('operatorSelect').addEventListener('change',async()=>{
  state.provider=$('operatorSelect').value; state.requestToken++;state.etaToken++;state.stops=[];state.variants=[];state.routeId=null;state.routeSeq=null;state.route='';
 $('liveEtaItems').replaceChildren(makeTextBlock('Select a route and stop to check arrivals.'));setActiveEta('unknown','Not checked');
  $('regionWrap').hidden=state.provider!=='GMB'; $('routeSelectWrap').hidden=state.provider!=='GMB';
  $('routeInputWrap').hidden=state.provider==='GMB';
  fill($('stopSelect'),[],'Search for a route first');
  if(state.provider==='GMB'){await loadRoutes()}
  else{fill($('directionSelect'),[{value:'outbound',label:'Outbound'},{value:'inbound',label:'Inbound'}]);$('directionSelect').value='outbound';status(`Enter ${state.provider} route number and select Find arrivals.`)}
 });
 $('regionSelect').addEventListener('change',()=>{state.region=$('regionSelect').value;void loadRoutes()});
 $('routeSelect').addEventListener('change',()=>void loadGmbVariants());
 $('directionSelect').addEventListener('change',()=>{state.etaToken++;if(state.provider==='GMB')void loadGmbStops();else{state.stops=[];fill($('stopSelect'),[],'Search to load stops for this direction');}});
 $('stopSelect').addEventListener('change',()=>{state.etaToken++;setActiveEta('unknown','Not checked');$('liveEtaItems').replaceChildren(makeTextBlock('Check arrivals for the selected stop.'));configureAlighting();reportContext();});
 $('alightSelect').addEventListener('change',updateRideStops);
 $('lookupEta').addEventListener('click',async()=>{
  if(state.provider!=='GMB'&&(state.route!==$('routeInput').value.trim().toUpperCase()||!state.stops.length||state.direction!==$('directionSelect').value)){
   const ok=await loadBusStops();if(!ok)return;
  }
  if(!chosenStop()){status('Choose a stop first.',true);return}
  reportContext();
  document.querySelector('[data-screen="boarding"]')?.click();
  await loadEta();
 });
 $('refreshEta').addEventListener('click',()=>void loadEta());
 $('refreshWeather').addEventListener('click',()=>void loadWeather());
 $('mtrLine').addEventListener('change',mtrStationChoices);
 $('lookupMtr').addEventListener('click',()=>void loadMtr());
 mtrStationChoices();
 refreshTimer=setInterval(()=>{if(document.getElementById('boarding').classList.contains('active')&&chosenStop()&&!document.hidden)void loadEta()},60000);
 window.hkRetryRoutes=()=>{if(state.provider==='GMB')return loadRoutes();return loadBusStops()};
 if(location.protocol==='file:'){
  status('Open start.py in IDLE and press F5. Use the HTTP address printed in IDLE, not index.html.',true);
  $('apiStatus').textContent='Local server required · Run start.py';$('apiStatus').className='badge warn';
  return;
 }
 void loadRoutes();void loadWeather();void loadLab();
 // Warn when somebody opened the HTML as file:// instead of using backend.
 if(location.protocol==='file:')status('Run ./run.sh and open http://127.0.0.1:8000 to connect to live data.',true);
}
wire();
})();
