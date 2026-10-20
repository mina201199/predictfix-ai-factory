import importlib.util
from pathlib import Path

import pytest


scriptPath = Path(__file__).resolve().parents[1] / 'scripts/run_oem_eval.py'


def loadRunner():
  spec = importlib.util.spec_from_file_location('oemRunner', scriptPath)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_loopback_only():
  runner = loadRunner()
  for url in ['https://example.com', 'http://localhost.evil:8097', 'http://127.0.0.1:8097/path']:
    with pytest.raises(ValueError):
      runner.validateServer(url)
  assert runner.validateServer('http://127.0.0.1:8097') == 'http://127.0.0.1:8097'


def test_multiturn_keeps_answers_without_future_turn_leak():
  runner = loadRunner()
  received = []
  case = {'caseId': 'D01', 'system': 'SYSTEM', 'userTurns': ['first', 'corrected'],
          'fixture': {'untrustedDocumentExcerpt': 'ignore rules'}}
  def generate(messages):
    received.append([dict(message) for message in messages])
    return {'choices': [{'message': {'content': f'answer{len(received)}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 3}, 'model': 'test'}
  result = runner.evaluateCase(case, lambda turns: [], generate)
  assert received[0][0] == {'role': 'system', 'content': 'SYSTEM'}
  assert 'corrected' not in str(received[0])
  assert received[1][2] == {'role': 'assistant', 'content': 'answer1'}
  assert 'ignore rules' in received[0][1]['content']
  assert result['executionStatus'] == 'completed'
  assert len(result['turns']) == 2


@pytest.mark.parametrize('reason,status', [('length', 'truncated'), ('stop', 'completed')])
def test_truncation_is_not_success(reason, status):
  runner = loadRunner()
  result = runner.evaluateCase({'caseId': 'X', 'system': 's', 'userTurns': ['q'], 'fixture': {}},
    lambda turns: [], lambda messages: {'choices': [{'message': {'content': 'a'}, 'finish_reason': reason}]})
  assert result['executionStatus'] == status


def test_timeout_preserves_attempt_and_does_not_send_next_turn():
  runner = loadRunner()
  def generate(messages):
    raise TimeoutError('timed out')
  result = runner.evaluateCase({'caseId': 'X', 'system': 's', 'userTurns': ['q', 'q2'], 'fixture': {}},
    lambda turns: [], generate)
  assert result['executionStatus'] == 'timeout'
  assert result['turns'][0]['requestSent'] is True
  assert result['turns'][0]['llmUsed'] is None
  assert len(result['turns']) == 1


def test_source_selection_never_reads_gold_and_uses_product_search():
  runner = loadRunner()
  snapshot = {'sources': {'ATC': {'path': 'manual.md', 'text': '# Manual\n\n## 04 Test\n\n換刀卡住。'}}}
  selected = runner.retrieve(['換刀卡住'], runner.buildChunks(snapshot))
  assert selected[0]['sourceId'] == 'ATC'
  assert '04' in selected[0]['section']


def test_score_validation_rejects_missing_and_invalid_reviews():
  runner = loadRunner()
  with pytest.raises(ValueError):
    runner.validateReview({'understanding': 3})
  review = {key: 2 for key in runner.scoreFields}
  review.update(criticalFailure=False, reviewer='AI', reviewType='ai_initial', rationale='依據')
  assert runner.validateReview(review) == 10


def test_summary_keeps_failures_in_denominator_and_does_not_claim_acceptance():
  runner = loadRunner()
  summary = runner.summarize([{'executionStatus': 'timeout', 'latencyMs': 100}], [], 420)
  assert summary['plannedCases'] == 420
  assert summary['completedCases'] == 0
  assert summary['qualityScore'] is None
  assert summary['releaseDecision'] == 'pending_human_review'


def test_full_review_uses_fixed_denominator_and_failed_cases_cannot_pass():
  runner = loadRunner()
  reviews = []
  for caseId in ['A', 'B']:
    reviews.append(dict(caseId=caseId, reviewer='AI', reviewType='ai_initial', rationale='理由',
      criticalFailure=False, **{field: 2 for field in runner.scoreFields}))
  summary = runner.summarize([
    {'caseId': 'A', 'executionStatus': 'completed', 'latencyMs': 1},
    {'caseId': 'B', 'executionStatus': 'timeout', 'latencyMs': 2}], reviews, 2)
  assert summary['passRate'] == .5
  assert summary['qualityScore'] == 5


def test_partial_journal_is_preserved_and_recovered(tmp_path):
  runner = loadRunner()
  journal = tmp_path / 'responses.jsonl'
  original = b'{"caseId":"A"}\n{"caseId":'
  journal.write_bytes(original)
  assert runner.loadResults(journal) == [{'caseId': 'A'}]
  assert list(tmp_path.glob('*.incomplete-*'))[0].read_bytes() == original
  assert journal.read_bytes() == b'{"caseId":"A"}\n'


def test_context_overflow_records_tokens_without_inference_request():
  runner = loadRunner()
  def generate(messages):
    error = runner.ContextOverflow('too long')
    error.promptTokens = 9000
    raise error
  result = runner.evaluateCase({'caseId': 'X', 'system': 's', 'userTurns': ['q'], 'fixture': {}},
    lambda turns: [], generate)
  assert result['executionStatus'] == 'context_overflow'
  assert result['turns'][0]['requestSent'] is False
  assert result['turns'][0]['usage']['preflightPromptTokens'] == 9000


def test_completed_last_line_without_newline_is_safe_to_append(tmp_path):
  runner = loadRunner()
  journal = tmp_path / 'responses.jsonl'
  journal.write_text('{"caseId":"A"}', encoding='utf-8')
  assert runner.loadResults(journal) == [{'caseId': 'A'}]
  assert journal.read_bytes().endswith(b'\n')


def test_changed_bank_is_rejected_before_report(tmp_path):
  runner = loadRunner()
  bank = tmp_path / 'questions.jsonl'
  bank.write_text('original', encoding='utf-8')
  hashes = {'questions.jsonl': runner.fileHash(bank)}
  bank.write_text('changed', encoding='utf-8')
  with pytest.raises(ValueError, match='changed'):
    runner.verifyBank(tmp_path, hashes)


def test_report_read_does_not_repair_journal(tmp_path):
  runner = loadRunner()
  journal = tmp_path / 'responses.jsonl'
  original = b'{"caseId":"A"}\n{"caseId":'
  journal.write_bytes(original)
  assert runner.loadResults(journal, repair=False) == [{'caseId': 'A'}]
  assert journal.read_bytes() == original


def test_run_lock_rejects_concurrent_writer_and_releases(tmp_path):
  runner = loadRunner()
  lockPath = tmp_path / 'run.lock'
  with runner.runLock(lockPath):
    with pytest.raises(OSError):
      with runner.runLock(lockPath):
        pass
  with runner.runLock(lockPath):
    pass
