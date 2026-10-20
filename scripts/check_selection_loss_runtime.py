"""CPU 決策 loss 檢查；高 common-mode 分數不能掩蓋錯誤決策。"""
import json
from types import SimpleNamespace


def checkRuntime():
  import torch
  from selection_decisions import decisionLoss, decisionPlan
  torch.set_num_threads(2)
  model = SimpleNamespace(lm_head=SimpleNamespace(weight=torch.eye(2)),
    config=SimpleNamespace(final_logit_softcapping=30.0))
  plan = decisionPlan([[0], [1]], [1])
  hidden = torch.tensor([[[176.0, 168.0]]], requires_grad=True)
  loss = decisionLoss(model, hidden, 1, plan)
  loss.backward()
  norm = float(hidden.grad.norm())
  # 尚未改正的分支不能靠共同推高兩個 logits 逃進 softcap 平坦區。
  assert norm > 1.0, f'Wrong decision lost its learning gradient: {norm}'
  shifted = torch.tensor([[[196.0, 188.0]]], requires_grad=True)
  shiftedLoss = decisionLoss(model, shifted, 1, plan)
  assert abs(float(loss.detach()) - float(shiftedLoss.detach())) < 1e-6
  assert abs(float(hidden.grad.sum())) < 1e-6
  assert hidden.grad[0, 0, 0] > 0 and hidden.grad[0, 0, 1] < 0
  print(json.dumps({'scope': 'CPU numeric gradient fixture, not official model quality',
    'wrongDecisionLoss': float(loss.detach()), 'gradientNorm': norm,
    'commonModeInvariant': True, 'gradientDirectionCorrect': True}))


if __name__ == '__main__':
  checkRuntime()
