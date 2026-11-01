async page => {
 const errors=[],origins=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>origins.push(new URL(r.url()).origin));
 const assert=(ok,why)=>{if(!ok)throw new Error(why);};
 const origin='http://127.0.0.1:8028';
 const runs=await (await page.request.get(origin+'/api/v1/runs')).json();
 const rich=runs.payload.runs.find(r=>String(r.initial_cash).startsWith('100000'));
 const pick=rich?'?run_id='+rich.run_id:'';
 await page.goto(origin+'/'+pick);
 await page.locator('[data-books] table').waitFor();
 const current=await (await page.request.get(origin+'/api/v1/bootstrap'+pick)).json();
 assert(current.read_only,'snapshot not read only');
 assert(current.overview.payload.authority==='LIVE_NOT_AUTHORIZED','authority changed');
 const run=current.run_id;
 assert(current.overview.scope.run_id===current.equity_curve.scope.run_id,'snapshot scope differs');
 const events=await page.request.get(origin+'/api/v1/events?run_id='+run+'&cursor='+encodeURIComponent(current.cursor));
 assert(events.status()===200,'notifications failed');
 const bad=await page.request.get(origin+'/api/v1/events?run_id=alien&cursor='+encodeURIComponent(current.cursor));
 assert(bad.status()===409,'scope did not force resnapshot');
 const csv=await page.request.get(origin+'/api/v1/exports/activity.csv?run_id='+run);
 assert(csv.status()===200 && csv.headers()['x-next-cursor'],'export absent');
 for(const section of ['data','research','risk','performance','health','alerts','audit']){
  await page.goto(origin+'/'+section+'?run_id='+run);
  assert((await page.locator('body').textContent()).includes('LIVE_NOT_AUTHORIZED'),section+' authority absent');
 }
 await page.goto(origin+'/orders?run_id='+run);
 const orders=await (await page.request.get(origin+'/api/v1/orders?run_id='+run)).json();
 if(orders.payload.orders.length){
  const id=orders.payload.orders[0].order_id;
  await page.goto(origin+'/orders/'+encodeURIComponent(id)+'?run_id='+run);
  assert((await page.locator('body').textContent()).includes('SIMULATION'),'order label absent');
 }
 for(const [label,width,height] of [['desktop',1440,1000],['narrow',390,844]]){
  await page.setViewportSize({width,height});
  await page.goto(origin+'/?run_id='+run);
  await page.locator('[data-books] table').waitFor();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.screenshot({path:'output/playwright/stabilization-'+label+'.png',animations:'disabled'});
  assert(await page.locator('body').evaluate(el=>el.scrollWidth<=window.innerWidth),'horizontal overflow');
 }
 assert(errors.length===0,JSON.stringify(errors));
 assert(origins.every(x=>x===origin),'external browser request');
 return {authority:'LIVE_NOT_AUTHORIZED',run,orders:orders.payload.orders.length,
  reviewPages:7,export:'bounded synthetic only',pageErrors:errors.length,externalRequests:0};
}
