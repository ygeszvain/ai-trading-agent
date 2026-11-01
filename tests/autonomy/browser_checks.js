async page => {
  const errors=[],origins=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>origins.push(new URL(r.url()).origin));
  const assert=(ok,reason)=>{if(!ok)throw new Error(reason);};
  await page.goto('http://127.0.0.1:8028/autonomy');
  await page.getByRole('heading',{name:'Bounded autonomy — LIVE_NOT_AUTHORIZED',exact:true}).waitFor();
  for(const name of ['Activate','Renew authority','Resume','Promote']){
    assert(await page.getByRole('button',{name,exact:true}).isDisabled(),name+' enabled');
  }
  const response=await page.request.get('http://127.0.0.1:8028/api/v1/autonomy');
  assert(response.status()===200,'read failed');
  const json=await response.json();
  assert(json.runtime_approved_capital_usd==='0' && !json.actual_dispatch_allowed,'authority changed');
  assert(json.real_authorization===null && json.automatic_change_class==='NONE','authorization invented');
  const body=await page.locator('body').textContent();
  assert(body.includes(json.mock.champion_hash) && body.includes(json.mock.envelope_hash),'frozen bindings absent');
  assert(body.includes('EXTERNAL_VALIDATION_PENDING') && body.includes('UNSIGNED_BLOCKED'),'evidence mixed');
  assert(json.mock.paused && !json.mock.envelope_current && !json.mock.monitor_current,'demo expiry masked');
  assert(json.orders.length===6 && json.audit.some(x=>x.event_type==='m7_denied_state_change'),'failed evidence absent');
  for(const action of ['activate','renew','widen','promote','resume','preferences']){
    const res=await page.request.post('http://127.0.0.1:8028/api/v1/autonomy/'+action,{headers:{Origin:'http://127.0.0.1:8028'},data:{capital:'999999'}});
    assert(res.status()===403,'accepted '+action);
  }
  assert((await (await page.request.get('http://127.0.0.1:8028/api/v1/autonomy?run_id=alien')).json()).mock===null,'scope leaked');
  for(const [name,width,height] of [['desktop',1440,1000],['narrow',390,844]]){
    await page.setViewportSize({width,height});
    await page.goto('http://127.0.0.1:8028/autonomy');
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.screenshot({path:'output/playwright/m7-autonomy-'+name+'.png',animations:'disabled'});
    assert(await page.locator('body').evaluate(el=>el.scrollWidth<=window.innerWidth),'horizontal overflow');
  }
  assert(errors.length===0,JSON.stringify(errors));
  assert(origins.every(x=>x==='http://127.0.0.1:8028'),'external request');
  return {authority:json.authority,liveCapital:'0',changeClass:'NONE',orders:json.orders.length,deniedPosts:6,pageErrors:errors.length,externalRequests:0};
}
