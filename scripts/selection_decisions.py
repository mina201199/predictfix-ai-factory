"""只監督受限生成需要決策的位置，避免格式與答案長度稀釋拒答錯誤。"""
from gemma_sft_protocol import nextTokens


def decisionPlan(choices, answer):
  if answer not in choices:
    raise ValueError('Gold answer is not a legal grammar path')
  decisions = []
  for position, target in enumerate(answer):
    allowed = sorted(nextTokens(choices, answer[:position]))
    if len(allowed) > 1:
      decisions.append({'position': position, 'allowed': allowed,
        'targetIndex': allowed.index(target)})
  if not decisions:
    raise ValueError('Grammar has no supervised decision')
  for index, item in enumerate(decisions):
    item['weight'] = 1.0 if index == 0 else 1.0 / (len(decisions) - 1)
  return decisions


def decisionLoss(model, hiddenStates, promptLength, plan, applySoftcap=False):
  import torch
  import torch.nn.functional as functional
  losses = []
  for item in plan:
    hidden = hiddenStates[0, promptLength + item['position'] - 1].to('cpu', model.lm_head.weight.dtype)
    logits = functional.linear(hidden, model.lm_head.weight[item['allowed']]).float()
    softcap = model.config.final_logit_softcapping
    if softcap and applySoftcap:
      logits = torch.tanh(logits / softcap) * softcap
    target = torch.tensor([item['targetIndex']], dtype=torch.long)
    losses.append(functional.cross_entropy(logits.unsqueeze(0), target) * item['weight'])
  return torch.stack(losses).sum()
