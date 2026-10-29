'use strict';
let cleanupPreview = null;
let maintenanceBusyAction = false;
function maintenanceReady() {
  if (!latest || !latest.maintenance_supported) throw Error('Reinicie drive-espelho no servidor para carregar a manutenção.');
}
function rate() {
  const input = $('maintenance-rate');
  if (!input.value.trim() || !input.checkValidity()) throw Error('Informe um limite válido em MiB/s.');
  return Number(input.value);
}
function renderMaintenance(s) {
  const task = s.maintenance || {}, running = task.state === 'running';
  const drained = s.paused && !(s.active || []).length && !['baixando','verificando'].includes(s.phase);
  const ready = !!s.maintenance_supported && drained && !running && !maintenanceBusyAction;
  $('maintenance-compatibility').hidden = !!s.maintenance_supported;
  for (const id of ['recovery-export','cleanup-preview','audit-start','rebuild-start']) $(id).disabled = !ready;
  $('recovery-file').disabled = !ready || s.tracked > 0;
  $('recovery-checkpoint').disabled = !ready || s.tracked > 0 || !task.checkpoint_available;
  $('maintenance-cancel').disabled = !running;
  $('cleanup-delete').disabled = !ready || !cleanupPreview;
  const names = {audit:'Auditoria',rebuild:'Reconhecimento'};
  const states = {running:'em andamento',complete:'concluído',cancelled:'cancelado',error:'com erro'};
  $('maintenance-task').textContent = task.kind
    ? (names[task.kind] || 'Manutenção')+' '+(states[task.state] || task.state)+' · '+task.done+' / '+task.total+' arquivos · '+bytes(task.bytes)+' lidos'+(task.current?' · '+task.current:'')+(task.error?' · '+task.error:'')
    : 'Pause a sincronização e escolha uma operação. Nenhuma verificação pesada começa automaticamente.';
  $('maintenance-progress').value = task.total ? Math.min(100,task.done/task.total*100) : 0;
  const report = task.report || {};
  $('maintenance-report').textContent = report.finished
    ? 'Último relatório: '+report.finished+' · '+report.ok+' conferidos · '+report.failed+' com problema · '+report.skipped+' sem referência/ignorados. Resultado: '+report.state
    : 'Nenhum relatório de manutenção ainda.';
  $('maintenance-findings').replaceChildren(...(report.findings || []).map(item => {
    const li=document.createElement('li'),name=document.createElement('strong'),message=document.createElement('p');
    name.textContent=item.path;message.textContent=item.message;li.append(name,message);return li;
  }));
  $('system-alerts').hidden = !(s.alerts || []).length;
  $('system-alerts').replaceChildren(...(s.alerts || []).map(alert => {
    const p=document.createElement('p'),link=document.createElement('a');p.append(document.createTextNode(alert.message));
    link.href=alert.kind==='auth'?'#settings':alert.kind==='raid'||alert.kind==='storage'?'#diagnostics':'#maintenance';
    link.textContent='Ver detalhes ↗';p.append(link);return p;
  }));
}
async function maintenanceAction(callback) {
  if (maintenanceBusyAction) return;
  maintenanceBusyAction=true;
  if(latest) renderMaintenance(latest);
  try { maintenanceReady();await callback(); }
  catch(error){toast(error.message);}
  finally {maintenanceBusyAction=false;await refresh();}
}
$('recovery-export').addEventListener('click',()=>maintenanceAction(async()=>{
  const bundle=await post('recovery-export',{},60000);
  const blob=new Blob([JSON.stringify(bundle,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download='hitechdrive-recovery-backup.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
  toast('Backup privado gerado, sem tokens OAuth. Guarde-o fora do computador que pretende reinstalar.');
}));
$('recovery-file').addEventListener('change',event=>maintenanceAction(async()=>{
  const file=event.target.files[0];if(!file)return;
  try {
    if(file.size>32*1024*1024)throw Error('O backup excede 32 MiB.');
    await post('recovery-import',JSON.parse(await file.text()),60000);
    toast('Manifesto recuperado. Reconecte a conta Google se necessário.');
  } finally {$('recovery-file').value='';}
}));
$('recovery-checkpoint').addEventListener('click',()=>maintenanceAction(async()=>{
  await post('recovery-checkpoint-import',{},60000);toast('Checkpoint recuperado; a réplica permanece pausada para revisão.');
}));
for(const [id,kind] of [['audit-start','audit'],['rebuild-start','rebuild']]){
  $(id).addEventListener('click',()=>maintenanceAction(async()=>{
    await post('maintenance-start',{kind,rate_mib:rate()});toast('Verificação iniciada. Pode cancelar sem apagar os arquivos.');
  }));
}
$('maintenance-cancel').addEventListener('click',()=>maintenanceAction(async()=>{
  await post('maintenance-cancel');toast('Cancelamento solicitado. Aguardando a leitura atual terminar.');
}));
$('cleanup-preview').addEventListener('click',()=>maintenanceAction(async()=>{
  cleanupPreview=await post('cleanup-preview',{},60000);
  $('cleanup-summary').textContent=cleanupPreview.count+' arquivos revisados · Lixeira: '+bytes(cleanupPreview.trash_bytes)+' · Parciais: '+bytes(cleanupPreview.partial_bytes)+(cleanupPreview.count>100?' · Mostrando 100 primeiros.':'');
  $('cleanup-files').replaceChildren(...cleanupPreview.entries.map(item=>{const li=document.createElement('li');li.textContent=item.path+' · '+bytes(item.size);return li;}));
  $('cleanup-confirmation').value='';
}));
$('cleanup-delete').addEventListener('click',()=>maintenanceAction(async()=>{
  if(!cleanupPreview)throw Error('Calcule o espaço e revise os arquivos primeiro.');
  const result=await post('cleanup-confirm',{token:cleanupPreview.token,kind:$('cleanup-kind').value,confirmation:$('cleanup-confirmation').value},60000);
  cleanupPreview=null;$('cleanup-files').replaceChildren();$('cleanup-confirmation').value='';
  $('cleanup-summary').textContent=result.removed+' arquivos excluídos; '+result.skipped+' alterados preservados. Gere outra prévia se necessário.';
  toast('Limpeza concluída com a confirmação fornecida.');
}));
window.addEventListener('hitech:status',event=>renderMaintenance(event.detail));
if(latest)renderMaintenance(latest);
