(() => {
  const button=document.getElementById('checkConnections');
  const results=document.getElementById('connectionResults');
  let lastReport=null;
  document.getElementById('retryConnections').addEventListener('click',()=>window.hkRetryRoutes?.());
  document.getElementById('downloadDiagnostics').addEventListener('click',()=>{
    if(!lastReport)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(lastReport,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='HKOnTransit-diagnostics.json';
    document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  button.addEventListener('click', async () => {
    button.disabled=true;
    results.textContent='Checking official sources…';
    try {
      const data=await window.hkRequest('/api/diagnostics');
      lastReport=data;document.getElementById('downloadDiagnostics').disabled=false;
      results.replaceChildren();
      for (const source of data.providers) {
        const row=document.createElement('div');
        row.textContent=`${source.provider}: ${source.connection==='ok'?'Connected':'Unavailable'} · ${source.elapsed_ms} ms${source.message?' · '+source.message:''}`;
        results.append(row);
      }
      const stamp=document.createElement('small');
      stamp.textContent='Checked '+new Date(data.checked_at).toLocaleString('en-HK',{timeZone:'Asia/Hong_Kong'})+' HKT';
      results.append(stamp);
    } catch(error) { results.textContent=error.message; }
    finally { button.disabled=false; }
  });
})();
