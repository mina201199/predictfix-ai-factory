const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

async function checkRole(role){
  const calls=[],elements=new Map();
  const element=selector=>{
    if(!elements.has(selector))elements.set(selector,{innerHTML:'',textContent:'',nextElementSibling:{textContent:''}});
    return elements.get(selector);
  };
  const context=vm.createContext({
    window:{authUser:{role},authReady:Promise.resolve()},Promise,
    $:element,document:{querySelectorAll:()=>[]},
    sup:()=>role==='supervisor',machines:[],tickets:[],duties:[],users:[],
    selectOptions:()=>'',renderTickets:()=>{},renderMachines:()=>{},renderDuties:()=>{},renderUsers:()=>{},
    view:'tickets',factoryType:'cnc',engineerRequest:0,selected:0,activePart:0,
    escapeHTML:String,currentView:'equipment',loadCatalog:async()=>{},switchView:()=>{},toast:message=>{throw Error(message)},
    api:async path=>{
      calls.push(path);
      return path.startsWith('/engineers?')?[{name:'New Engineer',score:100,reasons:['出勤：present'],
        method:'attendance_capacity_rules',breakdown:{skill:60,availability:40}}]:[];
    }
  });
  const consoleSource=fs.readFileSync('console.js','utf8');
  vm.runInContext(consoleSource.match(/async function refresh\(\)\{[^\n]+/)[0],context);
  await vm.runInContext('refresh()',context);
  assert(calls.includes('/tickets'));
  assert.equal(calls.includes('/duties'),role==='supervisor');
  assert.equal(calls.includes('/admin/users'),role==='supervisor');

  calls.length=0;
  const managementSource=fs.readFileSync('management.js','utf8');
  const startup=managementSource.split('\n').find(line=>line.startsWith('(async()=>{try{await loadCatalog();'));
  await vm.runInContext(startup,context);
  assert.equal(calls.includes('/personnel'),role==='supervisor');
  const personnelFunctions=managementSource.match(/async function personnelView\(\)\{[\s\S]*?\n\}/g);
  vm.runInContext(personnelFunctions.join('\n'),context);
  calls.length=0;
  await vm.runInContext('personnelView()',context);
  assert.equal(calls.includes('/personnel'),role==='supervisor');

  calls.length=0;
  const liveSource=fs.readFileSync('live.js','utf8');
  const start=liveSource.indexOf('renderEngineers=async function(){');
  vm.runInContext(liveSource.slice(start,liveSource.indexOf('\n};',start)+4),context);
  context.machines=[{id:'CNC-03',parts:[['主軸軸承']]}];
  await vm.runInContext('renderEngineers()',context);
  assert.equal(calls.some(path=>path.startsWith('/engineers?')),role==='supervisor');
  if(role==='engineer')assert(element('#engineers').innerHTML.includes('主管'));
  else{
    assert(element('#engineers').innerHTML.includes('New Engineer'));
    assert(!element('#engineers').innerHTML.includes('undefined'));
    assert(!element('#engineers').innerHTML.includes('案例'));
    assert(element('#engineers').innerHTML.includes('專長 60/60'));
    assert(element('#engineers').innerHTML.includes('可用性 40/40'));
  }
}

(async()=>{
  await checkRole('engineer');
  await checkRole('supervisor');
})().catch(error=>{console.error(error);process.exitCode=1});
