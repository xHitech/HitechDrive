'use strict';

let csrf = '';
let initialized = false;
let latest = null;
let refreshBusy = false;
let savingWorkers = false;
let toastTimer;
let errorsKey = '';
let eventsKey = '';
const busyActions = new Set();
const transferNodes = new Map();
const $ = id => document.getElementById(id);
const phases = {
  pausado: 'Sincronização pausada',
  aguardando: 'Tudo no seu ritmo',
  verificando: 'Consultando seu acervo',
  baixando: 'Copiando para o RAID',
  erro: 'Algo precisa de atenção'
};
const pages = {
  overview: ['Visão geral', 'Tudo no seu lugar.', 'Acompanhe sua cópia local, sem perder o ritmo.'],
  diagnostics: ['Desempenho', 'Cada detalhe, à vista.', 'Discos, conexão e transferências. Sem adivinhação.'],
  issues: ['Pendências', 'Nada fica para trás.', 'Veja o que precisa de atenção e retome quando quiser.'],
  activity: ['Atividade', 'Seu acervo em movimento.', 'Os últimos passos da sua sincronização.'],
  settings: ['Configurações', 'Do seu jeito.', 'Conecte sua conta e escolha como manter sua cópia local.']
};

function bytes(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const index = Math.min(4, Math.floor(Math.log(n) / Math.log(1024)));
  return (n / 1024 ** index).toFixed(index ? 1 : 0) + ' ' + ['B', 'KiB', 'MiB', 'GiB', 'TiB'][index];
}

function duration(seconds) {
  if (seconds === null || !Number.isFinite(seconds)) return 'Calculando…';
  if (seconds < 60) return 'Menos de 1 min';
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return minutes + ' min';
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + ' h ' + minutes % 60 + ' min';
  return Math.floor(hours / 24) + ' d ' + hours % 24 + ' h';
}

function toast(message) {
  $('toast').textContent = message;
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 7000);
}

function currentPage() {
  const name = window.location.hash.slice(1);
  return Object.hasOwn(pages, name) ? name : 'overview';
}

function navigate(page = currentPage()) {
  const [breadcrumb, title, description] = pages[page];
  document.querySelectorAll('[data-page]').forEach(panel => { panel.hidden = panel.dataset.page !== page; });
  document.querySelectorAll('[data-nav]').forEach(link => {
    const active = link.dataset.nav === page;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('breadcrumb').textContent = breadcrumb;
  $('page-title').replaceChildren(document.createTextNode(title.slice(0, -1)));
  const dot = document.createElement('span');
  dot.textContent = '.';
  $('page-title').append(dot);
  $('page-description').textContent = description;
  document.title = breadcrumb + ' · HitechDrive';
  window.dispatchEvent(new CustomEvent('hitech:navigate', {detail: page}));
}

async function requestJSON(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(url, {...options, signal: controller.signal});
    let value;
    try { value = await response.json(); }
    catch { throw Error('O serviço retornou uma resposta inesperada. Atualize a página e tente novamente.'); }
    if (!response.ok) {
      if (response.status === 404 && ['/api/workers', '/api/bandwidth', '/api/retry-errors'].includes(url)) {
        throw Error('O painel foi atualizado, mas o serviço ainda está na versão antiga. Reinicie drive-espelho no servidor.');
      }
      throw Error(value.error || 'Não foi possível concluir a solicitação.');
    }
    return value;
  } finally { clearTimeout(timeout); }
}

function post(path, data = {}) {
  return requestJSON('/api/' + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify(data)
  });
}

function setDisabled(id, value) { $(id).disabled = value || busyActions.has(id); }

function renderState(s) {
  $('phase').textContent = phases[s.phase] || 'Consultando serviço';
  $('badge').textContent = s.connected ? 'Conta conectada' : 'Conta não conectada';
  $('badge').dataset.connected = String(!!s.connected);
  $('badge').dataset.offline = 'false';
  $('sync-dot').dataset.running = String(['baixando', 'verificando'].includes(s.phase) && !s.paused);
  const activeCount = (s.active || []).length;
  $('current').textContent = s.paused && activeCount
    ? 'Pausando. Aguardando as transferências em andamento pararem.'
    : s.phase === 'baixando'
      ? activeCount ? activeCount + ' transferências em andamento.' : 'Preparando os próximos arquivos.'
      : s.phase === 'aguardando' && s.last_sync
        ? 'Ciclo concluído. O próximo será iniciado automaticamente.'
        : s.current || (s.connected ? 'Tudo pronto para sincronizar.' : 'Conecte sua conta em Configurações para começar.');
  $('connection').textContent = s.connected
    ? 'Autorização salva para acessar seu Drive somente para leitura.'
    : s.credentials ? 'Credenciais importadas. Agora autorize sua conta Google.' : 'Importe as credenciais do seu aplicativo Google para começar.';
  $('files').textContent = s.total + ' arquivos no acervo · ' + s.done + ' processados neste ciclo';
  $('last').textContent = s.last_sync ? 'Último ciclo: ' + s.last_sync : 'Primeiro ciclo ainda não concluído';
  $('error').textContent = s.error || '';
  $('error').hidden = !s.error;
  const draining = s.paused && (activeCount > 0 || ['baixando', 'verificando'].includes(s.phase));
  setDisabled('start', !s.connected || draining || !s.paused && ['baixando', 'verificando'].includes(s.phase));
  setDisabled('pause', s.paused);
  setDisabled('save', !s.paused || draining);
  setDisabled('connect', !s.paused || draining);
  $('connect').textContent = s.credentials ? 'Conectar com Google' : 'Configurar acesso';
  $('client').disabled = !s.paused || draining || busyActions.has('client');
  $('destination').textContent = s.destination;
  $('bandwidth-status').textContent = !Object.hasOwn(s, 'bandwidth_mib')
    ? 'Reinicie o serviço no servidor para ativar este recurso.'
    : s.bandwidth_mib ? 'Limite aplicado: ' + s.bandwidth_mib + ' MiB/s no total.' : 'Sem limite. Use 0 para manter a velocidade livre.';
  if (!initialized) {
    $('root').value = s.root;
    $('interval').value = String(s.interval);
    $('workers').value = String(s.workers || 4);
    $('bandwidth').value = String(s.bandwidth_mib || 0);
    initialized = true;
  }
  renderWorkers(s);
  renderLibrary(s);
  renderErrors(s);
  renderEvents(s.events || []);
}

function renderLibrary(s) {
  const ready = !!s.progress_ready;
  const globalPercent = ready && s.total_bytes ? Math.min(100, s.copied_bytes / s.total_bytes * 100) : 0;
  $('progress').value = globalPercent;
  $('global-total').textContent = ready
    ? bytes(s.copied_bytes) + ' / ' + bytes(s.total_bytes) + ' · ' + globalPercent.toFixed(1) + '%'
    : 'Consultando total…';
  $('total-size').textContent = ready ? bytes(s.total_bytes) : '—';
  $('copied-size').textContent = ready ? bytes(s.copied_bytes) : '—';
  $('remaining-size').textContent = ready ? bytes(s.remaining_bytes) : '—';
  $('eta').textContent = s.paused ? 'Pausado'
    : s.phase === 'erro' ? 'Aguardando'
    : s.phase === 'aguardando' && s.last_sync ? 'Concluído'
    : ready && s.remaining_bytes === 0 ? 'Finalizando' : duration(s.eta_seconds);
  $('size-note').textContent = !Object.hasOwn(s, 'error_count')
    ? 'Reinicie o serviço no servidor para carregar os novos indicadores.'
    : !ready ? 'O progresso aparece após consultar o catálogo.'
      : 'Os bytes recebidos incluem parciais. A validação continua antes de concluir.' +
        (s.unknown_size_files ? ' ' + s.unknown_size_files + ' documentos/links sem tamanho conhecido ficam fora deste total.' : '');
  const downloads = s.active || [];
  const known = downloads.filter(a => a.size > 0);
  const total = known.reduce((sum, a) => sum + a.size, 0);
  const received = known.reduce((sum, a) => sum + Math.min(a.bytes, a.size), 0);
  const percent = total ? Math.min(100, received / total * 100) : 0;
  $('active-progress').value = percent;
  $('active-summary').textContent = downloads.length ? downloads.length + ' em andamento' : 'Sem transferências';
  $('transfer').textContent = downloads.length
    ? bytes(received) + ' de ' + bytes(total) + ' · ' + percent.toFixed(1) + '% · ' + bytes(s.speed) + '/s' +
      (known.length < downloads.length ? ' · Há arquivos sem tamanho conhecido' : '')
    : 'Total dos downloads em andamento';
  $('downloads-empty').hidden = downloads.length > 0;
  renderTransfers(downloads);
}

function makeIcon(reference) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', reference);
  svg.append(use);
  return svg;
}

function newTransfer() {
  const row = document.createElement('li');
  row.className = 'transfer-row';
  const symbol = document.createElement('span');
  symbol.className = 'file-symbol';
  symbol.append(makeIcon('#i-file'));
  const content = document.createElement('div');
  content.className = 'transfer-content';
  const name = document.createElement('strong'); name.className = 'transfer-name';
  const path = document.createElement('span'); path.className = 'transfer-path';
  const bar = document.createElement('progress'); bar.max = 100;
  const meta = document.createElement('div'); meta.className = 'transfer-meta';
  content.append(name, path, bar, meta);
  const side = document.createElement('div'); side.className = 'transfer-side';
  const percent = document.createElement('strong');
  const speed = document.createElement('small');
  side.append(percent, speed);
  row.append(symbol, content, side);
  return {row, name, path, bar, meta, percent, speed};
}

function renderTransfers(downloads) {
  const keys = new Set(downloads.map(a => a.name));
  for (const [key, nodes] of transferNodes) {
    if (!keys.has(key)) { nodes.row.remove(); transferNodes.delete(key); }
  }
  for (const file of downloads) {
    let nodes = transferNodes.get(file.name);
    if (!nodes) { nodes = newTransfer(); transferNodes.set(file.name, nodes); $('active-transfers').append(nodes.row); }
    const parts = file.name.split('/');
    nodes.name.textContent = parts.pop(); nodes.name.title = file.name;
    nodes.path.textContent = parts.length ? parts.join(' / ') : 'Meu Drive'; nodes.path.title = file.name;
    const percent = file.size ? Math.min(100, file.bytes / file.size * 100) : null;
    nodes.percent.textContent = percent === null ? '—' : percent.toFixed(1) + '%';
    if (percent === null) nodes.bar.removeAttribute('value'); else nodes.bar.value = percent;
    nodes.bar.setAttribute('aria-label', 'Progresso de ' + file.name);
    nodes.meta.textContent = bytes(file.bytes) + ' / ' + (file.size ? bytes(file.size) : 'tamanho desconhecido');
    nodes.speed.textContent = bytes(file.speed) + '/s';
  }
}

function renderErrors(s) {
  const count = s.error_count || 0;
  $('errors-title').textContent = count ? count + (count === 1 ? ' arquivo precisa de atenção' : ' arquivos precisam de atenção') : 'Nenhuma pendência registrada';
  $('nav-error-count').textContent = String(count);
  $('nav-error-count').hidden = !count;
  $('issues-empty').hidden = count > 0;
  setDisabled('retry-errors', !count || !s.connected || ['baixando', 'verificando'].includes(s.phase) || (s.active || []).length > 0);
  $('errors-note').textContent = count
    ? 'A nova tentativa retoma pendentes e reconhece arquivos já concluídos. ' + (count > 100 ? 'Mostrando os 100 primeiros de ' + count + '.' : 'O histórico permanece salvo após reiniciar.')
    : 'Se algum arquivo falhar, o motivo e o número de tentativas aparecerão aqui.';
  const key = JSON.stringify(s.errors || []);
  if (key === errorsKey) return;
  errorsKey = key;
  $('file-errors').replaceChildren(...(s.errors || []).map(error => {
    const li = document.createElement('li');
    const name = document.createElement('strong'); name.textContent = error.name;
    const message = document.createElement('p'); message.textContent = error.message;
    const info = document.createElement('small'); info.textContent = error.attempts + ' tentativa(s) · Última falha: ' + error.time;
    li.append(name, message, info);
    return li;
  }));
}

function renderEvents(events) {
  const key = JSON.stringify(events);
  if (key === eventsKey) return;
  eventsKey = key;
  $('events').replaceChildren(...events.map(event => {
    const li = document.createElement('li');
    const time = document.createElement('time'); time.textContent = event.time;
    const text = document.createElement('span'); text.textContent = event.text;
    li.append(time, text);
    return li;
  }));
  if (!events.length) {
    const li = document.createElement('li');
    li.textContent = 'Ainda não há atividade nesta sessão.';
    $('events').append(li);
  }
}

function renderWorkers(s) {
  if (!s.workers_live) { $('workers-status').textContent = 'Reinicie o serviço no servidor para alterar ao vivo.'; return; }
  if (savingWorkers) return;
  const count = (s.active || []).length;
  $('workers-status').textContent = 'Aplicado: ' + s.workers + ' · Ativos: ' + count +
    (count > s.workers ? ' · Aguardando os já iniciados terminarem.' : ' · Alteração automática.');
  if (document.activeElement !== $('workers')) $('workers').value = String(s.workers);
}

async function refresh() {
  if (refreshBusy || document.hidden) return;
  refreshBusy = true;
  try {
    const status = await requestJSON('/api/status');
    latest = status;
    csrf = status.csrf;
    renderState(status);
  } catch (error) {
    $('badge').textContent = 'Serviço desconectado';
    $('badge').dataset.offline = 'true';
    $('error').textContent = 'Não foi possível atualizar o painel. Verifique o serviço e o túnel SSH; os números exibidos podem estar desatualizados.';
    $('error').hidden = false;
  } finally { refreshBusy = false; }
}

function action(id, callback) {
  $(id).addEventListener('click', async () => {
    if (busyActions.has(id)) return;
    busyActions.add(id); $(id).disabled = true;
    try { await callback(); }
    catch (error) { toast(error.message); }
    finally { busyActions.delete(id); $(id).disabled = false; await refresh(); }
  });
}

action('retry-errors', async () => {
  if (!latest || !Object.hasOwn(latest, 'error_count')) throw Error('Reinicie o serviço no servidor para carregar esta atualização.');
  await post('retry-errors'); toast('Nova tentativa solicitada. Os arquivos já concluídos serão reconhecidos.');
});
action('apply-bandwidth', async () => {
  if (!latest || !Object.hasOwn(latest, 'bandwidth_mib')) throw Error('Reinicie drive-espelho no servidor para aplicar o limite.');
  const input = $('bandwidth');
  if (!input.value.trim() || !input.checkValidity()) throw Error('Informe um limite válido em MiB/s; 0 = sem limite.');
  await post('bandwidth', {bandwidth_mib: Number(input.value)});
  toast('Limite aplicado aos downloads em andamento.');
});
action('start', () => post('start'));
action('pause', () => post('pause'));
action('save', async () => {
  await post('settings', {root: $('root').value, interval: Number($('interval').value), workers: Number($('workers').value)});
  toast('Configuração salva.');
});
action('connect', async () => {
  if (!latest) throw Error('Aguarde o painel conectar ao serviço.');
  if (!latest.credentials) {
    window.location.hash = 'settings'; navigate('settings');
    $('google-setup').open = true;
    $('google-setup').scrollIntoView({behavior: 'smooth', block: 'center'});
    toast('Crie seu aplicativo no Google Cloud e importe o JSON. As instruções estão abertas abaixo.');
    return;
  }
  if (!latest.paused) throw Error('Pause a sincronização antes de conectar a conta.');
  const response = await post('connect'); window.location.assign(response.url);
});
$('client').addEventListener('change', async event => {
  busyActions.add('client');
  try {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 65536) throw Error('JSON grande demais. Selecione as credenciais OAuth.');
    await post('client', JSON.parse(await file.text()));
    toast('Credenciais importadas. Agora conecte sua conta.');
  } catch (error) { toast(error.message); }
  finally { busyActions.delete('client'); $('client').value = ''; await refresh(); }
});
$('workers').addEventListener('change', async () => {
  if (savingWorkers) return;
  savingWorkers = true; $('workers').disabled = true;
  $('workers-status').textContent = 'Aplicando quantidade…';
  try {
    if (!latest || !latest.workers_live) throw Error('Reinicie drive-espelho no servidor para alterar a quantidade ao vivo.');
    const workers = Number($('workers').value);
    await post('workers', {workers}); latest.workers = workers;
    toast('Quantidade aplicada: ' + workers + '. Os já iniciados terminam normalmente.');
  } catch (error) { if (latest) $('workers').value = String(latest.workers); toast(error.message); }
  finally { savingWorkers = false; $('workers').disabled = false; await refresh(); }
});
window.addEventListener('hashchange', () => navigate());
document.querySelector('.skip-link').addEventListener('click', event => {
  event.preventDefault();
  $('main').focus();
  $('main').scrollIntoView({block: 'start'});
});
document.querySelectorAll('a[href^="#"]').forEach(link => {
  const page = link.getAttribute('href').slice(1);
  if (!Object.hasOwn(pages, page)) return;
  link.addEventListener('click', event => {
    event.preventDefault();
    if (window.location.hash === '#' + page) navigate(page); else window.location.hash = page;
  });
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
navigate();
refresh();
setInterval(refresh, 1500);
