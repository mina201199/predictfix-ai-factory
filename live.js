// All live features call the same-origin FastAPI; no secrets are stored in JS.
let serviceReady=false, engineerRequest=0, completingTicket=null;
async function api(path,options={}){
  await window.authReady;
  const response=await fetch('/api'+path,{...options,headers:{'Content-Type':'application/json','X-CSRF-Token':window.authCsrf,...(options.headers||{})}});
  let body;try{body=await response.json()}catch{throw new Error('後端未回傳 JSON；請使用 FastAPI 啟動系統。')}
  if(response.status===401){location.reload();throw new Error('登入已逾期')}
  if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'資料格式不符或服務失敗');
  return body;
}
const services=document.createElement('div');services.className='service-banner';services.innerHTML='<span id="service-status">正在連接後端…</span><a href="/docs" target="_blank" rel="noopener">API 文件 ↗</a>';$('.scenario-banner').after(services);
const modelPanel=document.createElement('section');modelPanel.className='card live-model';modelPanel.innerHTML=`<div class="card-head"><h2>真實模型推論 <small>CWRU BEARING CLASSIFIER</small></h2><span class="badge">CPU · Decision Tree</span></div><div class="model-body"><div class="model-form"><p>回放大學軸承實驗資料，使用未參與訓練的 3 HP 負載檔案。顯示的是已知故障類型，不是 CNC 實機健康度。</p><select class="btn" id="replay-sample" aria-label="選擇軸承回放資料"><option>正在載入…</option></select><button class="btn primary" id="run-prediction" disabled>執行模型推論 →</button><p class="mt-12">僅包含內圈、滾珠與外圈故障。無正常類別，不能用於正常／異常判定或壽命估計。</p></div><div class="model-output" id="model-result" aria-live="polite">選擇資料後，執行模型查看結果與推論證據。</div></div><details class="model-report"><summary>查看模型評估與資料切分</summary><div id="evaluation-report">尚未載入</div></details>`;$('#dashboard').prepend(modelPanel);
const completion=document.createElement('dialog');completion.id='completion-dialog';completion.innerHTML='<h2>完成維修工單</h2><p>記錄檢查發現、採取措施及修復後結果。</p><form id="completion-form"><label>修復結果<textarea id="completion-note" required minlength="3" maxlength="1000" aria-label="修復結果" placeholder="例如：清潔濾網、確認循環流量；復測溫度下降，主管確認結案。"></textarea></label><div class="actions"><button type="button" class="btn" id="cancel-completion">取消</button><button type="submit" class="btn primary">確認結案</button></div></form>';document.body.append(completion);$('#cancel-completion').onclick=()=>completion.close();
const demoRenderTickets=renderTickets;
renderTickets=function(){
  demoRenderTickets();
  document.querySelectorAll('[data-complete]').forEach(b=>b.onclick=()=>{completingTicket=tickets[+b.dataset.complete].id;$('#completion-note').value='';completion.showModal()});
  if(currentView==='tickets')$('#other-view').querySelector('.badge').textContent='後端資料庫';
  const pending=tickets.filter(t=>t.status!=='已完成').length;$('#ticket-count').textContent=pending;
};
async function refreshTickets(){tickets=await api('/tickets');renderTickets();await renderEngineers()}
$('#completion-form').onsubmit=async e=>{
  e.preventDefault();const button=e.submitter;button.disabled=true;
  try{await api('/tickets/'+encodeURIComponent(completingTicket)+'/complete',{method:'POST',body:JSON.stringify({note:$('#completion-note').value})});completion.close();await refreshTickets();toast('工單已結案，修復結果已保存於資料庫')}catch(error){toast(error.message)}finally{button.disabled=false}
};
$('#ticket-form').onsubmit=async e=>{
  e.preventDefault();if(!serviceReady){toast('後端未連線，無法建立工單');return}const button=e.submitter;button.disabled=true;
  try{await api('/tickets',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({machine:$('#ticket-machine').value,issue:$('#ticket-issue').value,engineer:$('#ticket-engineer').value})});$('#ticket-dialog').close();await refreshTickets();toast('工單已建立並保存於後端資料庫')}catch(error){toast(error.message)}finally{button.disabled=false}
};
renderEngineers=async function(){
  await window.authReady;
  if(factoryType!=='cnc')return;
  if(window.authUser?.role!=='supervisor'){
    $('#engineers').innerHTML='<p>工程師推薦由主管查看與派工。</p>';
    $('#engineers').nextElementSibling.textContent='';
    return;
  }
  const sequence=++engineerRequest,m=machines[selected],part=m.parts[activePart][0];
  try{
    const people=await api('/engineers?machine='+encodeURIComponent(m.id)+'&part='+encodeURIComponent(part));if(sequence!==engineerRequest)return;
    $('#engineers').innerHTML=people.slice(0,3).map(e=>`<div class="engineer"><span class="avatar">${escapeHTML(e.name.split(' ').map(n=>n[0]).join(''))}</span><div class="engineer-info"><b>${escapeHTML(e.name)}</b><p>推薦原因 · ${escapeHTML(m.id)} / ${escapeHTML(part)}</p><ul class="engineer-reasons">${e.reasons.map(r=>`<li>${escapeHTML(r)}</li>`).join('')}</ul><div class="reason-breakdown"><span>專長 ${e.breakdown.skill}/${e.method==='attendance_capacity_rules'?60:40}</span>${e.breakdown.history===undefined?'':`<span>案例 ${e.breakdown.history}/30</span>`}<span>可用性 ${e.breakdown.availability}/${e.method==='attendance_capacity_rules'?40:30}</span></div><button class="assign" data-live-assign="${escapeHTML(e.name)}">指派工單 →</button></div><div class="mini-score">${e.score}<small>規則評分</small></div></div>`).join('');
    $('#engineers').nextElementSibling.textContent='內建人員採展示履歷評分；新建帳號依出勤、資格與剩餘工時推薦。分數由規則計算。';
    document.querySelectorAll('[data-live-assign]').forEach(b=>b.onclick=()=>openTicket(b.dataset.liveAssign));
  }catch(error){if(sequence===engineerRequest)$('#engineers').innerHTML='<div class="engineer-loader">無法讀取推薦：'+escapeHTML(error.message)+'</div>'}
};
$('#analyze').onclick=async()=>{
  const text=$('#prompt').value.trim();if(!text){toast('請輸入問題');return}
  const button=$('#analyze'),answer=$('#ai-answer');button.disabled=true;button.textContent='分析中…';answer.classList.remove('hidden');answer.textContent='正在檢索文件並選取原文…';
  try{
    const result=await api('/copilot',{method:'POST',body:JSON.stringify({text})});
    answer.innerHTML=`<div class="llm-proof">${result.llm_used?(result.provider==='openai'?'✓ OpenAI 已執行':'✓ 本機 LLM 已執行'):'規則處理 · 本次沒有有效 LLM 結果'}<br>模型：${escapeHTML(result.model||'未使用')} · ${result.elapsed_ms} ms<br>請求：${escapeHTML(result.request_id)}</div><div class="pre-line">${escapeHTML(result.answer)}</div><details class="mt-10"><summary>查看結構化資料與處理方式</summary><pre class="proof">${escapeHTML(JSON.stringify({rules:result.extracted,llm:result.generated_fields||null,retrieval:result.retrieval_method,needs_confirmation:result.needs_confirmation},null,2))}</pre></details><div class="source-block">檢索依據 · 虛構示範文件，非原廠規格${result.citations.map(d=>`<details><summary>${escapeHTML(d.id+' · '+d.section+(d.version?' · v'+d.version:'')+(d.line_start?' · 行 '+d.line_start+'–'+d.line_end:'')+(d.is_synthetic?' · 虛構示範':''))}</summary><p>${escapeHTML(d.text)}</p></details>`).join('')||'<p>沒有匹配文件。</p>'}</div>`;
    if(result.extracted.machine_id){const index=machines.findIndex(m=>m.id===result.extracted.machine_id);if(index>=0){selected=index;activePart=0;currentTab='parts';renderFleet();renderDetail()}}
  }catch(error){answer.textContent='分析失敗：'+error.message}finally{button.disabled=false;button.textContent='分析 ↗'}
};
$('#run-prediction').onclick=async()=>{
  const button=$('#run-prediction');button.disabled=true;
  try{
    const result=await api('/predict',{method:'POST',body:JSON.stringify({machine:machines[selected].id,sample_id:$('#replay-sample').value})});
    const probabilities=Object.entries(result.probabilities).map(([k,p])=>`${{inner_race:'內圈',ball:'滾珠',outer_race:'外圈'}[k]} ${(p*100).toFixed(1)}%`).join(' · ');
    const values=result.signal_preview,max=Math.max(...values.map(Math.abs),.001),points=values.map((v,i)=>`${i/(values.length-1)*600},${45-v/max*35}`).join(' ');
    $('#model-result').innerHTML=`<strong>${escapeHTML(result.prediction_label)}</strong><br>分類分數：${escapeHTML(probabilities)}<br>資料標籤：${escapeHTML({inner_race:'內圈故障',ball:'滾珠故障',outer_race:'外圈故障'}[result.expected])}<div class="signal-chart"><svg viewBox="0 0 600 90" preserveAspectRatio="none" role="img" aria-label="回放振動波形示意"><polyline points="${points}" fill="none" stroke="#2b967b" stroke-width="1"/></svg></div><div class="proof">模型 ${escapeHTML(result.model_version)} · ${result.elapsed_ms} ms<br>請求 ${escapeHTML(result.request_id)}<br>輸入 SHA256 ${escapeHTML(result.input_sha256)}</div><p class="text-10-mt-10">${escapeHTML(result.limits)}</p>`;
  }catch(error){$('#model-result').textContent=error.message}finally{button.disabled=false}
};
// CNC is the connected MVP; alternate factory drawings remain in factory.js.
$('#factory').innerHTML='<option value="cnc">CNC 金屬加工廠</option>';
factoryChoices.forEach(f=>{if(f.id!=='cnc')f.live=false});
$('.demo').textContent='MVP · 公開資料回放';
$('.side-bottom').childNodes[1].textContent=' 後端連線與模型回放';
$('footer').lastElementChild.textContent='零件健康度／工廠指標為模擬；軸承分類為實際模型推論';
$('.knowledge h2').textContent='展示維修文件 · 非原廠手冊';
$('.copilot .badge').textContent='LOCAL LLM';
$('.input-bottom span').textContent='文字輸入 · AI 與文件檢索';
$('#prompt').placeholder='例如：CNC01 的冷卻泵應該檢查什麼？';
openDoc=async function(id){
  try{
    const query=id==='E102'?'E102':id==='bearing'?'軸承':'冷卻';
    const docs=await api('/documents?q='+encodeURIComponent(query));
    $('#doc-title').textContent='展示維修文件 · 非原廠手冊';
    $('#doc-text').textContent=docs.map(d=>d.title+'\n'+d.id+' · '+d.section+'\n'+d.text).join('\n\n');
    $('#doc-dialog .subnote').textContent='專案自製文件；與 Copilot 使用相同檢索來源。';
    $('#doc-dialog').showModal();
  }catch(error){toast(error.message)}
};
$('#recent-tickets').closest('section').querySelector('h2').innerHTML='維修工單 <small>DATABASE</small>';
const changeView=switchView;
switchView=function(view){changeView(view);if(view==='tickets')renderTickets();if(view==='knowledge'){
  $('#other-view').innerHTML='<div class="view-panel"><h2>本機維修知識 · 展示文件</h2><p class="mt-12">文件為專案撰寫示例。回答保留文件來源，由 AI 選取可核對的原文。</p><input class="search" aria-label="搜尋維修文件" placeholder="搜尋軸承、冷卻、刀具…"><div id="live-docs"></div></div>';
  let querySequence=0;
  async function load(){const seq=++querySequence;try{const docs=await api('/documents?q='+encodeURIComponent($('.search').value));if(seq!==querySequence||!$('#live-docs'))return;$('#live-docs').innerHTML=docs.map(d=>`<details class="recommend block-mb-10"><summary>${escapeHTML(d.id+' · '+d.title)}</summary><p>${escapeHTML(d.text)}</p></details>`).join('')||'<p>沒有匹配文件。</p>'}catch(error){if($('#live-docs'))$('#live-docs').textContent=error.message}}
  $('.search').oninput=load;load();
}};
async function initialize(){
  try{
    const health=await api('/health');serviceReady=true;
    $('#service-status').textContent=`後端：${health.database} · 感測模型：${health.sensor_model_ready?'已載入':'尚未準備'} · AI：${health.llm.provider==='openai'?'OpenAI 已設定':(health.llm.available?health.llm.model:'尚未就緒')} · 零件健康：模擬`;
    await refreshTickets();
    const [samples,report]=await Promise.all([api('/replay'),api('/model/report')]);
    $('#replay-sample').innerHTML=samples.map(s=>`<option value="${escapeHTML(s.sample_id)}">${escapeHTML({inner_race:'內圈',ball:'滾珠',outer_race:'外圈'}[s.expected])} · 檔案 ${escapeHTML(s.file)} · 視窗 ${s.window_index}</option>`).join('');
    $('#run-prediction').disabled=!samples.length;
    $('#evaluation-report').innerHTML=`<p class="mt-13">測試 Macro-F1：${report.test.macro_f1.toFixed(3)} · 多數類別基準：${report.baseline_test.macro_f1.toFixed(3)}<br>訓練負載 0/1 HP；驗證 2 HP；測試 3 HP。測試共有 ${report.split.test_windows} 個非重疊視窗，僅 3 個獨立檔案。此測試不是未見軸承／工廠驗證。</p><pre>${escapeHTML(JSON.stringify(report,null,2))}</pre>`;
  }catch(error){$('#service-status').textContent='後端或模型尚未就緒：'+error.message;$('#model-result').textContent=error.message;}
}
function partRisk(p){return p[1]<45?'critical':p[1]<70?'watch':'stable'}
function riskLabel(p){return {critical:'警示',watch:'注意',stable:'正常'}[partRisk(p)]}
function renderEquipmentOverview(){
  $('#other-view').innerHTML=`<div class="card-head"><h2>設備總覽 <small>PART CONDITION MAP</small></h2><span class="badge">${machines.length} 台 DEMO</span></div><div class="overview-intro"><p>直接拖曳或使用滑桿旋轉機器；選擇零件可在卡片內查看狀態與檢查線索。</p><div class="risk-legend"><span class="critical">● 警示：健康 &lt; 45%</span><span class="watch">● 注意：45–69%</span><span class="stable">● 正常：≥ 70%</span></div><p>門檻、設備與零件數值皆為模擬，不是 AI 故障機率。零件位置為概念示意。</p></div><div class="equipment-grid">${machines.map((m,i)=>`<article class="equipment-tile risk-tile" data-overview-machine="${i}"><div class="tile-heading"><h3>${escapeHTML(m.id)}</h3><span class="badge ${minHealth(m)<70?'orange':''}">${escapeHTML(m.status)}</span></div><p>${escapeHTML(m.name)}</p><div class="overview-model">${machineModel(m,true).replaceAll('data-part=','data-overview-part=')}</div><div class="viewer-control"><label for="overview-rotation-${i}">旋轉視角</label><input id="overview-rotation-${i}" type="range" min="-180" max="180" value="-32" aria-label="${escapeHTML(m.id)} 旋轉視角"><button class="link overview-reset">重設</button></div><div class="tile-meta"><span>設備使用率<b>${m.util}%</b><small>本班運轉時間／排程時間</small></span><span>累積運轉<b>${(m.hours?.toLocaleString()??'未建檔')} h</b><small>展示累積值</small></span></div><div class="overview-parts">${m.parts.map((p,j)=>`<button class="overview-part ${partRisk(p)}" data-overview-select="${j}"><span>${j+1} · ${escapeHTML(p[0])}</span><b>${riskLabel(p)} · 健康 ${p[1]}%</b></button>`).join('')}</div><div class="overview-part-info" aria-live="polite"></div><div class="tile-bottom"><span>直接在此檢視與旋轉</span><button class="btn primary overview-work">處理此零件 →</button></div></article>`).join('')}</div>`;
  document.querySelectorAll('[data-overview-machine]').forEach(card=>{
    const i=+card.dataset.overviewMachine,m=machines[i],stage=card.querySelector('.model-stage'),world=card.querySelector('.model-world'),slider=card.querySelector('input');
    let chosen=m.parts.findIndex(p=>p[1]===minHealth(m)),angle=-32,drag=null;
    function rotate(v){angle=+v;world.style.transform=`scale(1.3) rotateX(-17deg) rotateY(${angle}deg)`;slider.value=angle}
    function selectPart(j){chosen=j;const p=m.parts[j],unit=/刀具|刀片/.test(p[0])?'分鐘':'小時';
      card.querySelectorAll('[data-overview-select]').forEach(b=>b.setAttribute('aria-pressed',+b.dataset.overviewSelect===j));
      card.querySelectorAll('[data-overview-part]').forEach((b,k)=>{b.className='part-dot '+partRisk(m.parts[k])+(k===j?' selected-part':'');b.setAttribute('aria-label',m.id+' '+m.parts[k][0]+' '+riskLabel(m.parts[k])+' 健康 '+m.parts[k][1]+'%');b.setAttribute('aria-pressed',k===j);b.title=m.parts[k][0]+' · '+riskLabel(m.parts[k]);});
      card.querySelectorAll('.part-cube').forEach((c,k)=>c.className='cuboid part-cube '+partRisk(m.parts[k]));
      card.querySelector('.overview-part-info').innerHTML=`<strong>${escapeHTML(p[0])}</strong><p>${escapeHTML(p[5])}</p><div>累積 ${p[2].toLocaleString()} ${unit}／參考週期 ${p[3].toLocaleString()} ${unit}<br>參考週期使用比例 ${Math.round(p[2]/p[3]*100)}% · 模擬，非剩餘壽命</div>`;
    }
    card.querySelectorAll('[data-overview-select]').forEach(b=>b.onclick=()=>selectPart(+b.dataset.overviewSelect));
    card.querySelectorAll('[data-overview-part]').forEach(b=>b.onclick=()=>selectPart(+b.dataset.overviewPart));
    slider.oninput=()=>rotate(slider.value);card.querySelector('.overview-reset').onclick=()=>rotate(-32);
    stage.onpointerdown=e=>{if(e.target.closest('button'))return;drag={x:e.clientX,angle};stage.setPointerCapture(e.pointerId)};
    stage.onpointermove=e=>{if(drag)rotate(Math.max(-180,Math.min(180,drag.angle+(e.clientX-drag.x)*.7)))};
    stage.onpointerup=stage.onpointercancel=()=>drag=null;
    card.querySelector('.overview-work').onclick=()=>{selected=i;activePart=chosen;currentTab='parts';switchView('dashboard');renderFleet();renderDetail();$('.detail').scrollIntoView({behavior:'smooth',block:'start'})};
    rotate(-32);selectPart(chosen);
  });
}
const operationalSwitch=switchView;
switchView=function(view){
  operationalSwitch(view);
  if(view==='equipment'){renderEquipmentOverview();$('#page-subtitle').textContent='巡視產線，直接查看機器各零件的狀態。'}
  if(view==='dashboard')$('#page-subtitle').textContent='處理維修事件：確認線索、查文件、選技師、建立與追蹤工單。';
  if(view==='analytics'){
    $('#page-subtitle').textContent='回顧維修成效，找出重複故障與改善方向。';
    $('#other-view').insertAdjacentHTML('afterbegin','<div class="overview-intro"><b>維修分析用來回顧與改善</b><p>觀察哪些設備常壞、維修多久、哪些故障重複發生，以及修復後是否有效。正式版可依工單計算 MTTR、重複故障率及成本；MTBF 還需要實際運轉時間與故障事件。下方目前為展示統計，尚未從資料庫彙整。</p></div>');
  }
};
$('#page-subtitle').textContent='處理維修事件：確認線索、查文件、選技師、建立與追蹤工單。';
initialize();
