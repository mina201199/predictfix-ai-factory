"""新的未調參家族；沿用任務格式，但不把已看過的舊保留集重當盲測。"""
import json
from pathlib import Path

from build_selection_holdout import buildHoldout
from gemma_sft_protocol import validateHoldout

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = [
  ('mist-collector-link', '油霧收集器連線', '連線狀態碼', '集霧器面板畫面'),
  ('bar-loader-link', '棒材送料機交握', '送料批次編號', '交握紀錄時間'),
  ('conveyor-scale', '輸送帶秤重介面', '秤重顯示值', '傳送紀錄序號'),
  ('pallet-reader', '棧板識別讀取', '棧板標記編號', '讀取成功時間'),
  ('exhaust-damper', '排氣風門回授', '風門回授顯示值', '狀態變化截圖'),
  ('cooler-gateway', '冷卻機通訊閘道', '閘道事件編號', '面板最後連線時間'),
  ('sump-level-link', '集液槽液位連線', '液位顯示紀錄', '感測器識別碼'),
  ('magnetic-separator', '磁性分離機監視', '監視狀態畫面', '事件發生時間'),
  ('cabinet-light-link', '電箱照明監視', '照明狀態讀值', '端點識別編號'),
  ('air-dryer-gateway', '乾燥機通訊閘道', '乾燥機狀態碼', '最後接收時間'),
]


def buildRepairHoldout():
  data = buildHoldout(FAMILIES, seed=20261020)
  data['version'] = 'selection-holdout-v4-repair'
  for row in data['splits']['holdout']:
    row['id'] = row['id'].replace('holdout-', 'repair-holdout-', 1)
    row['source_group'] = row['source_group'].replace('holdout-', 'repair-holdout-', 1)
    row['question'] = row['question'].replace('PF-HO', 'PF-RE').replace('HO-', 'RE-')
    for paragraph in row['paragraphs']:
      paragraph['text'] = paragraph['text'].replace('PF-HO', 'PF-RE').replace('HO-', 'RE-')
  return data


if __name__ == '__main__':
  data = buildRepairHoldout()
  original = json.loads((ROOT / 'training/selection-dataset-v2.json').read_text(encoding='utf-8'))
  validateHoldout(data, original)
  target = ROOT / 'training/selection-holdout-v4-repair.json'
  with target.open('x', encoding='utf-8', newline='\n') as handle:
    json.dump(data, handle, ensure_ascii=False, indent=2)
    handle.write('\n')
  print(target)
