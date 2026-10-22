(() => {
  'use strict';
  if (document.getElementById('pf-agent')) return;
  const root = document.createElement('div');
  root.id = 'pf-agent';
  root.innerHTML = `
    <button class="agent-launch" type="button" aria-label="開啟維修 Agent" aria-expanded="false" aria-controls="agent-panel"><span aria-hidden="true">✦</span><span>維修助手</span></button>
    <section id="agent-panel" role="dialog" aria-labelledby="agent-title" hidden>
      <header class="agent-header"><div><small>VULKRION · AGENT</small><h2 id="agent-title">維修助手</h2><p>查知識、建工單、協助主管派工</p></div><button type="button" class="agent-close" aria-label="關閉維修助手">×</button></header>
      <div class="agent-notice">操作先確認，權限由系統檢查。維修建議須由人員核對。</div>
      <div class="agent-messages" role="log" aria-label="助手對話" aria-live="polite"></div>
      <div class="agent-status" role="status"></div>
      <form class="agent-form">
        <label class="agent-question-label" for="agent-question">告訴我遇到的問題或要做的事</label>
        <textarea id="agent-question" name="question" rows="2" maxlength="1200" required placeholder="例如：PF-INTERVIEW-DEMO 換刀卡住，先核對哪些資料？"></textarea>
        <div class="agent-actions"><button class="agent-clear" type="button">清除對話</button><a href="/workflow.html">維修流程 ↗</a><button class="agent-send" type="submit">傳送 ↑</button></div>
      </form>
    </section>`;
  document.body.append(root);
  const select = selector => root.querySelector(selector);
  const panel = select('#agent-panel');
  const launch = select('.agent-launch');
  const messages = select('.agent-messages');
  const form = select('.agent-form');
  const question = select('#agent-question');
  const status = select('.agent-status');
  let turns = [];
  let pending = null;
  let busy = false;
  let storageKey = '';
  let previousFocus = null;
  let lastCreatedTicketId = '';

  function textElement(tag, text, className = '') {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function save() {
    if (!storageKey) return;
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({turns: turns.slice(-20)}));
    } catch { /* 儲存空間受限時，當頁對話仍可使用。 */ }
  }

  function renderRag(container, rag) {
    container.append(textElement('small', rag.answer_method === 'grounded_paraphrase'
      ? `RAG · ${rag.model || '本機模型'} 白話整理 · 來源可查，建議需核對`
      : rag.answer_method === 'insufficient_evidence'
        ? '來源資訊不足 · 請補充資料後繼續追問'
      : rag.llm_used && rag.answer_method === 'llm_selected_verified_excerpts'
        ? `RAG · ${rag.model || '本機模型'} 已選段、引用已核對`
      : '檢索結果 · 未取得通過引用檢查的模型選段', 'agent-model'));
    for (const step of rag.steps || []) {
      const excerpt = document.createElement('details');
      excerpt.className = 'agent-source';
      excerpt.append(textElement('summary', `[${step.reference}] 模型選取原文（展開）`));
      excerpt.append(textElement('blockquote', step.quote));
      container.append(textElement('p', `[${step.reference}] ${step.quote.slice(0, 100)}${step.quote.length > 100 ? '…' : ''}`), excerpt);
    }
    for (const citation of rag.citations || []) {
      const detail = document.createElement('details');
      detail.className = 'agent-source';
      detail.append(textElement('summary', `[${citation.reference}] ${citation.title} · ${citation.version || ''}${citation.is_synthetic ? ' · 示範資料' : ''}`));
      detail.append(textElement('p', `${citation.section || ''} ${citation.line_start ? `· 行 ${citation.line_start}–${citation.line_end}` : ''}`));
      detail.append(textElement('p', citation.text || ''));
      if (/^\/api\/(knowledge\/manuals|cases)\/[A-Za-z0-9_-]+$/.test(citation.source_url || '')) {
        const link = textElement('a', '檢視來源紀錄 ↗');
        link.href = citation.source_url;
        link.target = '_blank';
        link.rel = 'noopener';
        detail.append(link);
      }
      container.append(detail);
    }
    for (const followUp of rag.follow_up || []) container.append(textElement('p', followUp, 'agent-followup'));
  }

  function addTurn(role, content, rag = null, remember = true) {
    const article = document.createElement('article');
    article.className = `agent-turn agent-${role}`;
    article.append(textElement('small', role === 'user' ? '你' : '維修助手'));
    article.append(textElement('p', content));
    if (rag) renderRag(article, rag);
    messages.append(article);
    if (remember) {
      turns.push({role, content, ...(rag ? {rag} : {})});
      turns = turns.slice(-20);
      save();
    }
    messages.scrollTop = messages.scrollHeight;
    return article;
  }

  function invalidatePending(message) {
    if (!pending) return;
    pending.card.querySelectorAll('button').forEach(button => button.disabled = true);
    pending.card.append(textElement('p', message, 'agent-followup'));
    pending = null;
  }

  function setBusy(value) {
    busy = value;
    select('.agent-send').disabled = value;
    select('.agent-clear').disabled = value;
    question.disabled = value;
    root.querySelectorAll('.agent-example').forEach(button => button.disabled = value);
    form.setAttribute('aria-busy', String(value));
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {...options, headers: {
      'Content-Type': 'application/json', 'X-CSRF-Token': window.authCsrf, ...(options.headers || {})
    }});
    const data = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? '登入已到期，請重新整理頁面後登入。'
      : typeof data.detail === 'string' ? data.detail : '資料格式不符，請補充或修正內容。');
    return data;
  }

  async function streamReply(payload, onEvent) {
    const response = await fetch('/api/agent/chat', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'Accept': 'application/x-ndjson',
        'X-CSRF-Token': window.authCsrf}, body: JSON.stringify(payload)});
    if (!response.ok) {
      const data = await response.json();
      throw new Error(response.status === 401 ? '登入已到期，請重新整理頁面後登入。'
        : typeof data.detail === 'string' ? data.detail : '無法取得回覆，請稍後重試。');
    }
    if (!response.body) throw new Error('瀏覽器未提供串流回覆，請重新整理後重試。');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let result = null;
    function consume(line) {
      if (!line.trim()) return;
      const event = JSON.parse(line);
      if (event.type === 'error') throw new Error(event.message);
      if (event.type === 'result') result = event.result;
      else onEvent(event);
    }
    try {
      while (true) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value, {stream: !done});
        let boundary;
        while ((boundary = buffer.indexOf('\n')) !== -1) {
          consume(buffer.slice(0, boundary));
          buffer = buffer.slice(boundary + 1);
        }
        if (done) break;
      }
      consume(buffer);
      if (!result) throw new Error('連線中斷，回答尚未完成，請重試。');
      return result;
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
  }

  function showProposal(proposal, article) {
    if (!['create_ticket', 'assign_ticket'].includes(proposal.tool)) return;
    const card = document.createElement('section');
    card.className = 'agent-proposal';
    card.append(textElement('h3', '待你確認 · 尚未執行'));
    const list = document.createElement('dl');
    for (const [label, value] of proposal.summary) {
      list.append(textElement('dt', label), textElement('dd', value));
    }
    card.append(list, textElement('p', '確認卡有效五分鐘；換頁或提出新要求後需重新產生。', 'agent-followup'));
    const confirm = textElement('button', '確認執行', 'agent-confirm');
    const cancel = textElement('button', '取消', 'agent-cancel');
    confirm.type = cancel.type = 'button';
    cancel.onclick = () => {
      invalidatePending('已取消，未送出操作。');
      addTurn('assistant', '已取消這份草稿，未送出操作。');
    };
    confirm.onclick = async () => {
      if (busy || pending?.proposal.id !== proposal.id) return;
      if (Date.now() / 1000 > proposal.expiresAt) {
        invalidatePending('確認卡已到期，請重新提出要求。');
        return;
      }
      setBusy(true);
      confirm.disabled = cancel.disabled = true;
      status.textContent = '正在送出已確認的操作…';
      try {
        // URL 與方法由固定工具表決定，不能採用模型產生的任意請求。
        const endpoint = proposal.tool === 'create_ticket' ? '/api/repair-flow/report'
          : `/api/tickets/${encodeURIComponent(proposal.ticketId)}/assign`;
        const result = await request(endpoint, {method: proposal.tool === 'create_ticket' ? 'POST' : 'PATCH',
          headers: {'Idempotency-Key': proposal.id}, body: JSON.stringify(proposal.payload)});
        invalidatePending('已確認並執行成功。');
        if (proposal.tool === 'create_ticket') lastCreatedTicketId = result.id;
        addTurn('assistant', `已${proposal.tool === 'create_ticket' ? '建立工單' : '完成派工'}：${result.id}\n設備：${result.machine}\n異常：${result.issue}\n負責人：${result.engineer}\n狀態：${result.status}`);
        if (proposal.tool === 'create_ticket') showExamples();
        status.textContent = '操作成功；到維修流程頁可查看最新工單。';
      } catch (error) {
        status.textContent = `${error.message} 請先到維修流程頁確認最新狀態，再重新提出要求。`;
        invalidatePending('未取得成功回應；請先確認工單狀態，避免重複操作。');
      } finally {
        setBusy(false);
      }
    };
    card.append(confirm, cancel);
    article.append(card);
    pending = {proposal, card};
    messages.scrollTop = messages.scrollHeight;
  }

  function setOpen(open) {
    if (open) previousFocus = document.activeElement;
    panel.hidden = !open;
    launch.setAttribute('aria-expanded', String(open));
    if (open) {
      question.focus();
      messages.scrollTop = messages.scrollHeight;
    }
    else (previousFocus?.isConnected ? previousFocus : launch).focus();
  }
  launch.onclick = () => setOpen(panel.hidden);
  select('.agent-close').onclick = () => setOpen(false);
  root.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) { event.preventDefault(); setOpen(false); }
  });
  question.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  select('.agent-clear').onclick = () => {
    invalidatePending('已清除對話。');
    turns = [];
    lastCreatedTicketId = '';
    messages.replaceChildren();
    status.textContent = '';
    save();
    welcome();
  };

  form.onsubmit = async event => {
    event.preventDefault();
    const message = question.value.trim();
    if (!message || busy) return;
    invalidatePending('已有新要求，此草稿已作廢。');
    const history = turns.slice(-6).map(turn => ({role: turn.role, content: turn.content.slice(0, 2000)}));
    addTurn('user', message);
    question.value = '';
    setBusy(true);
    const started = Date.now();
    let stage = '正在查找適用資料…';
    let firstTextMs = null;
    let preview = null;
    const updateStatus = () => { status.textContent = `${stage} · ${Math.floor((Date.now() - started) / 1000)} 秒`; };
    updateStatus();
    const timer = setInterval(updateStatus, 1000);
    try {
      const result = await streamReply({message, history}, event => {
        if (event.type === 'status') stage = event.message;
        if (event.type === 'partial') {
          if (firstTextMs === null) firstTextMs = Date.now() - started;
          if (!preview) preview = addTurn('assistant', '', null, false);
          preview.querySelector('p').textContent = event.text;
          stage = '建議陸續顯示中，完整回覆尚未完成';
          messages.scrollTop = messages.scrollHeight;
        }
        updateStatus();
      });
      preview?.remove();
      const article = addTurn('assistant', result.reply, result.rag);
      if (result.proposal) showProposal(result.proposal, article);
      status.textContent = `${result.execution?.llm_used ? result.execution.model || '本機模型'
        : ['needs_context', 'insufficient_detail', 'no_sources'].includes(result.execution?.reason)
          ? '請補充資訊' : '未完成模型整理'} · ${firstTextMs === null ? '' : `第一段 ${(firstTextMs / 1000).toFixed(1)} 秒 · `}完整 ${((Date.now() - started) / 1000).toFixed(1)} 秒`;
    } catch (error) {
      // 中斷的預覽不存進歷史，避免下一輪把未完成內容視為正式回答。
      preview?.remove();
      addTurn('assistant', `未完成這次請求：${error.message}`);
      status.textContent = '請檢查連線後重試。';
    } finally {
      clearInterval(timer);
      setBusy(false);
      if (!panel.hidden) question.focus();
    }
  };

  function welcome() {
    addTurn('assistant', '你好，選一道問題體驗，或直接輸入你的問題。回答會附上來源，也可以繼續追問。', null, false);
    showExamples();
  }

  function showExamples() {
    messages.querySelector('.agent-examples')?.remove();
    const examples = document.createElement('section');
    examples.className = 'agent-examples';
    examples.setAttribute('aria-label', '示範問題');
    examples.append(textElement('h3', '點選問題或操作，立即體驗'),
      textElement('p', '使用示範資料；建立工單、主管派工都會先出現確認卡。', 'agent-followup'));
    const questions = [
      ['換刀卡住，先查什麼？', 'PF-INTERVIEW-DEMO 新增刀具後，只有特定刀位卡住，先核對什麼？'],
      ['現場要記錄哪些資訊？', 'PF-INTERVIEW-DEMO 換刀卡住，現場要先記錄哪些資訊？'],
      ['刀具資料要核對哪些欄位？', 'PF-INTERVIEW-DEMO 換刀卡住，刀具資料要核對哪些欄位？'],
      ['建立工單', '請建立報修工單：設備 DEMO-INTERVIEW；機型 PF-INTERVIEW-DEMO；異常描述：特定刀位換刀卡住（面試示範）。請先產生草稿讓我確認。'],
      ['主管派工', () => {
        if (pending?.proposal.tool === 'create_ticket') {
          addTurn('assistant', '請先核對並確認目前的建立工單草稿。建立成功後，再點「主管派工」。');
          return '';
        }
        if (!lastCreatedTicketId) {
          addTurn('assistant', '請先點「建立工單」並確認建立成功，再點「主管派工」。若要派工既有工單，請直接輸入工單編號與工程師姓名；派工需要主管權限。');
          return '';
        }
        return `請準備派工草稿：工單編號 ${lastCreatedTicketId}；工程師姓名 INTERVIEW DEMO 工程師；派工原因：面試示範派工。請先讓我確認。`;
      }]
    ];
    for (const [label, prompt] of questions) {
      const button = textElement('button', label, 'agent-example');
      button.type = 'button';
      button.onclick = () => {
        if (busy) return;
        const message = typeof prompt === 'function' ? prompt() : prompt;
        if (!message) return;
        question.value = message;
        form.requestSubmit();
      };
      examples.append(button);
    }
    messages.append(examples);
    messages.scrollTop = messages.scrollHeight;
  }

  async function initialize() {
    let saved = {};
    try {
      if (window.crypto?.subtle) {
        const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(window.authCsrf));
        storageKey = 'pf-agent-' + Array.from(new Uint8Array(hash)).map(value => value.toString(16).padStart(2, '0')).join('');
      }
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith('pf-agent-') && key !== storageKey) sessionStorage.removeItem(key);
      }
      saved = storageKey ? JSON.parse(sessionStorage.getItem(storageKey) || '{}') : {};
      if (Array.isArray(saved.turns)) {
        turns = saved.turns.filter(turn => ['user', 'assistant'].includes(turn.role) && typeof turn.content === 'string').slice(-20);
        for (const turn of turns) addTurn(turn.role, turn.content, turn.rag, false);
      }
      if (turns.length) {
        addTurn('assistant', '已接續本次登入的對話。先前確認卡已作廢，要操作請重新提出要求。', null, false);
        showExamples();
      }
      else welcome();
    } catch {
      storageKey = '';
      if (!messages.children.length) welcome();
    }
  }
  initialize();
})();
