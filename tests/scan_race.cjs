'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

async function verifyStaleScan(action){
  const elements=new Map();
  const element=selector=>{
    if(!elements.has(selector))elements.set(selector,{value:'CNC-02',focus(){},scrollIntoView(){}});
    return elements.get(selector);
  };
  const context=vm.createContext({document:{querySelector:element,querySelectorAll:()=>[]},
    window:{authReady:Promise.resolve()},console});
  const source=fs.readFileSync(path.join(__dirname,'../scan.js'),'utf8');
  vm.runInContext(source.replace(/init\(\);\s*$/,''),context);
  vm.runInContext(`
    var replies=[],opened=[],rendered=[];
    prepare=async blob=>blob;
    api=()=>new Promise(resolve=>replies.push(resolve));
    renderResult=result=>rendered.push(result);
    loadMachine=async mid=>opened.push(mid);
    var pendingScan=scanBlob({});
  `,context);
  await Promise.resolve();
  await Promise.resolve();
  if(action==='manual')element('#manual-form').onsubmit({preventDefault(){}});
  else element('#scan-again').onclick();
  vm.runInContext("replies[0]({decision:'auto',candidates:[{machine_id:'CNC-01'}]})",context);
  await vm.runInContext('pendingScan',context);
  assert.equal(vm.runInContext('rendered.length',context),0,`${action}: stale OCR must not render`);
  if(action==='manual')assert.equal(vm.runInContext('opened[0]',context),'CNC-02');
}

(async()=>{
  await verifyStaleScan('manual');
  await verifyStaleScan('reset');
  console.log('Scan request race checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
