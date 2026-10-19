const graphKinds = {
  machine_model: '機型', part: '零件', alarm: '警報碼', symptom: '症狀', fault: '故障',
  cause: '原因', inspect_step: '排查步驟', verify_step: '驗收步驟', manual_section: '手冊段落',
  case: '已發布案例', spare: '備品', qualification: '資格'
};
const graphRelations = {
  has_part: '具有零件', references: '來源記載關聯', possible_cause: '來源記載可能原因',
  inspect: '排查', verify: '驗收', requires_spare: '需要備品', requires_qualification: '需要資格'
};
let graphSources = [];

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function showMessage(message) {
  document.querySelector('#message').textContent = message;
}

async function graphRequest(path, body) {
  const response = await fetch('/api/graph/' + path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': window.authCsrf },
    body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '輸入不符合要求，請檢查欄位。');
  return data;
}

function localLink(url, text) {
  const link = element('a', text);
  if (url && url.startsWith('/') && !url.startsWith('//')) link.href = url;
  return link;
}

function citationView(citation) {
  const box = element('details');
  box.append(element('summary', `${citation.sourceId} · ${citation.section} · 版本 ${citation.version}${citation.isSynthetic ? ' · 合成資料' : ''}`));
  box.append(element('blockquote', citation.quote), localLink(citation.url, '開啟引用來源'));
  return box;
}

function renderResults(data) {
  const target = document.querySelector('#results');
  target.replaceChildren();
  target.append(element('h3', `有效路徑 ${data.paths.length} 條 · ${data.llmUsed ? '使用模型' : '未呼叫模型'}`));
  if (data.truncated) target.append(element('p', '結果已達限制，請縮小查詢。'));
  for (const unknown of data.unknown) target.append(element('p', unknown, 'muted'));
  for (const path of data.paths) {
    const card = element('article');
    card.append(element('p', path.nodes.map(node => `${graphKinds[node.kind]}：${node.label}`).join(' → '), 'path'));
    for (const relation of path.relations) {
      card.append(element('p', `${graphRelations[relation.relation]} · 核准者 ${relation.approvedBy} · ${relation.approvedAt}`));
      card.append(citationView(relation.citation));
    }
    const last = path.nodes.at(-1);
    if (last.catalogUrl) card.append(localLink(last.catalogUrl, '查看備品／資格相關頁面（仍需核對適用性）'));
    target.append(card);
  }
  target.append(element('h3', '原字詞檢索來源'));
  for (const item of data.retrieval) {
    const card = element('article');
    card.append(localLink(item.source_url, `${item.title} · ${item.section} · ${item.version}`), element('pre', item.text));
    target.append(card);
  }
  if (!data.retrieval.length) target.append(element('p', '沒有符合機型的字詞檢索來源。'));
}

function sourceChanged() {
  const source = graphSources.find(item => item.chunkId === document.querySelector('#source').value);
  const models = document.querySelector('#source-model');
  models.replaceChildren();
  document.querySelector('#source-preview').textContent = source ? `${source.sourceType} · ${source.version}\n${source.text}` : '';
  document.querySelector('#quote').value = source ? source.text : '';
  document.querySelector('#source-link').removeAttribute('href');
  if (!source) return;
  document.querySelector('#source-link').href = source.url;
  for (const model of source.machineModels) {
    const option = element('option', model);
    option.value = model;
    models.append(option);
  }
}

async function refreshManagement() {
  const [sources, candidates] = await Promise.all([graphRequest('sources'), graphRequest('candidates')]);
  graphSources = sources;
  const selector = document.querySelector('#source');
  const previous = selector.value;
  selector.replaceChildren();
  for (const source of sources.filter(item => item.machineModels.length)) {
    const option = element('option', `${source.title} / ${source.section} / ${source.version}${source.isSynthetic ? '（合成）' : ''}`);
    option.value = source.chunkId;
    selector.append(option);
  }
  if (sources.some(source => source.chunkId === previous)) selector.value = previous;
  sourceChanged();
  const target = document.querySelector('#candidates');
  target.replaceChildren();
  for (const relation of candidates) {
    const card = element('article');
    card.append(element('h3', `${relation.head.label} → ${graphRelations[relation.relation]} → ${relation.tail.label}`));
    card.append(element('p', `${relation.machineModel} · ${relation.status} · r${relation.revision} · 來源${relation.sourceValid ? '有效' : '失效'} · 建立者 ${relation.createdBy}`));
    if (!relation.identityValid) card.append(element('p', relation.identityIssue));
    card.append(citationView(relation.citation));
    if (relation.reviewedBy) card.append(element('p', `最近審查 ${relation.reviewedBy} · ${relation.reviewedAt} · ${relation.reviewNote}`));
    const noteLabel = element('label', '核對／撤回理由');
    const note = element('input');
    note.minLength = 3;
    note.maxLength = 1000;
    noteLabel.append(note);
    card.append(noteLabel);
    for (const [action, label] of [['approve', '核對並核准'], ['withdraw', '撤回關係']]) {
      const button = element('button', label);
      button.type = 'button';
      button.disabled = action === 'approve' && (!relation.sourceValid || !relation.identityValid);
      button.addEventListener('click', async () => {
        if (note.value.trim().length < 3) return showMessage('請填寫至少 3 字的核對理由。');
        button.disabled = true;
        try {
          await graphRequest(`relations/${relation.id}/review`, { revision: relation.revision, action, note: note.value });
          await refreshManagement();
          showMessage('審查已保存；請重新查詢有效路徑。');
        } catch (error) { showMessage(error.message); button.disabled = false; }
      });
      card.append(button);
    }
    target.append(card);
  }
  if (!candidates.length) target.append(element('p', '目前沒有候選。可從結構化來源建立，或指定手冊原文。'));
}

document.querySelector('#query-form').addEventListener('submit', async event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.target));
  event.submitter.disabled = true;
  try {
    renderResults(await graphRequest('assist', { ...values, maxHops: Number(values.maxHops), useGraph: values.useGraph === 'true' }));
    showMessage('查詢完成；請核對各步來源與適用機型。');
  } catch (error) { showMessage(error.message); }
  finally { event.submitter.disabled = false; }
});

document.querySelector('#candidate-form').addEventListener('submit', async event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.target));
  event.submitter.disabled = true;
  try {
    const result = await graphRequest('candidates', { sourceChunkId: values.sourceChunkId, machineModel: values.machineModel,
      head: { kind: values.headKind, label: values.headLabel }, tail: { kind: values.tailKind, label: values.tailLabel },
      relation: values.relation, quote: values.quote });
    await refreshManagement();
    showMessage(result.status === 'candidate' ? '候選已保存，尚未發布給工程師。' : `相同來源關係已存在，目前狀態：${result.status}。`);
  } catch (error) { showMessage(error.message); }
  finally { event.submitter.disabled = false; }
});

document.querySelector('#source').addEventListener('change', sourceChanged);
document.querySelector('#refresh').addEventListener('click', () => refreshManagement().catch(error => showMessage(error.message)));
document.querySelector('#rebuild').addEventListener('click', async event => {
  event.target.disabled = true;
  try {
    const result = await graphRequest('rebuild', {});
    await refreshManagement();
    showMessage(`新增 ${result.created} 條待核對候選。${result.notice}`);
  } catch (error) { showMessage(error.message); }
  finally { event.target.disabled = false; }
});

for (const selector of ['#head-kind', '#tail-kind', '#relation']) {
  for (const [value, label] of Object.entries(selector === '#relation' ? graphRelations : graphKinds)) {
    const option = element('option', label);
    option.value = value;
    document.querySelector(selector).append(option);
  }
}
document.querySelector('#head-kind').value = 'alarm';
document.querySelector('#tail-kind').value = 'part';
document.querySelector('#relation').value = 'references';
window.authReady.then(async user => {
  if (user.role === 'supervisor') {
    document.querySelector('#management').hidden = false;
    try { await refreshManagement(); } catch (error) { showMessage(error.message); }
  }
});
