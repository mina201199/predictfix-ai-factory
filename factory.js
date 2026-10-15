// Demo component state is explicit; these scores are not trained model outputs.
const factoryChoices = [
  {id:'cnc', title:'CNC 金屬加工廠', equipment:'立式加工中心、精密車床、高速加工中心', reason:'推薦：刀具與軸承資料能對應零件健康度，維修流程容易呈現。', live:true},
  {id:'rotating', title:'旋轉設備維修場景', equipment:'工業馬達、離心泵、空壓機', reason:'推薦：先聚焦馬達軸承。公開實驗資料豐富；泵與空壓機仍需各自資料驗證。', live:true},
  {id:'semiconductor', title:'半導體晶圓廠', equipment:'蝕刻、沉積、清洗設備', reason:'候選：SECOM 適合良率分析，不能直接當成各零件健康度資料。', live:false},
  {id:'electronics', title:'電子組裝廠', equipment:'錫膏印刷、貼片、回焊設備', reason:'候選：可做影像品質檢測；零件壽命需額外資料。', live:false},
  {id:'plastic', title:'塑膠射出廠', equipment:'射出機、乾燥機、冰水機', reason:'候選：有製程、品質與能源資料；先做品質或能源分析較合適。', live:false}
];
let factoryType='cnc', activePart=0, rotation=-32;
const cncMachines = [
  {id:'CNC-01',name:'立式加工中心',kind:'mill',temp:48,vib:2.1,risk:12,status:'運行正常',hours:2840,util:68,parts:[['主軸軸承',93,2840,12000,540,'潤滑與振動穩定，維持例行巡檢。'],['切削刀具',78,168,240,72,'已累積 168 分鐘切削時間，建議檢查刃口磨耗。'],['冷卻泵',91,2300,8000,820,'流量穩定，依保養週期檢查濾網。'],['進給螺桿',96,2840,16000,1200,'定位誤差穩定，定期潤滑。']]},
  {id:'CNC-02',name:'精密車削中心',kind:'lathe',temp:54,vib:2.8,risk:24,status:'運行正常',hours:4250,util:81,parts:[['主軸軸承',84,4250,12000,390,'振動略增，建議於下次保養檢查潤滑。'],['車削刀片',64,178,220,42,'刃口磨耗增加，可預先安排換刀。'],['液壓泵',89,3500,10000,670,'液壓輸出穩定，持續監測。'],['進給螺桿',92,4250,16000,960,'檢查防塵罩與潤滑狀態。']]},
  {id:'CNC-03',name:'高速加工中心',kind:'mill',temp:92,vib:8.4,risk:82,status:'需要關注',hours:7680,util:92,parts:[['主軸軸承',38,7680,12000,36,'振動偏高且溫度異常，優先檢查軸承與潤滑；健康度低於展示警戒值。'],['切削刀具',56,196,240,44,'已使用 82% 展示額定切削時間，檢查刃口並準備替換刀具。'],['冷卻泵',62,5160,8000,120,'流量下降可能與濾網或循環泵有關，建議檢查冷卻系統。'],['進給螺桿',88,7680,16000,460,'定位狀態穩定，依計畫保養。']]}
];
// Additional machines use deliberately authored demo states, not sensor inference.
[
  ['CNC-04','五軸加工中心','mill',74,[89,82,94,90]],
  ['CNC-05','重切削車床','lathe',86,[76,31,85,91]],
  ['CNC-06','鑽攻加工中心','mill',57,[95,88,44,92]],
  ['CNC-07','複合車銑中心','lathe',79,[86,73,90,58]],
  ['CNC-08','模具精加工中心','mill',64,[92,85,93,96]],
  ['CNC-09','立式加工中心 B','mill',45,[68,79,81,39]]
].forEach(([id,name,kind,util,health],n)=>{
  const base=cncMachines[kind==='lathe'?1:0];
  const parts=base.parts.map((p,i)=>[p[0],health[i],Math.round(p[3]*(.28+(n+i)*.07)),p[3],null,
    health[i]<45?'展示警示：狀態偏低，安排檢查確認。':health[i]<70?'展示注意：追蹤狀態並安排保養。':'展示狀態穩定，維持例行巡檢。']);
  cncMachines.push({id,name,kind,util,parts,hours:3100+n*580,temp:48+n*3,vib:2+n*.3,
    risk:100-Math.min(...health),status:Math.min(...health)<45?'需要關注':Math.min(...health)<70?'安排保養':'運行正常'});
});
const rotatingMachines=[
  {id:'MTR-01',name:'工業感應馬達',kind:'motor',temp:49,vib:2.4,risk:15,status:'運行正常',hours:3200,util:75,parts:[['驅動端軸承',91,3200,12000,600,'振動正常，定期檢查潤滑。'],['非驅動端軸承',94,3200,12000,720,'振動穩定，維持巡檢。'],['冷卻風扇',88,3200,9000,440,'檢查風道與積塵。'],['聯軸器',92,2800,10000,580,'確認對心與固定件。']]},
  {id:'PMP-02',name:'離心泵',kind:'pump',temp:57,vib:3.1,risk:28,status:'運行正常',hours:4900,util:83,parts:[['泵軸軸承',85,4900,12000,360,'依保養計畫檢查振動。'],['機械軸封',72,3600,6000,210,'監測滲漏，準備備品。'],['葉輪',90,4900,15000,880,'流量與效率穩定。'],['聯軸器',87,4200,10000,380,'定期檢查對心。']]},
  {id:'CMP-03',name:'螺桿空壓機',kind:'compressor',temp:88,vib:7.2,risk:76,status:'需要關注',hours:8900,util:94,parts:[['主軸軸承',42,8900,14000,48,'振動偏高，優先檢查軸承與潤滑。'],['油氣分離器',55,2700,4000,96,'壓差上升，建議檢查並準備替換。'],['冷卻風扇',68,6300,10000,160,'散熱效率下降，檢查積塵與風道。'],['進氣閥',83,8900,16000,400,'動作穩定，維持巡檢。']]}
];
function cube(x,y,z,w,h,d,c,inner='',cls=''){
  return `<div class="cuboid ${cls}" style="--x:${x}px;--y:${y}px;--z:${z}px;--w:${w}px;--h:${h}px;--d:${d}px;${c?`--c:${c};`:''}">${['front','back','right','left','top','bottom'].map(face=>`<div class="face ${face}">${face==='front'?inner:''}</div>`).join('')}</div>`;
}
// Code-native cutaway geometry: shells, assemblies and hotspots rotate together.
function detailedMachineModel(m, interactive = false) {
  const label=value=>String(value).replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const metal = '#b7c9d5', dark = '#435e72';
  const box = (x,y,z,w,h,d,c=metal,html='',cls='housing') => cube(x,y,z,w,h,d,c,html,cls);
  const isLathe = m.kind === 'lathe';
  const isCNC = m.kind === 'mill' || isLathe;
  let structure = box(12,121,0,168,16,98,dark,'','chassis');
  structure += box(19,137,22,23,8,19,dark,'','foot') + box(145,137,22,23,8,19,dark,'','foot');
  if (isCNC) {
    // Open front construction leaves a visible working chamber even in solid mode.
    structure += box(22,19,-32,130,101,8,metal,'','shell rear-wall');
    structure += box(22,19,0,12,101,74,metal,'','shell pillar');
    structure += box(140,19,0,12,101,74,metal,'','shell pillar');
    structure += box(22,13,0,130,12,74,metal,'','shell roof');
    structure += box(23,105,0,130,16,74,metal,'<span class="machine-plate">'+(isLathe?'TURNING CENTER':'MACHINING CENTER')+'</span>','shell sill');
    structure += box(153,36,24,24,64,19,dark,'<div class="control-display"><i></i><span>•••</span><b>●</b></div>','console');
    structure += box(37,27,38,97,77,2,'#92dcf5','<span class="door-handle"></span>','shell glass-door');
    structure += box(155,17,0,6,14,6,'#2bf1c8','','signal-light');
    structure += box(34,97,0,99,6,55,dark,'','machine-table');
    structure += box(38,92,0,90,4,4,metal,'','rail') + box(38,92,-23,90,4,4,metal,'','rail');
    structure += box(68,28,-23,27,65,13,dark,'','spindle-column');
    structure += box(70,28,0,30,13,34,metal,'','spindle-head');
    structure += box(45,82,2,78,9,45,metal,'','work-bed');
    structure += box(34,24,34,4,78,4,dark,'','door-frame') + box(135,24,34,4,78,4,dark,'','door-frame');
  } else {
    const type = m.kind;
    structure += box(28,39,-25,130,80,8,metal,'','shell rear-wall');
    structure += box(28,32,0,12,88,65,metal,'','shell pillar') + box(146,32,0,12,88,65,metal,'','shell pillar');
    structure += box(28,28,0,130,10,65,metal,'','shell roof');
    structure += box(42,40,34,101,73,2,'#92dcf5','','shell glass-door');
    structure += box(53,19,-10,46,13,28,dark,'','terminal-box');
    structure += box(158,51,10,19,45,15,dark,'<div class="control-display"><i></i><span>•••</span></div>','console');
    if (type === 'pump') structure += box(118,8,0,15,29,15,metal,'','pipe');
  }
  const coords = isLathe ? [[47,54,10],[104,66,23],[123,91,2],[53,99,22]] : isCNC ? [[83,38,5],[84,71,23],[120,91,5],[42,99,22]] : [[58,56,5],[104,56,6],[126,91,5],[45,99,22]];
  // Exactly one part-cube root per data part keeps existing selection mapping stable.
  const assemblies = m.parts.map((part,i) => {
    const p=coords[i]||[30+(i%4)*34,26+Math.floor(i/4)*24,35];
    const health=m.parts[i][1], state=health == null?'unknown':health<45?'critical':health<70?'watch':'stable';
    const cls=`part-cube ${state} ${interactive && i===activePart?'active':''}`;
    const shape = i===0 ? 'bearing' : i===1 ? (isCNC?'tool':'rotor') : i===2?'pump':i===3?'screw':'rotor';
    const w=i===3?76:i===2?23:25, h=i===0?28:i===1?23:i===2?26:9;
    const assembly=box(p[0]-8,p[1]-7,p[2],w,h,i===3?9:24,'#71adc6',`<span class="mechanical-${shape}"></span>`,cls);
    const hotspot=interactive?`<button class="part-dot ${state} ${i===activePart?'active':''}" data-part="${i}" aria-label="查看${label(m.parts[i][0])}" aria-pressed="${i===activePart}" style="--x:${p[0]+5}px;--y:${p[1]-9}px;--z:${p[2]+31}px">${i+1}</button>`:'';
    return assembly+hotspot;
  }).join('');
  return `<div class="model-stage detailed-model ${interactive?'interactive-model cutaway':''}" aria-label="${label(m.name)} · ${interactive?'可旋轉零件剖視模型':'金屬機台模型'}"><div class="model-world" ${interactive?`style="transform:scale(1.45) rotateX(-17deg) rotateY(${rotation}deg)"`:''}><div class="model-floor"></div>${structure}${assemblies}</div>${interactive?'<button type="button" class="model-shell-toggle" aria-pressed="true">外殼透視：開</button>':''}<span class="model-mode">${interactive?'CUTAWAY · 零件透視':'DIGITAL TWIN · 設備模型'}</span></div>`;
}
document.addEventListener('click',event=>{
  const toggle=event.target.closest('.model-shell-toggle');if(!toggle)return;
  const stage=toggle.closest('.model-stage'),enabled=stage.classList.toggle('cutaway');
  toggle.setAttribute('aria-pressed',enabled);toggle.textContent='外殼透視：'+(enabled?'開':'關');
  stage.querySelector('.model-mode').textContent=enabled?'CUTAWAY · 零件透視':'SOLID · 金屬外殼';
});

function machineModel(m,interactive=false){return detailedMachineModel(m,interactive)}
function minHealth(m){return Math.min(...m.parts.map(p=>p[1]))}
function renderEngineers(){
  const m=machines[selected],p=m.parts[activePart];
  const candidates=[
    {initial:'AC',name:'Amy Chen',skills:40,history:m.risk>70?27:24,load:24,reason:[`具備${factoryType==='cnc'?'CNC 主軸與軸承':'旋轉設備軸承'}維修經驗，對應 ${m.id} 的${p[0]}檢查。`,'18 筆相似案例成功修復 16 筆（89%），有異常排除經驗。','目前 1 筆進行中工單，預計 30 分鐘後可接案。']},
    {initial:'AL',name:'Alex Lin',skills:p[0].includes('泵')?40:34,history:25,load:25,reason:[`${factoryType==='cnc'?'擅長冷卻、液壓與潤滑系統，可處理過熱相關檢查。':'擅長泵浦、冷卻與潤滑系統，可協助散熱檢查。'}`,'12 筆相似案例成功修復 10 筆（83%）。','目前 0 筆進行中工單，可立即接案。']},
    {initial:'BW',name:'Bob Wang',skills:27,history:21,load:15,reason:['具備綜合設備巡檢能力，適合協助量測與例行保養。','4 筆相似案例成功修復 3 筆（75%），專項案例較少。','目前 3 筆進行中工單，預計 2 小時後可接案。']}
  ].sort((a,b)=>(b.skills+b.history+b.load)-(a.skills+a.history+a.load));
  $('#engineers').innerHTML=candidates.map((e,i)=>`<div class="engineer"><span class="avatar">${e.initial}</span><div class="engineer-info"><b>${e.name}</b><p>推薦原因 · ${escapeHTML(m.id)}</p><ul class="engineer-reasons">${e.reason.map(r=>`<li>${escapeHTML(r)}</li>`).join('')}</ul><div class="reason-breakdown"><span>專長 ${e.skills}/40</span><span>案例 ${e.history}/30</span><span>可用性 ${e.load}/30</span></div><button class="assign" data-technician="${e.name}">指派工單 →</button></div><div class="mini-score">${e.skills+e.history+e.load}<small>匹配分數</small></div></div>`).join('');
  $('#engineers').nextElementSibling.textContent='展示評分：專長 40%＋相似案例 30%＋可用性 30%。非真實人員履歷。';
  document.querySelectorAll('[data-technician]').forEach(b=>b.onclick=()=>openTicket(b.dataset.technician));
}
renderFleet=function(){
  $('#fleet').innerHTML=machines.map((m,i)=>`<button class="machine ${i===selected?'selected':''}" data-machine="${i}" aria-pressed="${i===selected}"><div class="machine-top">${escapeHTML(m.id)}<span class="badge ${m.risk>70?'orange':''}">${escapeHTML(m.status)}</span></div><div class="machine-name">${escapeHTML(m.name)}</div>${machineModel(m)}<div class="model-caption">3D 示意 · 點選查看設備零件</div><div class="machine-stats"><span>使用率 <b>${m.util}%</b></span><span>最低健康 <b>${minHealth(m)}%</b></span></div><div class="risk-bar"><i style="width:${minHealth(m)}%;background:${minHealth(m)<60?'#d99a48':'#3caa8b'}"></i></div><div class="risk-caption"><span>零件最低健康度 · 模擬</span><span>${escapeHTML(m.parts.find(p=>p[1]===minHealth(m))[0])}</span></div></button>`).join('');
  document.querySelectorAll('[data-machine]').forEach(b=>b.onclick=()=>{selected=+b.dataset.machine;activePart=0;currentTab='parts';renderFleet();renderDetail()});
};
const oldDetail=renderDetail;
renderDetail=function(){
  const m=machines[selected];
  if(currentTab!=='parts'&&factoryType==='cnc'){oldDetail();renderEngineers();return}
  $('#device-heading').textContent=m.id;$('#device-badge').textContent=m.status;$('#device-badge').className='badge '+(m.risk>70?'orange':'');$('#device-location').textContent=m.name+' · 零件健康';
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===currentTab));
  if(currentTab==='parts'){
    const p=m.parts[activePart],tool=/刀具|刀片/.test(p[0]),unit=tool?'分鐘':'小時',used=p[3]>0?Math.min(100,Math.round(p[2]/p[3]*100)):null,color=p[1]<60?'#d39945':'#319c7d';
    $('#detail-content').innerHTML=`<div class="component-layout"><div class="viewer"><div class="viewer-title"><b>${escapeHTML(m.name)} · 內部零件</b><span>金屬機台 · 零件透視</span></div>${machineModel(m,true)}<div class="viewer-control"><span>視角</span><input type="range" min="-180" max="180" value="${rotation}" id="model-rotation" aria-label="旋轉機器視角"><button class="link" id="reset-rotation">重設</button></div><p class="subnote">拖曳旋轉，或使用滑桿；點選數字定位零件。位置為概念示意。</p></div><div class="part-list">${m.parts.map((part,i)=>`<button class="part-button ${i===activePart?'active':''}" data-part="${i}"><div class="row">${i+1}. ${escapeHTML(part[0])}<span style="color:${part[1]<60?'#c38c3c':'#319c7d'}">健康 ${part[1]}%</span></div><div class="battery">${Array.from({length:10},(_,n)=>`<i style="${n<Math.round(part[1]/10)?`background:${part[1]<60?'#d39945':'#319c7d'}`:''}"></i>`).join('')}</div><small>累積 ${part[2].toLocaleString()} ${/刀具|刀片/.test(part[0])?'分鐘':'小時'} · ${part[1]<60?'建議檢查':'持續監控'}</small></button>`).join('')}</div></div><div class="component-detail"><div style="display:flex;justify-content:space-between;gap:8px"><h3>${escapeHTML(p[0])}</h3><span class="badge ${p[1]<60?'orange':''}">${p[1]<60?'需要關注':'狀態穩定'}</span></div><div class="component-kpis"><div><span>健康度 · 越高越健康</span><strong style="color:${color}">${p[1]}%</strong><small>綜合劣化指標 · 模擬</small></div><div><span>額定壽命使用比例</span><strong>${used===null?'未設定':used+'%'}</strong><small>${p[2].toLocaleString()} / ${p[3].toLocaleString()} ${unit}</small></div><div><span>估計剩餘使用時間</span><strong>${p[4]===null?'未估計':p[4]} <small>${p[4]===null?'':unit}</small></strong><small>展示估計，非保證壽命</small></div></div><p>${escapeHTML(p[5])}</p><div class="component-explain"><b>健康度 ≠ 使用率。</b>健康度像電池健康，代表狀態劣化程度；額定壽命使用比例是累積使用時間 ÷ 設定參考壽命；設備使用率是今天運轉時間占排程時間的比例。三者分開顯示，所有數值目前為模擬。</div><div class="actions" style="margin-top:16px"><button class="btn primary" id="component-ticket">為此零件建立工單 →</button></div></div>`;
    document.querySelectorAll('[data-part]').forEach(b=>b.onclick=()=>{activePart=+b.dataset.part;renderDetail()});
    const stage=$('.interactive-model'),world=stage.querySelector('.model-world');
    function rotate(v){rotation=+v;world.style.transform=`scale(1.45) rotateX(-17deg) rotateY(${rotation}deg)`;$('#model-rotation').value=rotation}
    $('#model-rotation').oninput=e=>rotate(e.target.value);$('#reset-rotation').onclick=()=>rotate(-32);
    let drag=null;stage.onpointerdown=e=>{if(e.target.closest('button'))return;drag={x:e.clientX,angle:rotation};stage.setPointerCapture(e.pointerId)};stage.onpointermove=e=>{if(drag)rotate(Math.max(-180,Math.min(180,drag.angle+(e.clientX-drag.x)*.7)))};stage.onpointerup=()=>drag=null;stage.onpointercancel=()=>drag=null;
    $('#component-ticket').onclick=()=>{openTicket();$('#ticket-issue').value=m.parts[activePart][0]+' · 健康度 '+m.parts[activePart][1]+'% · 安排檢查'};
  }else if(currentTab==='health'){
    $('#detail-content').innerHTML=`<div class="alert"><b>${escapeHTML(m.id)} · 模擬感測診斷</b></div><div class="component-kpis"><div><span>溫度</span><strong>${m.temp}°C</strong></div><div><span>振動</span><strong>${m.vib}<small> mm/s</small></strong></div><div><span>示意故障風險</span><strong>${m.risk}%</strong></div></div><p>${m.risk>70?'振動與溫度偏高，檢查軸承、潤滑與冷卻。':'數值穩定，維持例行巡檢。'}</p><p class="subnote">未接入預測模型；不代表未來 7 天的校準故障機率。</p>`;
  }else if(currentTab==='repair'){
    $('#detail-content').innerHTML='<div class="recommend-list">'+['檢查軸承與振動','檢查潤滑與冷卻','檢查聯軸器與固定件'].map((r,i)=>`<div class="recommend"><span class="rank">${i+1}</span><div><h3>${r}</h3><p>${escapeHTML(m.id)} · 展示維修方案</p></div></div>`).join('')+'</div>';
  }else $('#detail-content').innerHTML=`<p>${escapeHTML(m.id)} 展示情境尚未提供維修歷史。工單可於「維修工單」頁查看。</p>`;
  renderEngineers();
};
const oldSwitch=switchView;
switchView=function(view){
  oldSwitch(view);
  if(view==='equipment'){
    $('#other-view').innerHTML=`<div class="card-head"><h2>機器列表 <small>3D EQUIPMENT</small></h2><span class="badge">${machines.length} 台 · 模擬</span></div><div class="equipment-grid">${machines.map((m,i)=>`<article class="equipment-tile"><div style="display:flex;justify-content:space-between"><h3>${escapeHTML(m.id)}</h3><span class="badge ${m.risk>70?'orange':''}">${escapeHTML(m.status)}</span></div><p>${escapeHTML(m.name)}</p>${machineModel(m)}<div class="tile-meta"><span>設備使用率<b>${m.util}%</b></span><span>最低零件健康<b>${minHealth(m)}%</b></span><span>累積運轉<b>${(m.hours?.toLocaleString()??'未建檔')}<small style="font-size:10px"> h</small></b></span></div><div class="tile-bottom"><span style="font-size:10px;color:#8c9e95">${m.parts.length} 個零件可檢視</span><button class="btn primary" data-inspect-parts="${i}">零件健康 →</button></div></article>`).join('')}</div>`;
    document.querySelectorAll('[data-inspect-parts]').forEach(b=>b.onclick=()=>{selected=+b.dataset.inspectParts;activePart=0;currentTab='parts';switchView('dashboard');renderFleet();renderDetail();$('.detail').scrollIntoView({behavior:'smooth',block:'start'})});
  }
  if(factoryType!=='cnc'&&view==='knowledge')$('#other-view').innerHTML='<div class="view-panel"><h2>旋轉設備知識來源</h2><p style="margin-top:15px">目前僅提供零件健康度與維修建議示例。正式知識庫需加入相應設備的操作與維修手冊。</p><p style="margin-top:15px"><a href="https://engineering.case.edu/bearingdatacenter" target="_blank" rel="noopener">CWRU 軸承實驗資料</a> · <a href="https://catalog.data.gov/dataset/ims-bearings" target="_blank" rel="noopener">NASA IMS 軸承資料</a></p></div>';
  if(factoryType!=='cnc'&&view==='analytics')$('#other-view').innerHTML='<div class="view-panel"><h2>旋轉設備維修分析</h2><p style="margin-top:15px">此候選情境尚未建立歷史統計。可先由機器列表檢查零件與建立工單。</p></div>';
};
const baseOpenTicket=openTicket;
openTicket=function(engineer='待指派'){$('#ticket-machine').innerHTML=machines.map(m=>`<option>${escapeHTML(m.id)}</option>`).join('');baseOpenTicket(engineer);if(factoryType!=='cnc')$('#ticket-issue').value=machines[selected].name+' · 設備巡檢'};
const baseRenderTickets=renderTickets;
renderTickets=function(){baseRenderTickets();$('#pending-summary').textContent=tickets.filter(t=>t.status==='處理中').length+' 筆處理中 · '+tickets.filter(t=>t.status!=='已完成'&&t.engineer==='待指派').length+' 筆待指派'};
function applyFactory(type){
  const f=factoryChoices.find(f=>f.id===type);if(!f||!f.live)return;
  factoryType=type;machines.splice(0,machines.length,...(type==='cnc'?cncMachines:rotatingMachines));selected=2;activePart=0;currentTab='parts';
  $('#factory').value=type;$('#scenario-title').textContent=f.title+' · 展示產線';$('#scenario-desc').textContent=f.equipment+'。'+f.reason;
  $('#prompt').value='';$('#ai-answer').classList.add('hidden');$('#prompt').placeholder=`例如：${machines[2].id} 的軸承健康度多少？`;
  $('.knowledge').classList.toggle('hidden',type!=='cnc');
  const metrics=document.querySelectorAll('.metric');metrics[1].querySelector('.number').innerHTML=machines.filter(m=>minHealth(m)<45).length+'<small>/ '+machines.length+' 台</small>';
  switchView(currentView);renderFleet();renderDetail();renderTickets();
}
const oldAnalyze=$('#analyze').onclick;
$('#analyze').onclick=()=>{
  const q=$('#prompt').value.trim();
  if(/健康|零件|壽命/.test(q)||factoryType!=='cnc'){
    if(!q){toast('請先輸入設備問題');return}
    const found=machines.findIndex(m=>q.replaceAll('-','').toUpperCase().includes(m.id.replaceAll('-','')));if(found>=0)selected=found;
    currentTab='parts';activePart=0;renderFleet();renderDetail();const m=machines[selected],p=m.parts[0];
    $('#ai-answer').classList.remove('hidden');$('#ai-answer').innerHTML=`<b>${escapeHTML(m.id)} · 零件健康示例</b><br>${escapeHTML(p[0])}健康度 <b>${p[1]}%</b>。${escapeHTML(p[5])}<br><span class="subnote">已開啟零件檢視。所有健康與壽命數值為展示設定。</span>`;
  }else oldAnalyze();
};
document.querySelectorAll('[data-prompt]').forEach((b,i)=>b.onclick=()=>{$('#prompt').value=[`${machines[2].id} 的零件健康度多少？`,`${machines[selected].id} 今年維修過幾次？`,'E102 是什麼？'][i];$('#analyze').click()});
// Add scenario chooser and a component tab without requiring network assets.
const chooser=document.createElement('dialog');chooser.id='factory-dialog';chooser.innerHTML='<h2>選擇工廠情境</h2><p>目前已提供 CNC 與旋轉設備兩種可操作示例；其餘情境列為專案候選。</p><div class="factory-options"></div><div class="actions"><button class="btn" id="close-factory">關閉</button></div>';document.body.append(chooser);
function showFactories(){chooser.querySelector('.factory-options').innerHTML=factoryChoices.map(f=>`<button class="factory-option ${factoryType===f.id?'chosen':''}" data-factory-choice="${f.id}"><b>${f.title} <span class="badge ${f.live?'':'gray'}">${f.live?'可操作示例':'候選 · 尚未建立'}</span></b><span>${f.equipment}<br>${f.reason}</span></button>`).join('');chooser.querySelectorAll('[data-factory-choice]').forEach(b=>b.onclick=()=>{const f=factoryChoices.find(f=>f.id===b.dataset.factoryChoice);if(f.live){applyFactory(f.id);chooser.close()}else toast(f.title+' 尚未建立，先比較資料與選定方向。')});chooser.showModal()}
$('#close-factory').onclick=()=>chooser.close();
$('#factory').innerHTML=factoryChoices.filter(f=>f.live).map(f=>`<option value="${f.id}">${f.title}</option>`).join('');$('#factory').setAttribute('aria-label','選擇工廠情境');$('#factory').onchange=()=>applyFactory($('#factory').value);
const banner=document.createElement('div');banner.className='scenario-banner';banner.innerHTML='<span class="ai-icon">▦</span><div><b id="scenario-title"></b><p id="scenario-desc"></p></div><button class="btn" id="choose-factory">比較工廠情境 →</button>';$('.title-row').after(banner);$('#choose-factory').onclick=showFactories;
const partTab=document.createElement('button');partTab.className='tab';partTab.dataset.tab='parts';partTab.textContent='零件健康 / 3D';$('.tabs').prepend(partTab);partTab.onclick=()=>{currentTab='parts';renderDetail()};
machines.splice(0,machines.length,...cncMachines);currentTab='parts';applyFactory('cnc');
