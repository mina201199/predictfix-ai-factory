"""Isolated localhost adapter serving; never substituted for the production LLM."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_lora_data import prompt
from train_lora import score_output


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8085)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Invalid port')
    report=json.loads((ROOT/'artifacts/lora-training-report.json').read_text(encoding='utf-8'))
    if report['status']!='completed':raise SystemExit('A completed training report is required')
    adapter=(ROOT/report['adapter_path']).resolve()
    if not adapter.is_relative_to((ROOT/'.runtime/lora-runs').resolve()):raise SystemExit('Adapter outside experiment directory')
    checksum=hashlib.sha256((adapter/'adapter_model.safetensors').read_bytes()).hexdigest()
    if checksum!=report['adapter_sha256']:raise SystemExit('Adapter checksum mismatch')
    import torch
    from transformers import AutoTokenizer,AutoModelForCausalLM
    from peft import PeftModel
    torch.set_num_threads(2)
    tokenizer=AutoTokenizer.from_pretrained(report['base_model'],revision=report['model_revision'],
        cache_dir=ROOT/'.runtime/hf-cache',local_files_only=True)
    base=AutoModelForCausalLM.from_pretrained(report['base_model'],revision=report['model_revision'],
        cache_dir=ROOT/'.runtime/hf-cache',local_files_only=True,dtype=torch.float32,attn_implementation='sdpa')
    model=PeftModel.from_pretrained(base,adapter);model.eval()
    metadata={'status':'ok','mode':'isolated_lora_experiment','run_id':report['run_id'],
              'base_model':report['base_model'],'adapter_sha256':checksum,'production_model_replaced':False}
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,body):
            data=json.dumps(body,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/healthz':self.send(200,metadata)
            else:self.send(404,{'error':'Not found'})
        def do_POST(self):
            if self.path!='/predict':self.send(404,{'error':'Not found'});return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=20000:raise ValueError('Request size limit')
                row=json.loads(self.rfile.read(size))
                if set(row)!= {'question','paragraphs'}:raise ValueError('Expected question and paragraphs')
                if not isinstance(row['question'],str) or not 2<=len(row['question'])<=2000:raise ValueError('Question length')
                if not isinstance(row['paragraphs'],list) or not 1<=len(row['paragraphs'])<=12:raise ValueError('Paragraph count')
                for p in row['paragraphs']:
                    if not isinstance(p,dict) or set(p)!= {'id','text'}:raise ValueError('Paragraph fields')
                    if not isinstance(p['id'],str) or not 1<=len(p['id'])<=30:raise ValueError('ID length')
                    if not isinstance(p['text'],str) or not 1<=len(p['text'])<=1500:raise ValueError('Text length')
                if len({p['id'] for p in row['paragraphs']})!=len(row['paragraphs']):raise ValueError('Duplicate paragraph IDs')
                text=tokenizer.apply_chat_template([{'role':'user','content':prompt(row)}],tokenize=False,
                    add_generation_prompt=True,enable_thinking=False)
                batch=tokenizer(text,return_tensors='pt')
                if batch['input_ids'].shape[1]>384:raise ValueError('Token limit exceeded')
                start=time.perf_counter()
                with torch.inference_mode():
                    output=model.generate(**batch,do_sample=False,max_new_tokens=32,pad_token_id=tokenizer.eos_token_id)
                raw=tokenizer.decode(output[0,batch['input_ids'].shape[1]:],skip_special_tokens=True)
                checked=score_output(raw,{**row,'selected':[]})
                self.send(200,{'valid':checked['valid'],'selected':checked['selected'] if checked['valid'] else [],
                               'raw_output':raw,'latency_seconds':round(time.perf_counter()-start,4),
                               'run_id':report['run_id'],'scope':'Synthetic experiment; human review required'})
            except (ValueError,KeyError,TypeError,UnicodeDecodeError):self.send(400,{'error':'Invalid experiment input'})
    server=HTTPServer(('127.0.0.1',args.port),Handler)
    print(json.dumps(metadata),flush=True)
    server.serve_forever()


if __name__=='__main__':main()
