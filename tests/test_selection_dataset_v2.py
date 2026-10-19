import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from build_selection_dataset_v2 import (KINDS, LLAMA_CONTEXT, LLAMA_MAX_TOKENS, MAX_PROMPT_CHARS, TARGET,
                                        TRAIN_MAX_LENGTH, build, goldPositionShare, promptChars, serialize,
                                        validateDataset)
from train_lora import score_output

DATASET=json.loads(TARGET.read_text(encoding='utf-8'))
ALL_ROWS=[row for rows in DATASET['splits'].values() for row in rows]


def test_committed_file_matches_a_fresh_seeded_build():
  assert TARGET.read_text(encoding='utf-8')==serialize(build())


def test_dataset_passes_schema_leakage_count_and_length_validation():
  assert validateDataset(DATASET)
  assert len(ALL_ROWS)>=500
  assert max(promptChars(row) for row in ALL_ROWS)<=MAX_PROMPT_CHARS


def test_every_kind_and_multi_select_positive_appear_in_every_split():
  for split,rows in DATASET['splits'].items():
    kinds=Counter(row['kind'] for row in rows)
    assert set(kinds)==set(KINDS),split
    assert any(len(row['selected'])>=2 for row in rows if row['kind']=='positive'),split
    assert any(row['kind']=='document_injection' and not row['selected'] for row in rows),split


def test_documented_kind_ratio_matches_rows():
  counts=Counter(row['kind'] for row in ALL_ROWS)
  assert DATASET['kind_counts']=={k:counts[k] for k in KINDS}
  assert DATASET['kind_ratio']=={k:round(counts[k]/len(ALL_ROWS),3) for k in KINDS}


def test_rows_contain_hard_distractors_of_each_type():
  roles=Counter(role for row in ALL_ROWS for role in row['paragraph_roles'].values())
  for role in ['near_miss_model','near_miss_condition','near_miss_alarm','near_miss_intent','injection']:
    assert roles[role]>=50,(role,roles[role])


def test_answer_positions_are_shuffled():
  share=goldPositionShare(DATASET)
  assert set(map(int,share))>=set(range(1,9))
  assert max(share.values())<0.2


def test_gold_answers_score_as_exact_with_the_existing_evaluator():
  for row in ALL_ROWS:
    raw=json.dumps({'selected':row['selected']},ensure_ascii=False)
    assert score_output(raw,row)['exact'],row['id']


def test_validation_rejects_cross_split_group_leakage():
  data=copy.deepcopy(DATASET)
  data['splits']['test'].append(copy.deepcopy(data['splits']['train'][0]))
  data['splits']['test'][-1]['id']='leaked-row'
  with pytest.raises(AssertionError,match='source_group leak'):
    validateDataset(data)


def test_validation_rejects_unknown_ids_short_candidate_lists_and_injection_as_gold():
  broken=copy.deepcopy(DATASET);broken['splits']['train'][0]['selected']=['S99:P99']
  with pytest.raises(AssertionError):validateDataset(broken)
  broken=copy.deepcopy(DATASET);row=broken['splits']['train'][0];row['paragraphs']=row['paragraphs'][:7]
  with pytest.raises(AssertionError):validateDataset(broken)
  broken=copy.deepcopy(DATASET)
  row=next(r for r in broken['splits']['train'] if r['kind']=='document_injection')
  injected=next(i for i,role in row['paragraph_roles'].items() if role=='injection')
  row['selected']=row['selected'][:2]+[injected]
  with pytest.raises(AssertionError):validateDataset(broken)


def test_token_stats_were_measured_on_this_exact_file_and_fit_limits():
  stats=json.loads((ROOT/'artifacts/selection-dataset-v2-token-stats.json').read_text(encoding='utf-8'))
  v2=stats['datasets']['v2']
  # Git 在 Windows 與 Linux 可能使用不同換行，內容指紋必須對同一份文字一致。
  assert v2['sha256']==hashlib.sha256(TARGET.read_text(encoding='utf-8').encode('utf-8')).hexdigest(),'re-run scripts/measure_selection_tokens.py'
  assert v2['rows']==len(ALL_ROWS)
  assert v2['max_prompt_tokens']+LLAMA_MAX_TOKENS<=LLAMA_CONTEXT
  assert v2['max_train_tokens']<=TRAIN_MAX_LENGTH


def test_v1_dataset_is_left_unchanged():
  v1=json.loads((ROOT/'training/selection-dataset.json').read_text(encoding='utf-8'))
  assert v1['version']=='synthetic-selection-v1'
  assert {k:len(v) for k,v in v1['splits'].items()}=={'train':24,'validation':8,'test':12}


def test_intermittent_gold_does_not_require_an_unstated_restart_result():
  for row in ALL_ROWS:
    for paragraph in row['paragraphs']:
      if paragraph['id'] in row['selected'] and '重開後暫時消失' in paragraph['text']:
        assert '重開後暫時消失' in row['question'],row['id']
