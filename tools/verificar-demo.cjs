// Validate the offline network boundary and fixture behavior without opening sockets.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const context={window:{},structuredClone};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'demo-fixture.js'),'utf8'),context);
(async()=>{
 const fetch=context.window.fetch;
 let status=await (await fetch('/api/status')).json();
 assert.equal(status.connected,true);assert.equal(status.active.length,3);
 assert.equal(status.destination,'/mnt/media/GoogleDrive');
 await fetch('/api/pause',{method:'POST',body:'{}'});
 status=await (await fetch('/api/status')).json();assert.equal(status.paused,true);assert.equal(status.active.length,0);
 await fetch('/api/start',{method:'POST',body:'{}'});
 status=await (await fetch('/api/status')).json();assert.equal(status.paused,false);
 for(const endpoint of ['connect','client','maintenance-start','recovery-export','cleanup-confirm']){
  const response=await fetch('/api/'+endpoint,{method:'POST',body:'{}'});assert.equal(response.status,400);
 }
 assert.equal((await fetch('https://example.invalid/')).status,400);
 const diagnostics=await (await fetch('/api/diagnostics')).json();assert.equal(diagnostics.current.disks.length,4);
 const html=fs.readFileSync(path.join(root,'docs/demo.html'),'utf8');
 assert(!/<script[^>]+src=/i.test(html),'Demo must embed scripts');
 assert(!/<link[^>]+rel="stylesheet"/i.test(html),'Demo must embed styles');
 assert(html.includes('OFFLINE DEMO'));assert(html.includes('window.fetch=async'));
 console.log('Offline demo OK: synthetic status, diagnostics, pause/resume, embedded assets and blocked real actions.');
})().catch(error=>{console.error(error);process.exitCode=1;});
