"""使用離線官方 tokenizer 檢查所有固定列，不載入模型或使用 GPU。"""
import argparse
from pathlib import Path

from gemma_sft_protocol import MODEL_REVISION, grammarAnswers, textHash, validateManifest
from run_gemma_sft import DATASET, HOLDOUT, PROTOCOL, encodeExample, readJson, resolveRows, writeJson


def audit(runtimeDir, reportPath):
  from transformers import AutoTokenizer
  if reportPath.exists():
    raise FileExistsError('Choose a new report path')
  snapshot = runtimeDir / 'hf-cache/models--google--gemma-4-E2B-it/snapshots' / MODEL_REVISION
  tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
  manifest = readJson(PROTOCOL)
  validateManifest(manifest, DATASET, HOLDOUT)
  report = {'protocol_sha256': textHash(PROTOCOL), 'model_revision': MODEL_REVISION,
    'scope': 'Offline official tokenizer only; no model training or inference', 'splits': {}}
  for split in ['train', 'validation', 'holdout']:
    records = []
    for row in resolveRows(manifest, split):
      ids, labels = encodeExample(tokenizer, row, manifest['sequence_cap'])
      sequences = [tokenizer.encode(answer, add_special_tokens=False) for answer in grammarAnswers(row)]
      longest = max(map(len, sequences))
      if longest > manifest['max_new_tokens']:
        raise ValueError(f'Grammar answer exceeds decoding cap: {row["id"]}')
      for answer, sequence in zip(grammarAnswers(row), sequences):
        if tokenizer.decode(sequence, skip_special_tokens=False) != answer:
          raise ValueError(f'Grammar round trip mismatch: {row["id"]}')
      records.append({'id': row['id'], 'sequence_tokens': len(ids),
        'supervised_tokens': sum(value != -100 for value in labels), 'max_grammar_tokens': longest})
    report['splits'][split] = {'rows': len(records), 'sequence_tokens': sum(r['sequence_tokens'] for r in records),
      'supervised_tokens': sum(r['supervised_tokens'] for r in records),
      'max_sequence_tokens': max(r['sequence_tokens'] for r in records),
      'max_grammar_tokens': max(r['max_grammar_tokens'] for r in records), 'records': records}
  writeJson(reportPath, report)
  print({split: {k: v for k, v in stats.items() if k != 'records'} for split, stats in report['splits'].items()})


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--runtime-dir', type=Path, required=True)
  parser.add_argument('--report', type=Path, required=True)
  args = parser.parse_args()
  audit(args.runtime_dir.resolve(), args.report)
