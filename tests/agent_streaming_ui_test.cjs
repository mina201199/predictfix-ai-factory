const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('agent-widget.js', 'utf8');
const implementation = source.slice(source.indexOf('  async function streamReply('), source.indexOf('  function showProposal('));
const encoder = new TextEncoder();
async function runStream(wire, expectFailure = false) {
  const bytes = encoder.encode(wire);
  let index = 0;
  let cancelled = false;
  let released = false;
  const received = [];
  const streamReply = vm.runInNewContext(implementation + '\nstreamReply;', {
    TextDecoder,
    window: {authCsrf: 'isolated-test-token'},
    fetch: async (url, options) => {
      assert.equal(url, '/api/agent/chat');
      assert.equal(options.headers.Accept, 'application/x-ndjson');
      assert.equal(options.headers['X-CSRF-Token'], 'isolated-test-token');
      return {ok: true, body: {getReader: () => ({
        async read() {
          // 每個位元組分開，驗證中文字元與事件邊界不依賴網路分包方式。
          if (index === bytes.length) return {done: true};
          return {done: false, value: bytes.slice(index, ++index)};
        },
        async cancel() { cancelled = true; },
        releaseLock() { released = true; }
      })}};
    }
  });
  if (expectFailure) {
    await assert.rejects(streamReply({message: 'test'}, event => received.push(event)));
  } else {
    const result = await streamReply({message: 'test'}, event => received.push(event));
    assert.equal(result.reply, '完成');
  }
  assert.ok(cancelled && released);
  assert.equal(received[0].text, '先核對刀位資料。');
}

(async () => {
  const partial = JSON.stringify({type: 'partial', text: '先核對刀位資料。'}) + '\n';
  await runStream(partial + JSON.stringify({type: 'result', result: {reply: '完成'}}));
  await runStream(partial, true);
  await runStream(partial + JSON.stringify({type: 'error', message: '連線中斷'}) + '\n', true);
  console.log('streaming UI transport: 3 scenarios passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
