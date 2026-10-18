const {JSDOM,VirtualConsole}=require('jsdom');
const fs=require('fs'), assert=require('node:assert/strict');
const root=require('node:path').resolve(__dirname,'..');
const fixtures=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const errors=[], calls=[];
const html=fs.readFileSync(root+'/index.html','utf8').replace(/<script defer src="\/assets\/([^"]+)"><\/script>/g,(_,f)=>'<script>'+fs.readFileSync(root+'/static/'+f,'utf8')+'</script>');
let offline=false, hang=false;
const vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
const dom=new JSDOM(html,{
 url:'http://localhost:8000/',runScripts:'dangerously',virtualConsole:vc,
 beforeParse(w){w.scrollTo=()=>{};w.fetch=async(url,opts={})=>{
  if(hang)return new Promise((_,reject)=>opts.signal.addEventListener('abort',()=>reject(new Error('aborted'))));
  if(offline)throw new TypeError('offline');
  calls.push(url);if(!(url in fixtures))throw Error('Uncovered API '+url);
  return {ok:true,status:200,json:async()=>structuredClone(fixtures[url])};
 };}
});
const w=dom.window,d=w.document,$=id=>d.getElementById(id),delay=ms=>new Promise(r=>setTimeout(r,ms));
const change=(id,value)=>{$(id).value=value;$(id).dispatchEvent(new w.Event('change'));};
(async()=>{
 await delay(120);
 assert.equal($('routeSelect').value,'69');assert.equal($('stopSelect').value,'1');
 $('lookupEta').click();await delay(60);
 assert.match($('etaHealth').textContent,/Current/);assert.match($('liveEtaItems').textContent,/5/);
 assert.match($('officialMapLink').href,/openstreetmap/);
 $('boardNow').click();assert.ok($('ride').classList.contains('active'));
 $('nextStop').click();assert.match($('rideHeadline').textContent,/Information|Stop/);
 change('operatorSelect','KMB');$('routeInput').value='1A';$('lookupEta').click();await delay(60);
 assert.match($('etaHealth').textContent,/Current/);
 change('operatorSelect','CTB');$('routeInput').value='1';change('directionSelect','inbound');$('lookupEta').click();await delay(60);
 assert.match($('etaHealth').textContent,/Current/);
 $('lookupMtr').click();await delay(50);assert.match($('mtrResult').textContent,/Platform/);
 $('nlPrefInput').value='Less walking and fewer transfers';$('nlPrefBtn').click();await delay(50);
 assert.ok($('prefWalk').classList.contains('active'));assert.ok($('prefTransfer').classList.contains('active'));
 $('submitReport').click();assert.equal($('reportCount').textContent,'1 report');
 $('prepareAssist').click();assert.match($('assistDraft').textContent,/draft/);
 for(const screen of ['home','boarding','ride','report','access','lab','live','more']){
  d.querySelectorAll('.screen').forEach(e=>e.classList.toggle('active',e.id===screen));
  assert.ok(!/[\u3400-\u9fff]/.test($(screen).textContent),'English screen '+screen);
 }
 $('checkConnections').click();await delay(50);assert.match($('connectionResults').textContent,/Connected/);
 offline=true;$('refreshEta').click();await delay(50);
 assert.match($('etaHealth').textContent,/unavailable/);assert.ok(!$('liveEtaItems').querySelector('.number'));
 offline=false;change('operatorSelect','GMB');await delay(120);
 assert.match($('apiStatus').textContent,/connected/);
 assert.equal($('downloadDiagnostics').disabled,false);
 $('retryConnections').click();await delay(120);
 assert.equal($('routeSelect').value,'69');
 hang=true;
 const realSetTimeout=w.setTimeout.bind(w);w.setTimeout=(fn,ms,...args)=>realSetTimeout(fn,ms===12000?15:ms,...args);
 await assert.rejects(w.hkRequest('/api/weather'),/Connection interrupted/);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',checks:['GMB selection, ETA and map','manual ride','KMB ETA','Citybus ETA','MTR','AI preferences','local report','assistance draft','English screens','connection diagnostics','offline recovery','abort deadline'],apiRequests:calls.length,browserRendering:'not tested (DOM simulation)'},null,2));
})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>w.close());
