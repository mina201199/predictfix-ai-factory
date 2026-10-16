// 嚴格 CSP 不允許 style 屬性；這裡只把經過驗證的數字或色碼，透過 CSSOM 套到幾個特定的 data-* 屬性，不提供任意 CSS 的入口
(()=>{
  const number=/^-?\d+(\.\d+)?(e[+-]?\d+)?$/;
  const hexColor=/^#[0-9a-fA-F]{3,8}$/;
  const numbers=(value,count)=>{const parts=String(value).split(',');return parts.length===count&&parts.every(p=>number.test(p))?parts:null};
  // 原本 inline style 先生效、之後程式用 CSSOM 改寫（例如旋轉角度）才是最終值；這裡在 microtask 才執行，所以只補還沒被設定的屬性
  const setIfEmpty=(element,property,value)=>{if(!element.style.getPropertyValue(property))element.style.setProperty(property,value)};
  function apply(element){
    const data=element.dataset;
    if(data.width!==undefined&&number.test(data.width))setIfEmpty(element,'width',data.width+'%');
    const geometry=data.geom&&numbers(data.geom,6);
    if(geometry)['--x','--y','--z','--w','--h','--d'].forEach((property,i)=>setIfEmpty(element,property,geometry[i]+'px'));
    const position=data.pos&&numbers(data.pos,3);
    if(position)['--x','--y','--z'].forEach((property,i)=>setIfEmpty(element,property,position[i]+'px'));
    if(data.tint&&hexColor.test(data.tint))setIfEmpty(element,'--c',data.tint);
    if(data.rotate!==undefined&&number.test(data.rotate))setIfEmpty(element,'transform',`scale(1.45) rotateX(-17deg) rotateY(${data.rotate}deg)`);
    const gauge=data.gauge&&numbers(data.gauge,3);
    if(gauge){const [a,b,c]=gauge;setIfEmpty(element,'background',`conic-gradient(#c6514e 0 ${a}%,#d4a13c ${a}% ${b}%,#2b9477 ${b}% ${c}%,#a7b1b8 ${c}% 100%)`)}
  }
  const selector='[data-width],[data-geom],[data-pos],[data-tint],[data-rotate],[data-gauge]';
  const scan=root=>{if(root.matches(selector))apply(root);root.querySelectorAll(selector).forEach(apply)};
  new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node.nodeType===1)scan(node)})))
    .observe(document.documentElement,{childList:true,subtree:true});
  scan(document.documentElement);
})();
