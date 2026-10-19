"""QLoRA 可行性檢查：GTX 1050 Ti（sm_61、4 GB）能否用 bitsandbytes nf4 對 Gemma 4 E2B 做 LoRA 訓練。

只記錄能否完成與顯存，不記錄速度：本機同時有其他工作在跑，計時不可信。
在獨立環境 .runtime/qlora-env 執行（安裝方式見 docs/qlora-feasibility.md）：
  python scripts/check_qlora_feasibility.py env
  python scripts/check_qlora_feasibility.py kernels
  python scripts/check_qlora_feasibility.py tiny
  python scripts/check_qlora_feasibility.py estimate
  python scripts/check_qlora_feasibility.py real --mode qlora
  python scripts/check_qlora_feasibility.py real --mode fp16
  python scripts/check_qlora_feasibility.py real --mode fp32
結果逐段寫入 artifacts/qlora-feasibility.json。
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import torch

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'artifacts/qlora-feasibility.json'
MODEL_ID='google/gemma-4-E2B-it'
MODEL_REVISION='3e22461f65e89153144f8adb70e3b8c2cc9845a7'
PACKAGES=['torch','transformers','peft','bitsandbytes','accelerate','safetensors','huggingface_hub','tokenizers']
LORA_TARGETS=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj']


def nowIso():
  return datetime.now(timezone.utc).isoformat(timespec='seconds')


def loadReport():
  if REPORT.exists():
    return json.loads(REPORT.read_text(encoding='utf-8'))
  return {'purpose':'GTX 1050 Ti 本機 QLoRA 可行性；只記錄可否完成與顯存，不含速度。',
          'model':{'id':MODEL_ID,'revision':MODEL_REVISION}}


def saveSection(name,value):
  report=loadReport()
  report[name]=value
  report['updated_at']=nowIso()
  REPORT.parent.mkdir(parents=True,exist_ok=True)
  REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  print(json.dumps({name:value},ensure_ascii=False,indent=2)[:4000],flush=True)


def nvidiaSmi():
  # 在 CUDA 初始化前先讀，才能分出「其他程式（桌面、瀏覽器）已占用」與本程序新增的顯存
  fields='name,driver_version,memory.total,memory.used,compute_cap'
  try:
    out=subprocess.run(['nvidia-smi',f'--query-gpu={fields}','--format=csv,noheader,nounits'],
                       capture_output=True,text=True,timeout=30).stdout.strip().splitlines()[0]
  except (OSError,IndexError,subprocess.SubprocessError):
    return None
  name,driver,total,used,cap=[x.strip() for x in out.split(',')]
  return {'name':name,'driver':driver,'total_mib':int(total),'used_by_others_mib':int(used),'compute_cap':cap}


def gpuSnapshot(torch):
  free,total=torch.cuda.mem_get_info()
  return {'device_used_mib':(total-free)>>20,'device_free_mib':free>>20,
          'peak_allocated_mib':torch.cuda.max_memory_allocated()>>20,
          'peak_reserved_mib':torch.cuda.max_memory_reserved()>>20}


def runtimeDir(args):
  return Path(args.runtime_dir).resolve() if args.runtime_dir else ROOT/'.runtime'


def env(args):
  smi=nvidiaSmi()
  versions={}
  for name in PACKAGES:
    try:versions[name]=importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:versions[name]=None
  info={'checked_at':nowIso(),'python':sys.version.split()[0],'os':platform.platform(),'packages':versions,
        'nvidia_smi_before_cuda_init':smi,'torch_cuda':torch.version.cuda,'cuda_available':torch.cuda.is_available()}
  if torch.cuda.is_available():
    info.update(device=torch.cuda.get_device_name(0),capability='.'.join(map(str,torch.cuda.get_device_capability(0))),
                torch_arch_list=torch.cuda.get_arch_list(),sm61_in_torch_build='sm_61' in torch.cuda.get_arch_list(),
                # Pascal 沒有原生 bf16；is_bf16_supported() 預設把模擬也算進去，要分開記錄
                bf16_native=torch.cuda.is_bf16_supported(including_emulation=False))
    torch.cuda.init();info['after_cuda_init']=gpuSnapshot(torch)
  # 授權狀態直接查 Hugging Face 公開 API，不需要 token
  url=f'https://huggingface.co/api/models/{MODEL_ID}/revision/{MODEL_REVISION}?blobs=true'
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'PredictFix-feasibility'}),timeout=60) as response:
    meta=json.load(response)
  files={s['rfilename']:s.get('size') for s in meta.get('siblings',[])}
  info['model_access']={'api':url.split('?')[0],'gated':meta.get('gated'),'private':meta.get('private'),
                        'license':[t for t in meta.get('tags',[]) if t.startswith('license:')],
                        'sha':meta.get('sha'),'weights_bytes':files.get('model.safetensors'),
                        'token_required':meta.get('gated') not in (False,None) or bool(meta.get('private'))}
  saveSection('environment',info)


def kernels(args):
  import bitsandbytes as bnb
  import bitsandbytes.functional as F
  torch.manual_seed(0)
  results=[]
  for computeDtype in [torch.float32,torch.float16]:
    for doubleQuant in [False,True]:
      reference=torch.nn.Linear(512,1024,bias=False)
      layer=bnb.nn.Linear4bit(512,1024,bias=False,compute_dtype=computeDtype,compress_statistics=doubleQuant,quant_type='nf4')
      layer.weight=bnb.nn.Params4bit(reference.weight.data.clone(),requires_grad=False,
                                     compress_statistics=doubleQuant,quant_type='nf4')
      layer=layer.cuda()
      dequantized=F.dequantize_4bit(layer.weight.data,layer.weight.quant_state).float()
      x=torch.randn(8,512,device='cuda',requires_grad=True)
      y=layer(x.to(computeDtype))
      y.float().square().mean().backward()
      expected=(x.detach().to(computeDtype).float()@dequantized.t())
      results.append({'quant_type':'nf4','compute_dtype':str(computeDtype).replace('torch.',''),'double_quant':doubleQuant,
                      'storage_dtype':str(layer.weight.dtype).replace('torch.',''),
                      'max_abs_error_vs_dequantized':round((y.float()-expected).abs().max().item(),6),
                      'mean_abs_quantization_error':round((dequantized.cpu()-reference.weight).abs().mean().item(),6),
                      'input_grad_finite':bool(x.grad is not None and torch.isfinite(x.grad).all().item())})
  ok=all(r['input_grad_finite'] and r['max_abs_error_vs_dequantized']<0.05 for r in results)
  saveSection('kernels',{'checked_at':nowIso(),'device':torch.cuda.get_device_name(0),'passed':ok,'cases':results})


def tinyConfig():
  from transformers import Gemma4TextConfig
  # 結構比照 E2B（PLE、KV 共用層、double-wide MLP、sliding/full 交錯、logit softcap），只把尺寸縮小
  return Gemma4TextConfig(
    vocab_size=4096,vocab_size_per_layer_input=4096,hidden_size=256,hidden_size_per_layer_input=32,
    intermediate_size=512,num_hidden_layers=5,num_kv_shared_layers=2,num_attention_heads=4,num_key_value_heads=1,
    head_dim=64,global_head_dim=128,layer_types=['sliding_attention','sliding_attention','full_attention','sliding_attention','full_attention'],sliding_window=64,
    max_position_embeddings=1024,use_double_wide_mlp=True,tie_word_embeddings=True,final_logit_softcapping=30.0,
    rope_parameters={'full_attention':{'partial_rotary_factor':0.25,'rope_theta':1000000.0,'rope_type':'proportional'},
                     'sliding_attention':{'rope_theta':10000.0,'rope_type':'default'}},
    pad_token_id=0,bos_token_id=2,eos_token_id=1)


def toNf4(linear,computeDtype):
  import bitsandbytes as bnb
  layer=bnb.nn.Linear4bit(linear.in_features,linear.out_features,bias=linear.bias is not None,
                          compute_dtype=computeDtype,compress_statistics=True,quant_type='nf4')
  layer.weight=bnb.nn.Params4bit(linear.weight.data.float(),requires_grad=False,compress_statistics=True,quant_type='nf4')
  if linear.bias is not None:
    layer.bias=torch.nn.Parameter(linear.bias.data.float(),requires_grad=False)
  return layer


def replaceLinears(module,computeDtype):
  count=0
  for name,child in list(module.named_children()):
    if isinstance(child,torch.nn.Linear):
      setattr(module,name,toNf4(child,computeDtype));count+=1
    else:
      count+=replaceLinears(child,computeDtype)
  return count



def placeDecoder(causalLm,mode,device,progress):
  """decoder 放 GPU；embed_tokens、PLE 表與共用權重的 lm_head 留在 CPU。

  bitsandbytes 不量化 embedding，E2B 的 PLE 表 fp16 就要 4.7 GB；transformers 的 device_map 雖可標成 cpu，
  但 accelerate 會在 forward 時把權重搬上 GPU，所以改為手動拆分，embedding 只在 CPU 查表後把結果送上 GPU。
  """
  text=causalLm.model
  dtype={'qlora':torch.float32,'fp16':torch.float16,'fp32':torch.float32}[mode]
  progress.update(total_layers=len(text.layers),layers_on_gpu=0,quantized_linears=0)
  # 每層個別轉換再上 GPU，放不下時才知道是在第幾層、已用多少顯存
  for layer in text.layers:
    layer.to(dtype)
    if mode=='qlora':progress['quantized_linears']+=replaceLinears(layer,torch.float32)
    layer.to(device);progress['layers_on_gpu']+=1
  for name in ['norm','rotary_emb','per_layer_projection_norm']:
    getattr(text,name).to(dtype).to(device)
  projection=text.per_layer_model_projection.to(dtype)
  if mode=='qlora':
    projection=toNf4(projection,torch.float32);progress['quantized_linears']+=1
  text.per_layer_model_projection=projection.to(device)
  causalLm.is_loaded_in_4bit=mode=='qlora'
  return progress


def trainSteps(causalLm,examples,device,steps,learningRate,log):
  """自行拆開 forward：CPU 查 embedding，GPU 跑 decoder，只對答案位置在 CPU 算 lm_head。

  詞彙表 262,144 個，若對整段序列算 logits，光 fp32 logits 就以 GB 計；只取答案 token 才放得下。
  """
  import torch.nn.functional as F
  text=causalLm.model
  trainable=[p for p in causalLm.parameters() if p.requires_grad]
  optimizer=torch.optim.AdamW(trainable,lr=learningRate)
  causalLm.train()
  softcap=causalLm.config.final_logit_softcapping
  records=[]
  for step in range(steps):
    ids,labels=examples[step%len(examples)]
    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
      embeds=text.embed_tokens(ids[None])
      perLayer=text.get_per_layer_inputs(ids[None],None)
    # fp16 對照組必須跟隨 decoder 型別，才能將運算錯誤與資源限制分開判讀。
    decoderDtype=text.norm.weight.dtype
    out=text(inputs_embeds=embeds.to(device,decoderDtype),per_layer_inputs=perLayer.to(device,decoderDtype),use_cache=False)
    targets=labels[1:]
    positions=(targets!=-100).nonzero().squeeze(1)
    hidden=out.last_hidden_state[0,positions.to(device)].to('cpu')
    logits=causalLm.lm_head(hidden.to(causalLm.lm_head.weight.dtype)).float()
    if softcap:logits=torch.tanh(logits/softcap)*softcap
    loss=F.cross_entropy(logits,targets[positions])
    if not torch.isfinite(loss):raise RuntimeError('Non-finite loss')
    optimizer.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(trainable,1.0)
    optimizer.step()
    torch.cuda.synchronize()
    record={'step':step+1,'sequence_tokens':int(ids.numel()),'answer_tokens':int(positions.numel()),
            'loss':round(loss.item(),4),**gpuSnapshot(torch)}
    records.append(record);log(record)
  return records


def addLora(causalLm,rank):
  from peft import LoraConfig, get_peft_model
  config=LoraConfig(r=rank,lora_alpha=rank*2,lora_dropout=0.05,target_modules=LORA_TARGETS,bias='none',task_type='CAUSAL_LM')
  peftModel=get_peft_model(causalLm,config)
  causalLm.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant':False})
  causalLm.config.use_cache=False
  trainable=sum(p.numel() for p in causalLm.parameters() if p.requires_grad)
  loraLayers=sum(1 for n,_ in causalLm.named_modules() if n.endswith('lora_A'))
  return peftModel,{'rank':rank,'alpha':rank*2,'target_modules':LORA_TARGETS,'trainable_parameters':trainable,
                    'lora_wrapped_linears':loraLayers}


def tiny(args):
  from transformers import Gemma4ForCausalLM
  torch.manual_seed(0)
  causalLm=Gemma4ForCausalLM(tinyConfig()).to(torch.bfloat16)
  base=torch.cuda.memory_allocated()
  placement=placeDecoder(causalLm,'qlora','cuda',{})
  linear4bit=sum(1 for m in causalLm.modules() if type(m).__name__=='Linear4bit')
  _,lora=addLora(causalLm,8)
  wrapped=sum(1 for m in causalLm.modules() if type(m).__module__.startswith('peft') and type(m).__name__=='Linear4bit')
  generator=torch.Generator().manual_seed(0)
  examples=[]
  for _ in range(3):
    ids=torch.randint(3,4096,(96,),generator=generator)
    labels=torch.full_like(ids,-100);labels[-12:]=ids[-12:]
    examples.append((ids,labels))
  records=trainSteps(causalLm,examples,'cuda',3,2e-4,lambda r:print(json.dumps(r),flush=True))
  saveSection('tiny_gemma4',{'checked_at':nowIso(),
    'purpose':'隨機初始化、結構比照 Gemma 4 E2B 的迷你模型；驗證 transformers Gemma 4 + bitsandbytes nf4 + PEFT LoRA 在 sm_61 的訓練路徑，不下載權重。',
    'config':{k:getattr(causalLm.config,k) for k in ['hidden_size','num_hidden_layers','num_kv_shared_layers','vocab_size','hidden_size_per_layer_input']},
    'placement':placement,'linear4bit_modules':linear4bit,'peft_lora_on_linear4bit':wrapped,'lora':lora,
    'weights_before_mib':base>>20,'steps':records,
    'passed':len(records)==3 and all(r['loss']==r['loss'] for r in records) and wrapped>0})


def paramBytes(params,bytesPerParam):
  return round(params*bytesPerParam/2**30,2)


def estimate(args):
  from huggingface_hub import hf_hub_download
  from transformers import AutoConfig, Gemma4ForConditionalGeneration
  cache=runtimeDir(args)/'hf-cache'
  hf_hub_download(MODEL_ID,'config.json',revision=MODEL_REVISION,cache_dir=cache)
  config=AutoConfig.from_pretrained(MODEL_ID,revision=MODEL_REVISION,cache_dir=cache)
  with torch.device('meta'):
    model=Gemma4ForConditionalGeneration(config)
  groups={'vision':0,'audio':0,'text_embed_tokens':0,'text_per_layer_embeddings':0,'text_decoder_linear':0,'text_other':0}
  for name,param in model.named_parameters():
    if '.vision_tower.' in f'.{name}' or 'embed_vision' in name:groups['vision']+=param.numel()
    elif '.audio_tower.' in f'.{name}' or 'embed_audio' in name:groups['audio']+=param.numel()
    elif name.endswith('language_model.embed_tokens.weight'):groups['text_embed_tokens']+=param.numel()
    elif 'embed_tokens_per_layer' in name:groups['text_per_layer_embeddings']+=param.numel()
    elif name.startswith('lm_head'):continue
    elif name.endswith('.weight') and param.dim()==2 and 'language_model' in name:groups['text_decoder_linear']+=param.numel()
    else:groups['text_other']+=param.numel()
  linear=groups['text_decoder_linear'];embed=groups['text_embed_tokens'];ple=groups['text_per_layer_embeddings']
  other=groups['text_other']
  # nf4 每參數 0.5 byte，加上 blocksize 64 的量化常數（double quant 後約 +0.03 byte）
  nf4=0.53
  scenarios={
    'lora_fp32_all_gpu':paramBytes(linear+embed+ple+other,4),
    'lora_fp16_all_gpu':paramBytes(linear+embed+ple+other,2),
    'lora_fp32_embeddings_on_cpu':paramBytes(linear+other,4),
    'lora_fp16_embeddings_on_cpu':paramBytes(linear+other,2),
    'qlora_nf4_bnb_default_embeddings_fp16_on_gpu':round(paramBytes(linear,nf4)+paramBytes(embed+ple+other,2),2),
    'qlora_nf4_embeddings_on_cpu':round(paramBytes(linear,nf4)+paramBytes(other,4),2)}
  saveSection('estimate',{'checked_at':nowIso(),'source':'官方 config.json 於 meta device 建模計數；只算權重，未含 CUDA context、啟動值與 optimizer。',
    'parameters':groups,'text_total_parameters':linear+embed+ple+other,
    'weights_gib':scenarios,'gpu_total_gib':4.0,
    'note':'PLE 表 = vocab_size_per_layer_input × num_hidden_layers × hidden_size_per_layer_input；bitsandbytes 不量化 embedding。'})


def realExamples(tokenizer,maxRows,datasetPath,seqCap):
  sys.path.insert(0,str(ROOT/'scripts'))
  from prepare_lora_data import prompt
  data=json.loads(datasetPath.read_text(encoding='utf-8'))
  rows=data['splits']['train']
  examples=[]
  for row in rows:
    answer=json.dumps({'selected':row['selected']},ensure_ascii=False,separators=(',',':'))
    messages=[{'role':'user','content':prompt(row)}]
    promptIds=tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,return_dict=True)['input_ids']
    fullIds=tokenizer.apply_chat_template(messages+[{'role':'assistant','content':answer}],tokenize=True,return_dict=True)['input_ids']
    if fullIds[:len(promptIds)]!=promptIds:raise RuntimeError('Chat template prefix mismatch')
    if len(fullIds)>seqCap:continue
    ids=torch.tensor(fullIds)
    labels=ids.clone();labels[:len(promptIds)]=-100
    examples.append((ids,labels))
    if len(examples)>=maxRows:break
  if not examples:raise RuntimeError('No example fits the sequence cap')
  return examples


def real(args):
  smi=nvidiaSmi()
  from transformers import AutoConfig, AutoTokenizer, Gemma4ForCausalLM
  cache=runtimeDir(args)/'hf-cache'
  section=f'real_{args.mode}_{args.weights}'+(f'_{args.label}' if args.label else '')
  result={'checked_at':nowIso(),'mode':args.mode,'nvidia_smi_before_cuda_init':smi,'status':'started'}
  try:
    result['dataset']={'path':args.dataset,
      'sha256':hashlib.sha256(Path(args.dataset).read_text(encoding='utf-8').encode('utf-8')).hexdigest(),
      'sha256_encoding':'UTF-8 text with LF line endings'}
    result['requested_steps']=args.steps
    result['sequence_token_limit']=args.seq_len
    config=AutoConfig.from_pretrained(MODEL_ID,revision=MODEL_REVISION,cache_dir=cache,local_files_only=not args.allow_download)
    tokenizer=AutoTokenizer.from_pretrained(MODEL_ID,revision=MODEL_REVISION,cache_dir=cache,local_files_only=not args.allow_download)
    result['weights']=args.weights
    if args.weights=='random':
      # 顯存只取決於張量形狀與 dtype；用官方 config 隨機初始化，可在未下載權重前量到相同的顯存，loss 則沒有意義
      torch.manual_seed(0)
      previous=torch.get_default_dtype();torch.set_default_dtype(torch.bfloat16)
      try:causalLm=Gemma4ForCausalLM(config.text_config)
      finally:torch.set_default_dtype(previous)
    else:
      # 多模態 checkpoint 只取文字解碼器；視覺／音訊權重不載入
      causalLm,loadingInfo=Gemma4ForCausalLM.from_pretrained(MODEL_ID,revision=MODEL_REVISION,cache_dir=cache,config=config.text_config,
        dtype=torch.bfloat16,key_mapping={r'^model\.language_model\.':'model.'},local_files_only=not args.allow_download,
        output_loading_info=True)
      result['checkpoint_loading']={'missing_keys':sorted(loadingInfo.get('missing_keys',[])),
        'mismatched_keys':sorted(loadingInfo.get('mismatched_keys',[]),key=str),
        'unexpected_key_count':len(loadingInfo.get('unexpected_keys',[]))}
      if result['checkpoint_loading']['missing_keys'] or result['checkpoint_loading']['mismatched_keys']:
        raise RuntimeError('Pretrained text weights are incomplete or mismatched')
    result['text_parameters']=sum(p.numel() for p in causalLm.parameters())
    causalLm.requires_grad_(False)
    torch.cuda.init();result['after_cuda_init']=gpuSnapshot(torch)
    result['placement']={}
    placeDecoder(causalLm,args.mode,'cuda',result['placement'])
    result['after_weights']=gpuSnapshot(torch)
    _,result['lora']=addLora(causalLm,args.rank)
    examples=realExamples(tokenizer,args.steps,Path(args.dataset),args.seq_len)
    result['steps']=trainSteps(causalLm,examples,'cuda',args.steps,2e-4,lambda r:print(json.dumps(r),flush=True))
    result['status']='completed'
  except torch.OutOfMemoryError as error:
    result.update(status='out_of_memory',error=str(error).splitlines()[0][:600],at_failure=gpuSnapshot(torch))
  except Exception as error:  # 其他失敗也要留紀錄，再往外丟
    result.update(status='failed',error_type=type(error).__name__,error=str(error)[:1200])
    saveSection(section,result);raise
  saveSection(section,result)


if __name__=='__main__':
  os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING','1')
  parser=argparse.ArgumentParser()
  parser.add_argument('command',choices=['env','kernels','tiny','estimate','real'])
  parser.add_argument('--runtime-dir',help='放 hf-cache 的 .runtime 目錄；預設為本專案 .runtime')
  parser.add_argument('--report',type=Path,help='另存報告，保留先前測試紀錄')
  parser.add_argument('--mode',choices=['qlora','fp16','fp32'],default='qlora')
  parser.add_argument('--steps',type=int,default=3)
  parser.add_argument('--seq-len',type=int,default=320)
  parser.add_argument('--rank',type=int,default=8)
  parser.add_argument('--dataset',default=str(ROOT/'training/selection-dataset.json'))
  parser.add_argument('--label',default='')
  parser.add_argument('--weights',choices=['pretrained','random'],default='pretrained',
                      help='random：用官方 config 隨機初始化同形狀模型，只用來量顯存')
  parser.add_argument('--allow-download',action='store_true',help='未加此旗標時只用本機快取，避免未經同意下載 10 GB 權重')
  args=parser.parse_args()
  if args.report is not None:REPORT=args.report
  {'env':env,'kernels':kernels,'tiny':tiny,'estimate':estimate,'real':real}[args.command](args)
