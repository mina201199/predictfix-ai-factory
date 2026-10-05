"""Install official llama.cpp CPU build + official Qwen GGUF into project only."""
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.runtime'
RUNTIME.mkdir(exist_ok=True)

def read_json(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'PredictFix'}),timeout=60) as r:
        return json.load(r)

def download(url,target):
    if target.exists() and target.stat().st_size>1024*1024:
        return
    print('Downloading',target.name,flush=True)
    partial=target.with_suffix(target.suffix+'.part')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'PredictFix'}),timeout=90) as response, partial.open('wb') as file:
        count=0
        while chunk:=response.read(1024*1024):
            file.write(chunk)
            count+=len(chunk)
            if count%(20*1024*1024)==0:
                print(f'{target.name}: {count//(1024*1024)} MiB',flush=True)
    partial.replace(target)

release=read_json('https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=1')[0]
asset=next(a for a in release['assets'] if 'bin-win-cpu-x64.zip' in a['name'])
archive=RUNTIME/asset['name']
download(asset['browser_download_url'],archive)
target=RUNTIME/'llama'
target.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as zip_file:
    for item in zip_file.infolist():
        if not (target/item.filename).resolve().is_relative_to(target.resolve()):
            raise ValueError('Unexpected archive path')
    zip_file.extractall(target)
repo='Qwen/Qwen3-0.6B-GGUF'
metadata=read_json('https://huggingface.co/api/models/'+repo)
names=[s['rfilename'] for s in metadata['siblings']]
name=next((n for n in names if 'q4_k_m' in n.lower()), next(n for n in names if n.endswith('.gguf')))
model=RUNTIME/'models'/Path(name).name
model.parent.mkdir(exist_ok=True)
download('https://huggingface.co/'+repo+'/resolve/main/'+name,model)
(RUNTIME/'local-llm.json').write_text(json.dumps({'runtime_version':release['tag_name'],
    'runtime_url':asset['browser_download_url'],'model_repository':repo,'model_file':str(model)},indent=2),encoding='utf-8')
print('READY',model,flush=True)
