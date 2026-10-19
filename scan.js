'use strict';
const $=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const NO='尚無資料';
const show=(v,unit='')=>v===null||v===undefined||v===''?NO:`${v}${unit}`;
const fmt=v=>v?new Date(v).toLocaleString('zh-TW',{timeZone:'Asia/Taipei',hour12:false}):NO;
const day=v=>v?new Date(v).toLocaleDateString('zh-TW',{timeZone:'Asia/Taipei'}):NO;
const KIND={mill:'加工中心',lathe:'車床'};
const REMINDER={overdue:'已逾期',due:'今天到期',soon:'7 天內到期',scheduled:'已排程',in_progress:'處理中'};
const SOURCE={part:'零件',ticket:'工單',manual:'手冊',plan:'保養',stock:'備品'};
const MAX_EDGE=1600;
let machines=[];
// 使用者可能在 AI 回應前就換了機台；只畫目前這台的回應，避免舊結果蓋掉新畫面
let current='';
let scanGeneration=0;

function notice(message,error=false){$('#notice').textContent=message;$('#notice').className=error?'error':''}

async function api(path,options={}){
  await window.authReady;
  const r=await fetch('/api'+path,{...options,headers:{'X-CSRF-Token':window.authCsrf,...(options.headers||{})}});
  if(r.status===401){location.reload();throw Error('請重新登入')}
  let data;
  try{data=await r.json()}catch{throw Error('服務暫時無法完成請求，請稍後重試')}
  if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:'請求失敗，請稍後重試');
  return data;
}

async function bitmapOf(blob){
  try{return await createImageBitmap(blob,{imageOrientation:'from-image'})}catch{return null}
}

async function prepare(blob){
  const bitmap=await bitmapOf(blob);
  const canvas=$('#preview');
  if(!bitmap){canvas.width=320;canvas.height=40;return blob}
  // CSP 的 img-src 不允許 blob: 網址，預覽改畫在 canvas；順便把手機大圖縮小，上傳更快也不會超過 6 MB
  const scale=Math.min(1,MAX_EDGE/Math.max(bitmap.width,bitmap.height));
  canvas.width=Math.round(bitmap.width*scale);canvas.height=Math.round(bitmap.height*scale);
  canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
  if(scale===1&&blob.size<1.5e6)return blob;
  return await new Promise(resolve=>canvas.toBlob(b=>resolve(b||blob),'image/jpeg',0.9));
}

async function scanBlob(blob){
  const generation=++scanGeneration;
  current='';
  $('#overview').hidden=true;
  $('#result').hidden=false;
  $('#result-body').innerHTML='<p class="loading">正在辨識銘牌文字</p>';
  $('#result').scrollIntoView({behavior:'smooth',block:'start'});
  try{
    const upload=await prepare(blob);
    if(generation!==scanGeneration)return;
    const result=await api('/scan/nameplate',{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:upload});
    if(generation===scanGeneration)renderResult(result);
  }catch(e){if(generation===scanGeneration){$('#result-body').innerHTML=`<p class="error">${esc(e.message)}</p>`;notice(e.message,true)}}
}

function renderResult(r){
  const top=r.candidates[0];
  const raw=r.text.length?`<details><summary>OCR 讀到的全部文字</summary><p>${r.text.map(esc).join('<br>')}</p></details>`:'';
  const meta=`<p><small class="muted">${esc(r.engine)} · ${r.elapsed_ms} ms · 在本機執行</small></p>`;
  if(r.decision==='auto'){
    $('#result-body').innerHTML=`<div class="machine-id">${esc(top.machine_id)}</div><p>信心 <span class="confidence">${Math.round(top.confidence*100)}%</span>，已自動開啟這台機台。</p><button type="button" class="btn" id="fix">不是這台？修正</button>${meta}${raw}`;
    $('#fix').onclick=()=>{$('#manual-input').focus();$('#manual-input').scrollIntoView({block:'center'})};
    loadMachine(top.machine_id);
  }else if(r.decision==='confirm'){
    $('#result-body').innerHTML=`<p>辨識信心不夠高，請確認是哪一台：</p><div class="candidates">${r.candidates.map(c=>`<button type="button" class="btn" data-machine="${esc(c.machine_id)}">${esc(c.machine_id)}<span class="confidence low"> ${Math.round(c.confidence*100)}%</span></button>`).join('')}</div><p class="muted">都不是？請在上方手動輸入。</p>${meta}${raw}`;
    for(const b of document.querySelectorAll('[data-machine]'))b.onclick=()=>loadMachine(b.dataset.machine);
  }else{
    $('#result-body').innerHTML=`<p>照片裡沒有找到已建檔的機台編號。請重拍清楚一點，或直接手動輸入。</p>${meta}${raw}`;
    $('#manual-input').focus();
  }
}

async function loadMachine(mid){
  current=mid;
  notice('');
  $('#overview').hidden=false;
  $('#overview-head').innerHTML=`<p class="loading">正在整理 ${esc(mid)} 的資料</p>`;
  for(const id of ['#ai-summary','#sec-live','#sec-people','#sec-history','#sec-maintenance','#sec-reliability','#sec-suggestions'])$(id).innerHTML='';
  let o;
  try{o=await api('/machines/'+encodeURIComponent(mid)+'/overview')}
  catch(e){$('#overview-head').innerHTML=`<p class="error">${esc(e.message)}</p>`;return}
  if(current!==mid)return;
  renderOverview(o);
  $('#overview').scrollIntoView({behavior:'smooth',block:'start'});
  $('#ai-summary').innerHTML='<p class="loading">AI 分析中，本機模型約需 1 分鐘</p>';
  $('#sec-suggestions').innerHTML='<p class="loading">等待 AI 分析</p>';
  try{
    const s=await api('/machines/'+encodeURIComponent(mid)+'/ai-summary',{method:'POST'});
    if(current===mid)renderSummary(s);
  }catch(e){if(current===mid)$('#ai-summary').innerHTML=`<p class="error">${esc(e.message)}</p>`}
}

function metrics(items){
  return `<div class="metrics">${items.map(([k,v,extra])=>`<div><small>${k}</small><strong>${esc(v)}</strong>${extra?`<small>${extra}</small>`:''}</div>`).join('')}</div>`;
}

function renderOverview(o){
  const m=o.machine,l=o.live;
  $('#overview-head').innerHTML=`<div><small class="muted">${esc(KIND[m.kind]||m.kind||'設備')}${m.machine_model?' · '+esc(m.machine_model):''}</small><h2>${esc(m.id)} ${esc(m.name||'')}</h2></div><span class="status-pill${(l.risk??0)>=50?' risk':''}">${esc(l.status||NO)} · 風險 ${esc(show(l.risk))}</span>`;
  const parts=o.parts.length?o.parts.map(p=>`<div class="part"><div class="part-head"><span>${esc(p.name)}</span><span>${p.health===null?NO:esc(p.health)+'%'}</span></div>${p.health===null?'':`<meter min="0" max="100" low="60" high="80" optimum="100" value="${Number(p.health)}"></meter>`}<p>${esc(p.note||'')}${p.replaced_on?` · 上次更換 ${esc(p.replaced_on)}`:''}</p></div>`).join(''):`<p class="muted">${NO}</p>`;
  $('#sec-live').innerHTML=metrics([['溫度',show(l.temp,' °C')],['振動',show(l.vib,' mm/s')],['稼動率',show(l.util,'%')],['累計工時',show(m.hours,' 小時')],['安裝日期',show(m.installed_on)]])+'<h3>零件健康度</h3>'+parts;
  const r=o.people.responsible,i=o.people.last_inspection;
  const duty=r?({true:'在班',false:'未在班'}[String(r.on_duty)]||'出勤尚無資料'):'';
  const open=o.in_progress.length?o.in_progress.map(t=>`<div class="entry"><p><strong>${esc(t.id)}</strong> <span class="badge">${esc(t.status)}</span></p><p>${esc(t.issue)}</p><small>${esc(t.engineer)} · 已記錄 ${t.logged_minutes} 分鐘 · 建立於 ${fmt(t.created_at)}</small>${t.latest_log?`<p class="muted">最新紀錄（${fmt(t.latest_log.at)}）：${esc(t.latest_log.note)}</p>`:''}</div>`).join(''):'<p class="muted">目前沒有未結工單。</p>';
  $('#sec-people').innerHTML=metrics([['負責人',r?r.name:NO,r?`${duty} · 手上 ${r.open_tickets} 張工單`:''],['上次檢核',i?i.date:NO,i?esc(i.inspector||''):'']])+(i&&i.note?`<p class="muted">檢核紀錄：${esc(i.note)}</p>`:'')+'<h3>進行中的工單</h3>'+open;
  $('#sec-history').innerHTML=o.history.length?o.history.map(h=>`<div class="entry"><p><strong>${day(h.closed_at||h.created_at)}</strong> ${esc(h.issue)}</p><small>${esc(h.engineer)} · ${esc(h.id)}${h.photo_count?` · ${h.photo_count} 張照片`:''}${h.case_id?' · 已發布案例':''}</small><p class="muted">${esc(h.completion_note||'')}</p></div>`).join(''):'<p class="muted">尚無已結案的檢修紀錄。</p>';
  const plans=o.maintenance.plans.length?o.maintenance.plans.map(p=>`<div class="entry"><p>${esc(p.title)} <span class="badge">${esc(REMINDER[p.reminder]||p.reminder)}</span></p><small>下次到期 ${esc(p.next_due)}</small></div>`).join(''):'<p class="muted">這台機台還沒有保養計畫。</p>';
  const stock=o.stock.length?o.stock.map(s=>`<div class="entry"><p>${esc(s.name)} ${s.low?'<span class="badge warning">低於安全量</span>':''}</p><small>對應零件 ${esc(s.part)} · 庫存 ${s.quantity} ／ 安全量 ${s.minimum}</small></div>`).join(''):'<p class="muted">沒有找到名稱對應的備品。</p>';
  $('#sec-maintenance').innerHTML=`<p>下次檢核：<strong>${esc(show(o.maintenance.next_inspection))}</strong></p><h3>保養計畫</h3>${plans}<h3>相關備品</h3>${stock}`;
  const rel=o.reliability;
  $('#sec-reliability').innerHTML=metrics([['故障次數',String(rel.failures)],['MTBF 平均故障間隔',rel.mtbf_days===null?'樣本不足':rel.mtbf_days+' 天'],['MTTR 平均修復時間',rel.mttr_hours===null?'樣本不足':rel.mttr_hours+' 小時']])+'<p class="muted">定期保養產生的工單不算故障。MTBF 至少需要 3 張工單，MTTR 至少需要 2 張已結案工單。</p>';
}

function renderSummary(s){
  const label=s.mode==='llm'?`由本機模型 ${esc(s.meta?.model||'')} 產生，每條建議都附上依據`:'本機模型未啟用或回覆不合格，以下由規則產生';
  $('#ai-summary').innerHTML=`<ol class="ai-lines">${s.summary.map(line=>`<li>${esc(line)}</li>`).join('')}</ol><p class="mode-label">${label}</p>`;
  $('#sec-suggestions').innerHTML=s.suggestions.map(x=>`<div class="entry"><p>${esc(x.text)}</p><small>依據<span class="source-tag">${esc(SOURCE[x.source.type]||x.source.type)}：${esc(x.source.label)}</span></small></div>`).join('');
}

async function loadSamples(){
  try{
    const samples=await api('/scan/samples');
    $('#samples').innerHTML=samples.map(s=>`<button type="button" data-sample="${esc(s.url)}"><img src="${esc(s.url)}" alt="${esc(s.machine_id)} 範例銘牌" loading="lazy"><span>${esc(s.machine_id)}</span></button>`).join('');
    $('#sample-box').hidden=!samples.length;
    // 範例也走真正的 OCR，而不是直接帶入編號
    for(const b of document.querySelectorAll('[data-sample]'))b.onclick=async()=>scanBlob(await fetch(b.dataset.sample).then(r=>r.blob()));
  }catch{$('#sample-box').hidden=true}
}

async function init(){
  await window.authReady;
  const config=await fetch('/api/auth/config').then(r=>r.json()).catch(()=>({}));
  if(config.app_mode==='demo'){$('#demo-badge').hidden=false;loadSamples()}
  try{
    machines=await api('/machines');
    $('#machine-list').innerHTML=machines.map(m=>`<option value="${esc(m.id)}">${esc(m.name||'')}</option>`).join('');
  }catch(e){notice(e.message,true)}
}

$('#photo').onchange=e=>{const file=e.target.files[0];if(file)scanBlob(file);e.target.value=''};
const drop=$('#drop');
drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragging')};
drop.ondragleave=()=>drop.classList.remove('dragging');
drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragging');const file=e.dataTransfer.files[0];if(file)scanBlob(file)};
$('#manual-form').onsubmit=e=>{
  e.preventDefault();
  const typed=$('#manual-input').value.trim();
  // 手動輸入常常大小寫不一致，對照已建檔編號找出正確寫法
  const match=machines.find(m=>m.id.toLowerCase()===typed.toLowerCase());
  if(typed){++scanGeneration;$('#result').hidden=true;loadMachine(match?match.id:typed)}
};
$('#scan-again').onclick=()=>{++scanGeneration;current='';$('#overview').hidden=true;$('#result').hidden=true;$('#capture').scrollIntoView({behavior:'smooth'})};
init();
