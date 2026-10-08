"""Publish only recorded experiment results inside the README's managed block."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
START='<!-- experiment-results:start -->'
END='<!-- experiment-results:end -->'


def pct(value):return f'{value*100:.1f}%'


def main():
    deployment=json.loads((ROOT/'artifacts/local-deployment-report.json').read_text(encoding='utf-8'))
    training=json.loads((ROOT/'artifacts/lora-training-report.json').read_text(encoding='utf-8'))
    content=[
      f'**本機部署：{deployment["status"]}。** 正式資料模式已在 `{deployment["url"]}` 運行，採獨立資料庫與具有檔案雜湊的版本快照。',
      '',
      '已驗證登入與主管權限、匿名阻擋、關閉快速登入、重啟後帳號保存，以及 SQLite 備份／新庫還原與工作階段撤銷。尚未部署公網，Docker／PostgreSQL／HTTPS 未完成實測。',
      '',
      '**LoRA 任務：根據報修問題與候選原文，選取相關段落 ID；無依據時輸出空清單。** 資料為 44 題原創虛構案例，按來源主題分組，訓練／驗證／測試為 24／8／12 題。',
      '',f'實驗狀態：`{training["status"]}`；模型：`{training["base_model"]}`；run：`{training["run_id"]}`。',''
    ]
    if training['status']=='completed':
        content += ['| 同一組 12 題來源主題保留測試 | 原模型 | LoRA 模型 |',
                    '|---|---:|---:|']
        before=training['base_test']['metrics'];after=training['lora_test']['metrics']
        for key,label in [('exact_match','段落集合完全符合'),('precision','選取 Precision'),('recall','選取 Recall'),
                          ('valid_output_rate','合法輸出'),('no_answer_accuracy','資料不足判斷'),
                          ('injection_exact_match','文件注入題正確選取')]:
            content.append(f'| {label} | {pct(before[key])} | {pct(after[key])} |')
        content.append(f'| 平均生成耗時（CPU） | {before["mean_latency_seconds"]:.2f} 秒 | {after["mean_latency_seconds"]:.2f} 秒 |')
        lora=training['lora']
        content += ['',f'CPU float32、LoRA rank {lora["rank"]}、q_proj/v_proj、batch 1，共 {lora["steps"]} 步；僅訓練 {lora["trainable_parameters"]:,} 個參數。訓練耗時 {training["training_seconds"]:.1f} 秒。',
                    '',f'Exact match 變化：**{training["delta_exact_match"]*100:+.1f} 個百分點**。這是小規模流程實驗，不能證明現場維修成效；訓練 loss、逐題原始輸出、版本與雜湊均保存。',
                    '', '本實驗使用 Transformers、無 JSON grammar，嚴格拒絕 Markdown 包住的 JSON；現有 llama.cpp 服務有格式約束，這些數字不等於線上服務正確率。生成耗時也受回答長度影響。',
                    '', '**目前保留原服務模型，未自動替換。** 此 adapter 尚未完成量化部署、安全回歸與專家評估。']
        failures=[r for r in training['lora_test']['results'] if r['kind']=='no_answer' and not r['exact']]
        if failures:
            content += ['',f'**失敗分析：{len(failures)} 題資料不足題未正確拒答。** 例如輸出 `{failures[0]["raw_output"]}`，包含不存在的段落 ID；仍須由後端拒絕與降級。此結果尚不符合替換現有模型的條件。']
    elif training['status']=='failed':
        content += [f'本次訓練未完成：`{training.get("error_type","unknown")}`。報告保留失敗原因與已完成的階段；不填入未執行的成效數字。']
    serving_path=ROOT/'artifacts/lora-serving-report.json'
    if serving_path.exists():
        serving=json.loads(serving_path.read_text(encoding='utf-8'))
        if serving['health']['run_id']==training['run_id'] and serving['status']=='deployed':
            content += ['',f'**adapter 推論服務已部署於 `{serving["url"]}`。** 已重新載入保存的權重，驗證同題原始輸出一致與錯誤輸入拒絕；這是獨立實驗 API，尚未接入正式維修流程。詳見 [推論部署報告](artifacts/lora-serving-report.json)。']
    content += ['', '[實驗方法與重跑](docs/lora-training.md) · [部署報告](artifacts/local-deployment-report.json) · [LoRA 完整報告](artifacts/lora-training-report.json) · [資料集](training/selection-dataset.json)']
    readme=ROOT/'README.md';text=readme.read_text(encoding='utf-8')
    assert text.count(START)==1 and text.count(END)==1
    left,rest=text.split(START,1);_,right=rest.split(END,1)
    readme.write_text(left+START+'\n'+'\n'.join(content)+'\n'+END+right,encoding='utf-8')
    print('README updated from recorded deployment and training results.')


if __name__=='__main__':main()
