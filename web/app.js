const $ = id => document.getElementById(id);
const messages = window.keeperMessages;
let language = navigator.language.startsWith('ja') ? 'ja' : 'en';
try { language = localStorage.getItem('keeper-language') || language; } catch {}
if (!messages[language]) language='en';
let selected=null, cached=null, refreshing=false, notice=null, scheduleDirty=false;
const expandedProjects=new Set();
function t(key) {return messages[language][key] || key;}
function node(tag,text,cls){const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;}
function date(value){return value?new Date(value).toLocaleString(language==='ja'?'ja-JP':'en-US'):'—';}
function translate(){document.documentElement.lang=language;$('language').value=language;document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=t(e.dataset.i18n));if(notice)$('message').textContent=t(notice);if(cached)render(cached);}
function errorMessage(error){return t({'ログインしてください':'auth','キーが違います':'badkey','しばらく待って再試行してください':'limited','処理中です':'busy','Recovery required':'recovery','Unknown project':'unknown','Schedule must be HH:MM':'invalid_schedule','Invalid timezone':'invalid_timezone'}[error] || error);}
async function api(path,body){
  const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Keeper-Request':'1'},body:JSON.stringify(body)});
  const data=await r.json();
  if(r.status===401){$('login').hidden=false;$('dashboard').hidden=true;$('logout').hidden=true;}
  if(!r.ok){const e=new Error(errorMessage(data.error||String(r.status)));e.status=r.status;throw e;}
  return data;
}
async function action(id,operation='run'){
  try{await api('/api/'+operation,{id});notice='begun';$('message').textContent=t(notice);await refresh();}
  catch(e){notice=null;$('message').textContent=e.message;}
}
function render(data){
  $('schedule').textContent=t('schedule').replace('{time}',data.schedule).replace('{tz}',data.timezone);
  if(!scheduleDirty){$('schedule-time').value=data.schedule;$('schedule-timezone').value=data.timezone;}
  $('busy').textContent=t(data.busy?'busy':'waiting');$('run-all').disabled=data.busy;
  const rows=[];
  for(const p of data.projects){
    const row=node('tr','');const title=node('td','');title.append(node('strong',p.name),node('small',p.directory));if(p.manual_stopped)title.append(node('small',t('manual')));row.append(title);
    const version=node('td','');const images={...p.current_images};
    for(const c of p.inventory?.containers||[])if(c.service)images[c.service]=c.image_id;
    for(const [service,id] of Object.entries(images)){const line=node('div',`${service}: ${p.image_refs?.[service]||p.inventory?.containers?.find(c=>c.service===service)?.image||''}`);line.append(node('code',id.slice(0,24)));version.append(line);}
    if(!version.childNodes.length)version.textContent=t('first');
    const checked=node('td',date(p.last_checked));checked.dataset.label=t('checked');const updated=node('td',date(p.last_updated));updated.dataset.label=t('updated');
    const status=node('td',t(({updated:'update_done',start:'starting',stop:'stopping'})[p.status]||p.status||'unknown'),p.status?.includes('failed')||p.status==='error'?'error':'status');status.dataset.label=t('status');row.append(version,checked,updated,status);
    const actions=node('td','');
    for(const [key,operation] of [['start','start'],['stop','stop'],['check','run']]){const b=node('button',t(key));b.disabled=data.busy||p.recovery_pending||(operation==='run'&&p.manual_stopped);b.onclick=()=>action(p.id,operation);actions.append(b);}
    const details=node('button',t('details'));details.onclick=()=>{selected=selected===p.id?null:p.id;render(cached);if(selected)refresh();};actions.append(details);
    if(p.recovery_pending){const b=node('button',t('recover'));b.disabled=data.busy;b.onclick=()=>action(p.id,'recover');actions.append(b);}
    row.append(actions);rows.push(row);
    const cr=node('tr','','container-row'),cell=node('td','');cell.colSpan=6;
    const inv=p.inventory;const disclosure=node('details','');disclosure.open=expandedProjects.has(p.id);disclosure.addEventListener('toggle',()=>{if(!disclosure.isConnected)return;if(disclosure.open)expandedProjects.add(p.id);else expandedProjects.delete(p.id);});disclosure.append(node('summary',`${t('containers')} (${inv?.containers?.length||0})`));
    if(inv?.error)disclosure.append(node('div',inv.error,'error'));
    else if(!inv?.containers?.length)disclosure.append(node('small',t(inv?.observed_at?'empty':'observing')));
    const list=node('div','','container-list');
    for(const c of inv?.containers||[]){const item=node('div','','container-item');item.append(node('strong',c.name||c.id.slice(0,12)),node('span',`${t(c.status)}${c.running&&c.health?' · '+t(c.health):''}`,c.running&&c.health==='unhealthy'?'error':'status'),node('small',`${t('service')}: ${c.service} · ${c.id.slice(0,12)}`),node('code',c.image));const ports=Object.entries(c.ports).flatMap(([port,bindings])=>(bindings||[]).map(b=>`${b.HostIp||'*'}:${b.HostPort} → ${port}`));if(ports.length)item.append(node('small',`${t('ports')}: ${ports.join(', ')}`));list.append(item);}
    disclosure.append(list);cell.append(disclosure);cr.append(cell);rows.push(cr);
    if(selected===p.id){$('detail-title').textContent=p.name;$('error').textContent=p.last_error||p.control_error?JSON.stringify({update_error:p.last_error,rollback_error:p.rollback_error,control_error:p.control_error},null,2):t('noerror');}
  }
  $('projects').replaceChildren(...rows);$('details').hidden=!selected;
}
async function refresh(){
  if(refreshing)return;refreshing=true;
  try{cached=await api('/api/projects');$('login').hidden=true;$('dashboard').hidden=false;$('logout').hidden=false;render(cached);if(selected){const logs=await api('/api/logs/'+encodeURIComponent(selected));$('log').textContent=logs.log||t('nolog');}}
  catch(e){if(e.status!==401){notice=null;$('message').textContent=e.message;}}
  finally{refreshing=false;}
}
$('schedule-settings').oninput=()=>{scheduleDirty=true;};
$('schedule-settings').onsubmit=async e=>{e.preventDefault();try{await api('/api/settings',{schedule:$('schedule-time').value,timezone:$('schedule-timezone').value});scheduleDirty=false;notice='schedule_saved';$('message').textContent=t(notice);await refresh();}catch(e){notice=null;$('message').textContent=e.message;}};
$('language').onchange=()=>{language=$('language').value;try{localStorage.setItem('keeper-language',language);}catch{}translate();};
$('login').onsubmit=async e=>{e.preventDefault();try{await api('/api/login',{key:$('key').value});$('key').value='';notice=null;$('message').textContent='';await refresh();}catch(e){$('message').textContent=e.message;}};
$('run-all').onclick=()=>action(null);
$('logout').onclick=async()=>{await api('/api/logout',{});selected=null;cached=null;await refresh();};
translate();refresh();setInterval(refresh,4000);
