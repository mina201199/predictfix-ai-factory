let pageOffset = 0;
const pageSize = 100;
const notice = document.querySelector('#notice');

async function integrationApi(path, options = {}) {
  const response = await fetch('/api/integrations/' + path, {
    ...options,
    headers: { 'X-CSRF-Token': window.authCsrf, ...options.headers }
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '輸入格式不符，請檢查欄位');
  return result;
}

function line(container, title, details, action) {
  const row = document.createElement('article');
  row.className = 'integration-row';
  const heading = document.createElement('strong');
  heading.textContent = title;
  row.append(heading);
  for (const detail of details) {
    const paragraph = document.createElement('p');
    paragraph.textContent = detail;
    row.append(paragraph);
  }
  if (action) {
    const button = document.createElement('button');
    button.className = 'btn';
    button.textContent = action.label;
    button.addEventListener('click', () => perform(button, action.run));
    row.append(button);
  }
  container.append(row);
}

async function perform(button, operation) {
  button.disabled = true;
  notice.textContent = '';
  try {
    await operation();
    await refresh();
    notice.textContent = '已完成操作。';
  } catch (error) {
    notice.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function refresh() {
  const query = '?limit=' + pageSize + '&offset=' + pageOffset;
  const [mappings, records, events] = await Promise.all([
    integrationApi('mappings' + query), integrationApi('records' + query), integrationApi('outbox' + query)
  ]);
  for (const id of ['mapping-list', 'order-list', 'event-list', 'outbox-list']) document.getElementById(id).replaceChildren();
  for (const mapping of mappings) line(document.querySelector('#mapping-list'), mapping.source + ' / ' + mapping.machineCode, ['內部設備：' + mapping.machineId]);
  for (const order of records.orders) {
    const data = order.latestPayload;
    const reason = { unknown_machine_code: '機台代號尚未對應', mapped_machine_inactive: '對應設備已停用' }[order.reason] || '';
    line(document.querySelector('#order-list'), order.source + ' / ' + order.externalId + ' · v' + order.version,
      ['外部機台：' + order.machineCode + ' · ' + (order.ticketId || '待人工對應'),
        '症狀：' + data.symptoms + ' · 警報：' + data.alarm,
        '發生時間：' + data.occurredAt, reason].filter(Boolean),
      order.ticketId ? null : { label: '使用目前映射建立待指派工單', run: () => integrationApi('orders/' + order.id + '/resolve', { method: 'POST' }) });
  }
  for (const record of records.events) line(document.querySelector('#event-list'), record.source + ' / ' + record.eventId,
    ['接收時間：' + new Date(record.receivedAt * 1000).toLocaleString('zh-TW'), 'SHA256：' + record.payloadHash]);
  for (const record of events) line(document.querySelector('#outbox-list'), '#' + record.id + ' · ' + record.state + ' · ' + record.ticketId,
    ['事件：' + record.eventId + ' · 狀態：' + record.payload.status, '嘗試：' + record.attempts + ' · 最後錯誤：' + (record.lastError || '無'),
      '處理進度：' + (record.state === 'sent' ? '已完成回寫' : record.state === 'dead' ? '等待主管重試' :
        record.state === 'sending' ? '租約截止 ' + new Date(record.leaseUntil * 1000).toLocaleString('zh-TW') :
          record.nextAttempt ? new Date(record.nextAttempt * 1000).toLocaleString('zh-TW') : '待 worker 處理')],
    record.state === 'dead' ? { label: '重試此事件', run: () => integrationApi('outbox/' + record.id + '/retry', { method: 'POST' }) } : null);
  document.querySelector('#previous').disabled = pageOffset === 0;
  document.querySelector('#next').disabled = Math.max(mappings.length, records.orders.length, records.events.length, events.length) < pageSize;
  document.querySelector('#page-label').textContent = '第 ' + (pageOffset / pageSize + 1) + ' 頁（每區最多 100 筆）';
}

window.authReady.then(async user => {
  if (user.role !== 'supervisor') {
    notice.textContent = '此頁需要主管權限，請回維修管理頁處理工單。';
    return;
  }
  document.querySelector('#supervisor-content').hidden = false;
  try {
    const response = await fetch('/api/machines');
    if (!response.ok) throw new Error('無法載入設備');
    for (const machine of await response.json()) {
      const option = document.createElement('option');
      option.value = machine.id;
      option.textContent = machine.id + ' · ' + machine.name;
      document.querySelector('#machine-select').append(option);
    }
    await refresh();
  } catch (error) {
    notice.textContent = error.message;
  }
});

document.querySelector('#mapping-form').addEventListener('submit', event => {
  event.preventDefault();
  perform(event.submitter, () => integrationApi('mappings', { method: 'PUT',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(new FormData(event.target))) }));
});
document.querySelector('#csv-form').addEventListener('submit', event => {
  event.preventDefault();
  const source = new FormData(event.target).get('source');
  const file = document.querySelector('#csv-file').files[0];
  const dryRun = event.submitter.value !== 'import';
  perform(event.submitter, async () => {
    if (file.size > 262144) throw new Error('CSV 超過 256 KiB');
    const result = await integrationApi('csv?source=' + encodeURIComponent(source) + '&dryRun=' + dryRun,
      { method: 'POST', headers: { 'Content-Type': 'text/csv' }, body: file });
    document.querySelector('#csv-result').textContent = (result.dryRun ? '預覽結果（未保存）\n' : '已匯入結果\n') + result.rows.map(row =>
      '第 ' + row.row + ' 列：' + (row.ok ? row.result.state + ' / ' + (row.result.ticketId || '待對應') : row.status + ' / ' + row.error)).join('\n');
  });
});
document.querySelector('#refresh').addEventListener('click', event => perform(event.target, async () => {}));
document.querySelector('#previous').addEventListener('click', event => perform(event.target, async () => { pageOffset = Math.max(0, pageOffset - pageSize); }));
document.querySelector('#next').addEventListener('click', event => perform(event.target, async () => { pageOffset += pageSize; }));
