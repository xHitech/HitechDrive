// Runs only in the generated offline demo, never in the real service.
const demoMiB=1048576,demoGiB=1073741824;
let demoTick=0;
const demoState={csrf:'offline-demo',phase:'baixando',connected:true,credentials:true,paused:false,
 total:2400,done:1680,last_sync:null,error:'',root:'root',interval:300,workers:3,workers_live:true,
 bandwidth_mib:0,destination:'/mnt/media/GoogleDrive',progress_ready:true,total_bytes:240*demoGiB,
 copied_bytes:168*demoGiB,remaining_bytes:72*demoGiB,unknown_size_files:0,eta_seconds:1800,
 speed:42*demoMiB,overall_speed:42*demoMiB,errors:[],error_count:0,tracked:1680,alerts:[],
 events:[{time:'12:00:00',text:'Demonstração com arquivos fictícios.'}],maintenance_supported:true,
 maintenance:{state:'idle',checkpoint_available:true},active:[]};
function demoStatus(){
 if(!demoState.paused){demoTick=(demoTick+1)%30;}
 demoState.phase=demoState.paused?'pausado':'baixando';
 demoState.active=demoState.paused?[]:[
  {name:'Sample library/Animation/Short film.mp4',size:2*demoGiB,bytes:(.2+demoTick/45)*2*demoGiB,speed:18*demoMiB},
  {name:'Sample library/Music/Instrumental.flac',size:160*demoMiB,bytes:(.15+demoTick/45)*160*demoMiB,speed:10*demoMiB},
  {name:'Sample library/Books/Illustrated book.cbz',size:800*demoMiB,bytes:(.1+demoTick/45)*800*demoMiB,speed:14*demoMiB}];
 return structuredClone(demoState);
}
function demoDiagnostics(){
 const history=Array.from({length:40},(_,i)=>({time:i*2.5,google_bps:(37+Math.sin(i/4)*5)*demoMiB,
  rx_bps:(39+Math.sin(i/4)*5)*demoMiB,networks:[{tx_bps:demoMiB}],
  disks:['disk-a','disk-b','disk-c','disk-d'].map((name,j)=>({name,model:'Sample disk',
   metrics:{busy_pct:35+j*8+Math.sin(i/4+j)*12,read_bps:0,write_bps:21*demoMiB,await_ms:12+j*3,queue:.5+j*.2}}))}));
 const current=history.at(-1);Object.assign(current,{internet_pct:34,io_pressure_pct:2,
  stages_pct:{api:4,receive:66,write:20,verify:7,throttle:3},
  networks:[{name:'ethernet-demo',rx_bps:42*demoMiB,tx_bps:demoMiB,link_mbps:1000,link_rx_pct:35}]});
 return {current,history,internet_mbps:1000,warnings:[],arrays:[{name:'demo-array',level:'raid10',members:['disk-a','disk-b','disk-c','disk-d'],degraded:0,sync_action:'idle'}]};
}
window.fetch=async function(input,options={}){
 const path=String(input),method=options.method||'GET';
 const respond=(data,status=200)=>({ok:status<400,status,json:async()=>data});
 if(method==='GET'&&path==='/api/status')return respond(demoStatus());
 if(method==='GET'&&path==='/api/diagnostics')return respond(demoDiagnostics());
 const body=JSON.parse(options.body||'{}');
 if(method==='POST'&&path==='/api/pause'){demoState.paused=true;return respond({ok:true});}
 if(method==='POST'&&path==='/api/start'){demoState.paused=false;return respond({ok:true});}
 if(method==='POST'&&path==='/api/workers'){demoState.workers=body.workers;return respond({ok:true});}
 if(method==='POST'&&path==='/api/bandwidth'){demoState.bandwidth_mib=body.bandwidth_mib;return respond({ok:true});}
 return respond({error:'Offline demo: esta ação está desativada. Nenhum dado real será lido ou alterado.'},400);
};
