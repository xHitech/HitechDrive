let diagnosticInitialized=false, diagnosticBusy=false, lastDiagnostic=null;
const diskColors=['#6D28D9','#D97706','#059669','#DB2777','#2563EB','#475569'];
function plot(canvas,history,series,fixedMax=null){
 const width=canvas.clientWidth||450,height=190,dpr=Math.min(window.devicePixelRatio||1,2);
 canvas.width=width*dpr;canvas.height=height*dpr;
 const c=canvas.getContext('2d');c.scale(dpr,dpr);
 const left=44,right=12,top=16,bottom=28,w=width-left-right,h=height-top-bottom;
 const all=series.flatMap(s=>history.map(p=>s.value(p))).filter(v=>v!==null&&Number.isFinite(v));
 const max=fixedMax||Math.max(1,...all)*1.15;
 const theme=getComputedStyle(document.documentElement),grid=theme.getPropertyValue('--chart-grid').trim()||'#E9E7EF',text=theme.getPropertyValue('--chart-text').trim()||'#766A83';
 c.font='11px system-ui';c.lineWidth=1;
 for(let i=0;i<=4;i++){let y=top+h-i*h/4;c.strokeStyle=grid;c.beginPath();c.moveTo(left,y);c.lineTo(width-right,y);c.stroke();c.fillStyle=text;c.fillText((max*i/4).toFixed(max<10?1:0),3,y+4);}
 if(history.length<2){c.fillStyle=text;c.fillText('Aguardando amostras…',left+14,top+h/2);return;}
 const first=history[0].time,last=history[history.length-1].time,span=Math.max(.01,last-first);
 for(const s of series){c.strokeStyle=s.color;c.lineWidth=2;c.beginPath();let drawing=false;for(const p of history){let v=s.value(p);if(v===null||!Number.isFinite(v)){drawing=false;continue;}let x=left+(p.time-first)/span*w,y=top+h-Math.min(max,Math.max(0,v))/max*h;if(drawing)c.lineTo(x,y);else c.moveTo(x,y);drawing=true;}c.stroke();}
 c.fillStyle=text;c.fillText('-'+Math.round(span)+' s',left,height-8);c.fillText('agora',width-44,height-8);
}
function metricText(value,digits=1){return value===null||value===undefined?'—':Number(value).toFixed(digits);}
function renderDiagnostics(d){
 lastDiagnostic=d;
 const p=d.current,disks=p.disks||[],history=d.history||[];
 const arrays=d.arrays||[];
 $('raid-health').textContent=arrays.length?arrays.map(a=>a.name+' · '+a.level.toUpperCase()+' · '+a.members.length+' membros · '+(a.degraded===0?'sem membros ausentes':a.degraded===null?'estado indisponível':a.degraded+' membro(s) ausente(s)')+' · operação: '+a.sync_action).join(' | '):'Não foi possível ler o estado de um RAID10 neste ambiente.';
 plot($('disk-chart'),history,disks.map((disk,i)=>({color:diskColors[i%diskColors.length],value:p=>{const match=p.disks.find(x=>x.name===disk.name);return match&&match.metrics?match.metrics.busy_pct:null;}})),100);
 $('disk-legend').textContent=disks.map((disk,i)=>['Roxo','Laranja','Verde','Rosa','Azul','Cinza'][i%diskColors.length]+': '+disk.name).join(' · ');
 plot($('network-chart'),history,[{color:'#6D28D9',value:p=>p.google_bps===null?null:p.google_bps/1048576},{color:'#059669',value:p=>p.rx_bps===null?null:p.rx_bps/1048576},{color:'#D97706',value:p=>p.networks.length?p.networks.reduce((sum,n)=>sum+(n.tx_bps||0),0)/1048576:null}]);
 $('disk-metrics').replaceChildren(...disks.map(disk=>{let article=document.createElement('article'),title=document.createElement('span'),value=document.createElement('strong'),detail=document.createElement('small'),model=document.createElement('small'),m=disk.metrics;title.textContent=disk.name;value.textContent=m?metricText(m.busy_pct)+'% ocupado':'Aguardando…';model.textContent=disk.model;detail.textContent=m?'Lê '+bytes(m.read_bps)+'/s · Grava '+bytes(m.write_bps)+'/s · Latência '+metricText(m.await_ms)+' ms · Fila '+metricText(m.queue):'Taxas disponíveis após a segunda amostra.';if(m&&m.busy_pct>=90)article.className='busy';article.append(title,value,model,detail);return article;}));
 const net=p.networks.map(n=>n.name+': recebe '+(n.rx_bps===null?'—':bytes(n.rx_bps)+'/s')+' · envia '+(n.tx_bps===null?'—':bytes(n.tx_bps)+'/s')+' · '+(n.link_rx_pct===null?'velocidade do enlace desconhecida':metricText(n.link_rx_pct)+'% do enlace de '+n.link_mbps+' Mbps')).join(' | ');
 $('network-metrics').textContent='Google: '+(p.google_bps===null?'—':bytes(p.google_bps)+'/s')+' · Internet: '+(p.internet_pct===null?'informe seu plano para estimar %':metricText(p.internet_pct)+'% do plano informado')+' · Espera por I/O no sistema: '+metricText(p.io_pressure_pct)+'%'+(net?' | '+net:' | Placa física indisponível.');
 const labels={api:'Resposta da API',receive:'Leitura Google/rede',write:'Gravação local',verify:'Checksum',throttle:'Limitador de banda'};
 $('stage-metrics').replaceChildren(...Object.entries(labels).map(([key,label])=>{let div=document.createElement('div'),name=document.createElement('span'),bar=document.createElement('progress');const value=p.stages_pct[key];name.textContent=label+': '+metricText(value)+'%';bar.max=100;bar.value=value||0;div.append(name,bar);return div;}));
 $('diagnostic-warnings').replaceChildren(...d.warnings.map(message=>{let li=document.createElement('li');li.textContent=message;return li;}));
 if(!diagnosticInitialized){$('internet-mbps').value=String(d.internet_mbps||0);diagnosticInitialized=true;}
}
async function refreshDiagnostics(){if(diagnosticBusy||document.hidden||$('diagnostics-page').hidden)return;diagnosticBusy=true;try{const r=await fetch('/api/diagnostics');if(r.status===404){$('raid-health').textContent='Reinicie o serviço no servidor para ativar os gráficos desta atualização.';return;}if(!r.ok)throw Error('Falha ao consultar diagnóstico');renderDiagnostics(await r.json());}catch(e){$('raid-health').textContent='Diagnóstico indisponível: '+e.message;}finally{diagnosticBusy=false;}}
$('save-internet').addEventListener('click',async()=>{try{const input=$('internet-mbps');if(!input.value.trim()||!input.checkValidity())throw Error('Informe Mbps válidos, ou 0 para desconhecido.');await post('diagnostics-settings',{internet_mbps:Number(input.value)});toast('Referência de internet salva.');setTimeout(refreshDiagnostics,1100);}catch(e){toast(e.message);}});
window.addEventListener('hitech:navigate',event=>{if(event.detail==='diagnostics')refreshDiagnostics();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshDiagnostics();});
refreshDiagnostics();setInterval(refreshDiagnostics,2500);

window.addEventListener('hitech:theme',()=>{if(lastDiagnostic&&!$('diagnostics-page').hidden)renderDiagnostics(lastDiagnostic);});
