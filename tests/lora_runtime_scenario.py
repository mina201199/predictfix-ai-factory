import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'

import torch
from peft import LoraConfig, PeftModel, get_peft_model
from transformers import AutoModelForCausalLM, Qwen3Config

parser = argparse.ArgumentParser()
parser.add_argument('--report', type=Path, required=True)
args = parser.parse_args()
if args.report.exists():
  raise FileExistsError('Report already exists; choose a fresh output path')
torch.set_num_threads(2)


def freshModel():
  torch.manual_seed(42)
  config = Qwen3Config(vocab_size=64, hidden_size=32, intermediate_size=64,
    num_hidden_layers=1, num_attention_heads=2, num_key_value_heads=2, head_dim=16,
    max_position_embeddings=32, use_cache=False)
  return AutoModelForCausalLM.from_config(config)


model = get_peft_model(freshModel(), LoraConfig(r=4, lora_alpha=8, target_modules=['q_proj', 'v_proj'],
  lora_dropout=0.0, bias='none', task_type='CAUSAL_LM'))
model.gradient_checkpointing_enable()
model.enable_input_require_grads()
model.train()
inputs = torch.tensor([[1, 2, 3, 4, 5, 6]])
labels = inputs.clone()
labels[:, :3] = -100
parameters = [parameter for parameter in model.parameters() if parameter.requires_grad]
optimizer = torch.optim.AdamW(parameters, lr=0.001)
loss = model(input_ids=inputs, labels=labels).loss
assert torch.isfinite(loss)
loss.backward()
assert any(parameter.grad is not None and torch.count_nonzero(parameter.grad) for parameter in parameters)
assert all(parameter.grad is None or torch.isfinite(parameter.grad).all() for parameter in parameters)
torch.nn.utils.clip_grad_norm_(parameters, 1.0)
optimizer.step()
model.gradient_checkpointing_disable()
model.eval()
with torch.no_grad():
  before = model(input_ids=inputs).logits
with tempfile.TemporaryDirectory(prefix='safe-adapter-', dir=args.report.parent) as folder:
  model.save_pretrained(folder, safe_serialization=True)
  assert (Path(folder) / 'adapter_model.safetensors').exists()
  restored = PeftModel.from_pretrained(freshModel(), folder)
  restored.eval()
  with torch.no_grad():
    after = restored(input_ids=inputs).logits
  assert torch.allclose(before, after, atol=1e-6), torch.max(torch.abs(before - after)).item()
report = {'device':'cpu', 'scope':'Random tiny Qwen3 CPU fixture; no pretrained weights or model quality claim',
  'optimizerSteps':1, 'finiteLoss':float(loss.detach()), 'finiteGradients':True, 'adapterReloadMatches':True,
  'versions':{name:importlib.metadata.version(name) for name in ['torch', 'transformers', 'peft', 'accelerate', 'setuptools']}}
args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
