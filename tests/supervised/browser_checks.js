async page => {
  const errors=[],origins=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>origins.push(new URL(r.url()).origin));
  await page.goto('http://127.0.0.1:8028/readiness');
  await page.getByRole('heading',{name:'Supervised pilot readiness — LIVE_NOT_AUTHORIZED',exact:true}).waitFor();
  const assert=(ok,reason)=>{if(!ok)throw new Error(reason);};
  assert(await page.getByRole('button',{name:'Activate pilot',exact:true}).isDisabled(),'activation enabled');
  assert(await page.getByRole('button',{name:'Approve intent',exact:true}).isDisabled(),'approval enabled');
  const json=await (await page.request.get('http://127.0.0.1:8028/api/v1/readiness')).json();
  assert(json.runtime.approved_capital_usd==='0' && !json.actual_dispatch_allowed,'financial authority changed');
  const body=await page.locator('body').textContent();
  assert(body.includes(json.orders[0].intent.risk_snapshot_hash),'risk binding absent');
  assert(body.includes(json.approvals.find(x=>x.record.intent_hash).record.intent_hash),'approval binding absent');
  assert(body.includes('EXTERNAL_VALIDATION_PENDING') && body.includes('UNSIGNED_BLOCKED'),'evidence mixed');
  assert(json.coverage.audit_returned===json.audit.length,'coverage incorrect');
  for(const action of ['approve','activate','dispatch','resume','cancel']){
    const res=await page.request.post('http://127.0.0.1:8028/api/v1/readiness/'+action,{headers:{Origin:'http://127.0.0.1:8028'},data:{enabled:true}});
    assert(res.status()===403,'server accepted '+action);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:8028/readiness');
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.screenshot({path:'output/playwright/m6-readiness-desktop.png',animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await page.goto('http://127.0.0.1:8028/readiness');
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.screenshot({path:'output/playwright/m6-readiness-narrow.png',animations:'disabled'});
  assert(await page.locator('header').count()===1,'duplicate header');
  assert(await page.getByRole('heading',{name:'Supervised pilot readiness — LIVE_NOT_AUTHORIZED',exact:true}).isVisible(),'authority label hidden');
  assert(await page.locator('body').evaluate(el=>el.scrollWidth<=window.innerWidth),'narrow overflow');
  assert(errors.length===0,JSON.stringify(errors));
  assert(origins.every(x=>x==='http://127.0.0.1:8028'),'external browser request');
  return {authority:json.authority,actualDispatch:false,orders:json.orders.length,auditEvents:json.audit.length,pageErrors:errors.length,externalOrigins:0};
}
