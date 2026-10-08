"""CPU LoRA experiment: actual generated outputs, unchanged prompts, held-out source groups."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import sys
import time
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_lora_data import prompt, validate


def score_output(raw,row):
    try:
        parsed=json.loads(raw.strip())
        selected=parsed['selected']
        valid=(set(parsed)=={'selected'} and isinstance(selected,list) and len(selected)<=4
               and all(isinstance(x,str) for x in selected) and len(set(selected))==len(selected)
               and set(selected)<={p['id'] for p in row['paragraphs']})
    except (ValueError,KeyError,TypeError):
        valid=False;selected=[]
    predicted=set(selected) if valid else set()
    expected=set(row['selected'])
    return {'valid':valid,'selected':selected,'exact':valid and predicted==expected,
            'tp':len(predicted&expected),'fp':len(predicted-expected),'fn':len(expected-predicted)}


def summarize(results):
    tp=sum(r['tp'] for r in results);fp=sum(r['fp'] for r in results);fn=sum(r['fn'] for r in results)
    n=len(results)
    negatives=[r for r in results if r['kind']=='no_answer']
    attacks=[r for r in results if r['kind']=='document_injection']
    return {'count':n,'exact_match':sum(r['exact'] for r in results)/n,
            'valid_output_rate':sum(r['valid'] for r in results)/n,
            'precision':tp/(tp+fp) if tp+fp else 0,'recall':tp/(tp+fn) if tp+fn else 0,
            'no_answer_accuracy':sum(r['exact'] for r in negatives)/len(negatives),
            'injection_exact_match':sum(r['exact'] for r in attacks)/len(attacks),
            'mean_latency_seconds':sum(r['latency_seconds'] for r in results)/n}


def run(args,report,path):
    import torch
    import psutil
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model
    torch.set_num_threads(args.threads)
    torch.manual_seed(42);random.seed(42)
    dataset_path=ROOT/'training/selection-dataset.json'
    data=json.loads(dataset_path.read_text(encoding='utf-8'));validate(data)
    report['dataset']={'sha256':hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                       'counts':{k:len(v) for k,v in data['splits'].items()},
                       'scope':data['scope'],'split_method':data['split_method']}
    report['environment']={'python':sys.version.split()[0],
        'packages':{p:importlib.metadata.version(p) for p in ['torch','transformers','peft','accelerate']},
        'device':'cpu','ram_total_bytes':psutil.virtual_memory().total,'threads':args.threads}
    tokenizer=AutoTokenizer.from_pretrained(args.model,cache_dir=ROOT/'.runtime/hf-cache',revision=args.revision)
    model=AutoModelForCausalLM.from_pretrained(args.model,cache_dir=ROOT/'.runtime/hf-cache',revision=args.revision,
        dtype=torch.float32,low_cpu_mem_usage=True,attn_implementation='sdpa')
    report['model_revision']=getattr(model.config,'_commit_hash',None)
    report['dtype']='float32';report['decoding']={'do_sample':False,'max_new_tokens':32,'grammar_constraints':False}
    def persist():
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    def tokens(row,answer=None):
        messages=[{'role':'user','content':prompt(row)}]
        if answer is not None:messages.append({'role':'assistant','content':answer})
        text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=answer is None,enable_thinking=False)
        batch=tokenizer(text,return_tensors='pt')
        if batch['input_ids'].shape[1]>args.max_length:
            raise ValueError('Sequence exceeds max_length; never silently truncate labels or candidate paragraphs.')
        return batch
    def evaluate(rows,label):
        model.eval();outputs=[]
        for row in rows:
            batch=tokens(row);start=time.perf_counter()
            with torch.inference_mode():
                generated=model.generate(**batch,do_sample=False,max_new_tokens=32,
                                         pad_token_id=tokenizer.eos_token_id)
            raw=tokenizer.decode(generated[0,batch['input_ids'].shape[1]:],skip_special_tokens=True)
            result={**score_output(raw,row),'id':row['id'],'kind':row['kind'],'expected':row['selected'],
                    'raw_output':raw,'latency_seconds':round(time.perf_counter()-start,4)}
            outputs.append(result)
            print(f'{label} {row["id"]}: exact={result["exact"]} raw={raw!r}',flush=True)
        return {'metrics':summarize(outputs),'results':outputs}
    report['status']='baseline_evaluation';persist()
    # Validation is used for inspection; test results do not select checkpoints or hyperparameters.
    report['base_validation']=evaluate(data['splits']['validation'],'base-validation');persist()
    report['base_test']=evaluate(data['splits']['test'],'base-test');persist()
    config=LoraConfig(r=4,lora_alpha=8,lora_dropout=0.05,target_modules=['q_proj','v_proj'],task_type='CAUSAL_LM',bias='none')
    model=get_peft_model(model,config)
    model.config.use_cache=False
    trainable=[p for p in model.parameters() if p.requires_grad]
    report['lora']={'rank':4,'alpha':8,'dropout':0.05,'target_modules':['q_proj','v_proj'],
                    'trainable_parameters':sum(p.numel() for p in trainable),
                    'total_parameters':sum(p.numel() for p in model.parameters()),
                    'learning_rate':args.learning_rate,'steps':args.steps,'batch_size':1,'max_length':args.max_length}
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
    model.enable_input_require_grads()
    optimizer=torch.optim.AdamW(trainable,lr=args.learning_rate)
    train=data['splits']['train'].copy();random.shuffle(train)
    report['status']='training';report['training_log']=[];persist()
    start=time.perf_counter();model.train()
    for step in range(args.steps):
        row=train[step%len(train)]
        answer=json.dumps({'selected':row['selected']},ensure_ascii=False,separators=(',',':'))
        batch=tokens(row,answer)
        prompt_ids=tokens(row)['input_ids']
        prefix=prompt_ids.shape[1]
        assert torch.equal(batch['input_ids'][:,:prefix],prompt_ids), 'Chat template prefix mismatch'
        labels=batch['input_ids'].clone();labels[:,:prefix]=-100
        assert (labels!=-100).sum()>0
        optimizer.zero_grad(set_to_none=True)
        loss=model(**batch,labels=labels).loss
        if not torch.isfinite(loss):raise RuntimeError('Non-finite training loss')
        loss.backward();torch.nn.utils.clip_grad_norm_(trainable,1.0);optimizer.step()
        record={'step':step+1,'example_id':row['id'],'loss':round(loss.item(),6),
                'elapsed_seconds':round(time.perf_counter()-start,3),
                'process_rss_bytes':psutil.Process().memory_info().rss}
        report['training_log'].append(record);persist();print(json.dumps(record),flush=True)
    output=ROOT/'.runtime/lora-runs'/args.run_id/'adapter'
    output.mkdir(parents=True,exist_ok=True)
    model.save_pretrained(output);tokenizer.save_pretrained(output)
    report['adapter_path']=str(output.relative_to(ROOT)).replace('\\','/')
    report['adapter_sha256']=hashlib.sha256((output/'adapter_model.safetensors').read_bytes()).hexdigest()
    report['training_seconds']=round(time.perf_counter()-start,3)
    model.config.use_cache=True;model.gradient_checkpointing_disable()
    report['status']='adapter_evaluation';persist()
    report['lora_validation']=evaluate(data['splits']['validation'],'lora-validation');persist()
    report['lora_test']=evaluate(data['splits']['test'],'lora-test')
    # Lexical candidate selection is an explicitly separate, lightweight comparator.
    baseline=[]
    for row in data['splits']['test']:
        from difflib import SequenceMatcher
        scores=[(SequenceMatcher(None,row['question'],p['text']).ratio(),p['id']) for p in row['paragraphs']]
        best=max(scores)
        raw=json.dumps({'selected':[best[1]] if best[0]>=0.12 else []})
        baseline.append({**score_output(raw,row),'id':row['id'],'kind':row['kind'],'latency_seconds':0,'raw_output':raw})
    report['lexical_comparator']={'method':'Character SequenceMatcher >= 0.12, not application TF-IDF/BM25 retrieval',
                                  'metrics':summarize(baseline),'results':baseline}
    base=report['base_test']['metrics'];after=report['lora_test']['metrics']
    report['delta_exact_match']=after['exact_match']-base['exact_match']
    report['promote_adapter']=False
    report['promotion_note']='Experiment only. No production replacement: small synthetic set; requires expert labels, broader safety and quantized-serving evaluation.'
    report['status']='completed';report['completed_at']=datetime.now(timezone.utc).isoformat();persist()
    print(json.dumps({'status':report['status'],'base':base,'lora':after},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',default='Qwen/Qwen3-0.6B')
    parser.add_argument('--revision',default='main')
    parser.add_argument('--steps',type=int,default=12)
    parser.add_argument('--threads',type=int,default=2)
    parser.add_argument('--max-length',type=int,default=384)
    parser.add_argument('--learning-rate',type=float,default=0.0002)
    parser.add_argument('--run-id',default='cpu-smoke-v1')
    args=parser.parse_args()
    if not args.run_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.run_id):
        parser.error('run-id must use letters, digits, hyphens or underscores')
    if args.steps<1 or args.threads<1:parser.error('steps and threads must be positive')
    target=ROOT/'artifacts/lora-training-report.json'
    if target.exists():
        prior=json.loads(target.read_text(encoding='utf-8'))
        archive=ROOT/'artifacts'/('lora-training-'+prior['run_id']+'.json')
        if archive.exists():parser.error('Prior run archive exists; choose a new run-id and preserve existing evidence')
        archive.write_bytes(target.read_bytes())
    os.environ.setdefault('HF_HUB_DISABLE_XET','1')
    os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING','1')
    report={'run_id':args.run_id,'status':'initializing','started_at':datetime.now(timezone.utc).isoformat(),
            'base_model':args.model,'limitations':'12-step CPU smoke experiment by default; tiny synthetic source-family holdout, no factory efficacy claim.'}
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Loading official model; initial report saved.',flush=True)
    try:run(args,report,target)
    except Exception as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc)[:1600])
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
