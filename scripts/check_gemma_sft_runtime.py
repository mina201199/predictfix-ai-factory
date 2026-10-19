"""獨立訓練環境的 CPU 小模型整合驗證；不能替代官方權重或 GPU 實測。"""
import argparse
import json
import tempfile
from pathlib import Path

from gemma_sft_protocol import grammarAnswers, nextTokens, verifyReload
from run_gemma_sft import (adapterEvidence, encodeExample, forwardText,
  generateConstrained, initializeAdapter, writeJson)
from prepare_lora_data import prompt


class ByteTokenizerFixture:
  def encode(self, value, **kwargs):
    return [value + 3 for value in value.encode('utf-8')]

  def decode(self, ids, **kwargs):
    return bytes(value - 3 for value in ids).decode('utf-8')

  def apply_chat_template(self, messages, **kwargs):
    prefix = [2] + self.encode(messages[0]['content'] + '\nassistant\n')
    return {'input_ids': prefix if len(messages) == 1 else prefix + self.encode(messages[1]['content']) + [1]}


def referenceGenerate(model, tokenizer, row):
  import torch
  promptIds = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt(row)}])['input_ids']
  choices = [tokenizer.encode(answer) for answer in grammarAnswers(row)]
  prefix = []
  model.eval()
  with torch.inference_mode():
    while prefix not in choices:
      allowed = sorted(nextTokens(choices, prefix))
      if len(allowed) == 1:
        token = allowed[0]
      else:
        output = forwardText(model, promptIds + prefix, cache=False)
        logits = model.lm_head(output.last_hidden_state[:, -1]).float()[0]
        token = allowed[int(logits[allowed].argmax())]
      prefix.append(token)
  return tokenizer.decode(prefix)


def checkRuntime(outputPath):
  import torch
  from peft import PeftModel
  from transformers import Gemma4ForCausalLM
  from check_qlora_feasibility import addLora, tinyConfig
  torch.set_num_threads(2)
  def freshModel(dtype=torch.float32):
    torch.manual_seed(123)
    return Gemma4ForCausalLM(tinyConfig()).to(dtype)
  tokenizer = ByteTokenizerFixture()
  row = {'id': 'cpu-fixture', 'question': 'fixture?', 'paragraphs': [
    {'id': 'A', 'text': 'fixture'}, {'id': 'B', 'text': 'other'}], 'selected': ['A']}
  manifest = {'max_new_tokens': 64}
  model = freshModel()
  wrapped, metadata = addLora(model, 8)
  initialHash = initializeAdapter(model, 20261019)
  other = freshModel(torch.float16)
  otherWrapped, _ = addLora(other, 8)
  if initializeAdapter(other, 20261019) != initialHash:
    raise AssertionError('Initial adapter depends on base dtype')
  del otherWrapped, other
  ids, labels = encodeExample(tokenizer, row, 1024)
  output = forwardText(model, ids, cache=False)
  labels = torch.tensor(labels[1:])
  positions = (labels != -100).nonzero().squeeze(1)
  logits = model.lm_head(output.last_hidden_state[0, positions])
  softcap = model.config.final_logit_softcapping
  logits = torch.tanh(logits / softcap) * softcap
  loss = torch.nn.functional.cross_entropy(logits, labels[positions])
  optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=0.0002)
  loss.backward()
  optimizer.step()
  with tempfile.TemporaryDirectory(prefix='gemma-cpu-selfcheck-') as folder:
    adapterDir = Path(folder) / 'adapter'
    wrapped.save_pretrained(adapterDir, safe_serialization=True)
    before = adapterEvidence(model, tokenizer, row, adapterDir, manifest)
    cached = generateConstrained(model, tokenizer, row, 64)['raw']
    reference = referenceGenerate(model, tokenizer, row)
    if cached != reference:
      raise AssertionError('Chunked cached decoding differs from full-prefix reference')
    restored = freshModel()
    restoredWrapped = PeftModel.from_pretrained(restored, adapterDir, is_trainable=True)
    after = adapterEvidence(restored, tokenizer, row, adapterDir, manifest)
    reloadResult = verifyReload(before, after)
  result = {'scope': 'Random tiny Gemma4 CPU fixture only; not pretrained SFT or GPU evidence',
    'device': 'cpu', 'loss': float(loss.detach()), 'optimizer_steps': 1,
    'initial_adapter_same_across_fp16_fp32_bases': True,
    'chunked_cache_matches_full_prefix': True, 'reload': reloadResult,
    'initial_adapter_sha256': initialHash, 'trainable_parameters': metadata['trainable_parameters'],
    'before': before, 'after': after}
  if Path(outputPath).exists():
    raise FileExistsError('Report already exists; choose a fresh output path')
  writeJson(outputPath, result)
  print(json.dumps({key: value for key, value in result.items() if key not in ['before', 'after']}, indent=2))


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--report', type=Path, required=True)
  checkRuntime(parser.parse_args().report)
