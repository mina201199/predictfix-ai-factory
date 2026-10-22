const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('agent-widget.js', 'utf8');
const implementation = source.slice(source.indexOf('  function showExamples('), source.indexOf('  async function initialize('));
function element(tag, text) {
  return {tag, text, children: [], setAttribute() {}, querySelector() { return null; }, append(...children) { this.children.push(...children); }};
}
const submitted = [];
const replies = [];
const context = vm.createContext({
  document: {createElement: element}, textElement: element,
  messages: element('div'), question: {value: ''}, busy: false, pending: null, lastCreatedTicketId: '',
  addTurn: (role, text) => replies.push(text)
});
context.form = {requestSubmit: () => submitted.push(context.question.value)};
vm.runInContext(implementation + '\nshowExamples();', context);
const buttons = context.messages.children[0].children.filter(child => child.tag === 'button');
const create = buttons.find(button => button.text === '建立工單');
const assign = buttons.find(button => button.text === '主管派工');
assign.onclick();
assert.equal(submitted.length, 0);
assert.match(replies.at(-1), /先點「建立工單」/);
create.onclick();
assert.match(submitted.at(-1), /建立報修工單.*DEMO-INTERVIEW.*異常描述：特定刀位換刀卡住/);
context.pending = {proposal: {tool: 'create_ticket'}};
assign.onclick();
assert.equal(submitted.length, 1);
assert.match(replies.at(-1), /確認目前的建立工單草稿/);
assert.ok(context.pending);
context.pending = null;
context.lastCreatedTicketId = 'WO-confirmed-demo';
assign.onclick();
assert.equal(submitted.at(-1), '請準備派工草稿：工單編號 WO-confirmed-demo；工程師姓名 INTERVIEW DEMO 工程師；派工原因：面試示範派工。請先讓我確認。');
context.busy = true;
create.onclick();
assign.onclick();
assert.equal(submitted.length, 2);
console.log('demo actions: missing ticket, pending confirmation, explicit ticket, busy guards passed');
