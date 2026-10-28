"""Read-only Linux disk/network telemetry; bottlenecks are evidence, not benchmarks."""
from collections import deque
import json
from pathlib import Path
import threading
import time

STAGES = ('api', 'receive', 'write', 'verify', 'throttle')

def read(path, default=''):
    try: return Path(path).read_text().strip()
    except OSError: return default

def number(path):
    try: return float(read(path))
    except ValueError: return None

def disk_delta(previous, current, elapsed):
    if elapsed <= 0 or len(current)<11 or len(previous)<11:
        return None
    if any(current[i]<previous[i] for i in (0,2,3,4,6,7,9,10)):
        return None
    d=[b-a for a,b in zip(previous,current)]
    ios=d[0]+d[4]
    return {'read_bps':d[2]*512/elapsed,'write_bps':d[6]*512/elapsed,
            'busy_pct':min(100,max(0,d[9]/elapsed/10)),
            'await_ms':(d[3]+d[7])/ios if ios else 0,
            'queue':max(0,d[10]/elapsed/1000),'inflight':current[8]}

class Diagnostics:
    def __init__(self, provider, sysroot='/sys', procroot='/proc'):
        self.provider=provider
        self.sys=Path(sysroot);self.proc=Path(procroot)
        self.lock=threading.RLock()
        self.stages={key:0.0 for key in STAGES}
        self.api_errors=0
        self.last=None
        self.history=deque(maxlen=120)
        self.cached=None

    def observe(self, stage, duration):
        with self.lock:
            if stage=='api_error':self.api_errors+=1
            elif stage in self.stages:self.stages[stage]+=max(0,duration)

    def raw(self):
        arrays=[];physical=set()
        for path in sorted((self.sys/'block').glob('md*')):
            if read(path/'md/level')!='raid10':continue
            members=[]
            for member in sorted((path/'slaves').glob('*')):
                resolved=member.resolve()
                disk=resolved.parent.name if (resolved/'partition').exists() else member.name
                physical.add(disk)
                members.append({'member':member.name,'disk':disk})
            arrays.append({'name':path.name,'level':read(path/'md/level'),
                'degraded':number(path/'md/degraded'),'state':read(path/'md/array_state'),
                'sync_action':read(path/'md/sync_action'),'members':members})
        disks={}
        for name in sorted(physical):
            p=self.sys/'block'/name
            try: values=list(map(int,read(p/'stat').split()))
            except ValueError:continue
            if len(values)>=11:disks[name]={'stat':values,'model':read(p/'device/model')}
        networks={}
        for p in sorted((self.sys/'class/net').glob('*')):
            # Physical interfaces only, avoiding double-counting Tailscale/VPN/bridges.
            if not (p/'device').exists() or read(p/'operstate')!='up':continue
            rx=number(p/'statistics/rx_bytes');tx=number(p/'statistics/tx_bytes')
            if rx is None or tx is None:continue
            networks[p.name]={'rx':rx,'tx':tx,'speed_mbps':number(p/'speed')}
        pressure={}
        for line in read(self.proc/'pressure/io').splitlines():
            fields=line.split()
            if fields:
                pairs=dict(x.split('=',1) for x in fields[1:] if '=' in x)
                pressure[fields[0]]=float(pairs.get('avg10',0))
        memory={}
        for line in read(self.proc/'meminfo').splitlines():
            fields=line.split()
            if len(fields)>1 and fields[0] in ('Dirty:','Writeback:'):
                memory[fields[0][:-1].lower()]=int(fields[1])*1024
        return {'time':time.monotonic(),'arrays':arrays,'disks':disks,'networks':networks,
                'pressure':pressure,'memory':memory,'stages':dict(self.stages),'api_errors':self.api_errors,
                'app':self.provider()}

    def snapshot(self):
        with self.lock:
            now=time.monotonic()
            if self.cached and self.last and now-self.last['time']<1:
                return self.cached
            raw=self.raw();old=self.last;self.last=raw
            dt=raw['time']-old['time'] if old else 0
            disks=[];networks=[]
            for name,disk in raw['disks'].items():
                before=old['disks'].get(name) if old else None
                delta=disk_delta(before['stat'],disk['stat'],dt) if before else None
                disks.append(dict(name=name,model=disk['model'],metrics=delta))
            for name,net in raw['networks'].items():
                before=old['networks'].get(name) if old else None
                rx=tx=None
                if before and dt>0 and net['rx']>=before['rx'] and net['tx']>=before['tx']:
                    rx=(net['rx']-before['rx'])/dt;tx=(net['tx']-before['tx'])/dt
                speed=net['speed_mbps']
                networks.append({'name':name,'rx_bps':rx,'tx_bps':tx,'link_mbps':speed if speed and speed>0 else None,
                    'link_rx_pct':min(100,rx*8/(speed*1e6)*100) if rx is not None and speed and speed>0 else None})
            app=raw['app'];before_app=old['app'] if old else {}
            received=max(0,app.get('network_bytes',0)-before_app.get('network_bytes',0))
            google=received/dt if dt>0 else None
            stages={key:max(0,raw['stages'][key]-old['stages'][key]) if old else 0 for key in STAGES}
            total=sum(stages.values())
            stage_pct={key:value/total*100 if total else None for key,value in stages.items()}
            internet=app.get('internet_mbps',0)
            rx=sum(n['rx_bps'] or 0 for n in networks) if networks else None
            plan_pct=rx*8/(internet*1e6)*100 if rx is not None and internet>0 else None
            point={'time':time.time(),'disks':disks,'networks':networks,'google_bps':google,
                'internet_pct':plan_pct,'rx_bps':rx,'stages_pct':stage_pct,'io_pressure_pct':raw['pressure'].get('some'),
                'api_errors':raw['api_errors']-old['api_errors'] if old else 0}
            if old:self.history.append(point)
            warnings=[]
            for array in raw['arrays']:
                if array['degraded'] and array['degraded']>0:
                    warnings.append('RAID degradado: '+array['name'])
                if array['sync_action'] not in ('idle','frozen',''):
                    warnings.append('RAID executando '+array['sync_action']+': '+array['name'])
            # Require multiple samples before reporting a sustained bottleneck candidate.
            recent=list(self.history)[-3:]
            if len(recent)==3:
                for disk in disks:
                    measures=[next((d['metrics'] for d in p['disks'] if d['name']==disk['name']),None) for p in recent]
                    if all(m and m['busy_pct']>=90 and (m['await_ms']>=20 or m['queue']>=2) for m in measures):
                        warnings.append('Possível gargalo no HD '+disk['name']+': ocupação alta com fila/latência em 3 amostras.')
                if all(p['internet_pct'] is not None and p['internet_pct']>=90 for p in recent):
                    warnings.append('Tráfego próximo do plano informado; possível limite da internet (inclui tráfego local).')
                if app.get('bandwidth_mib',0) and all((p['stages_pct'].get('throttle') or 0)>=30 for p in recent):
                    warnings.append('O limitador do HitechDrive está segurando os downloads.')
            if point['api_errors']:
                warnings.append('A API do Google retornou erros nesta amostra; confira também a lista de arquivos com erro.')
            if not warnings:
                warnings.append('Sem gargalo confirmado nas amostras. Espera na leitura pode ser Google ou rota de rede; não distingue os dois sozinha.')
            self.cached={'arrays':raw['arrays'],'current':point,'history':list(self.history),
                'warnings':warnings,'internet_mbps':internet,'memory':raw['memory'],
                'warming_up':not bool(old),'available':bool(raw['arrays'])}
            return self.cached
