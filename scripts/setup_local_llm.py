"""Install official llama.cpp CPU build + Gemma 4 E2B GGUF (Google, Apache 2.0) into project only."""
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'.runtime'
RUNTIME.mkdir(exist_ok=True)
# 固定為 docs/local-llm-benchmark.md 實測過的組合並驗證 SHA-256，避免下載到未測試的新版或遭替換的檔案
RUNTIME_URL='https://github.com/ggml-org/llama.cpp/releases/download/b11491/llama-b11491-bin-win-cpu-x64.zip'
RUNTIME_SHA256='dd73bb6652216f354a8786970cc50f6d90768cde2a6c47321976f7bd5b02447b'
MODEL_REPO='ggml-org/gemma-4-E2B-it-GGUF'
MODEL_REVISION='b4243c156154b6dca9324415f8c7ccc098b4aed1'
MODEL_FILE='gemma-4-E2B-it-Q8_0.gguf'
MODEL_SHA256='996d08777aadc6bfd3c7375ef70ba25a0f55240075860754fdb18d6d860aa63a'

def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as file:
        while chunk:=file.read(8*1024*1024):
            value.update(chunk)
    return value.hexdigest()

def download(url,target,expected):
    if target.exists() and digest(target)==expected:
        return
    print('Downloading',target.name,flush=True)
    partial=target.with_suffix(target.suffix+'.part')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'PredictFix'}),timeout=90) as response, partial.open('wb') as file:
        count=0
        while chunk:=response.read(1024*1024):
            file.write(chunk)
            count+=len(chunk)
            if count%(200*1024*1024)==0:
                print(f'{target.name}: {count//(1024*1024)} MiB',flush=True)
    if digest(partial)!=expected:
        partial.unlink()
        raise SystemExit('SHA-256 mismatch: '+target.name)
    partial.replace(target)

archive=RUNTIME/Path(RUNTIME_URL).name
download(RUNTIME_URL,archive,RUNTIME_SHA256)
target=RUNTIME/'llama'
target.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as zip_file:
    for item in zip_file.infolist():
        if not (target/item.filename).resolve().is_relative_to(target.resolve()):
            raise ValueError('Unexpected archive path')
    zip_file.extractall(target)
model=RUNTIME/'models'/MODEL_FILE
model.parent.mkdir(exist_ok=True)
download(f'https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{MODEL_FILE}',model,MODEL_SHA256)
(RUNTIME/'local-llm.json').write_text(json.dumps({'runtime_version':'b11491','runtime_url':RUNTIME_URL,
    'model_repository':MODEL_REPO,'model_revision':MODEL_REVISION,'model_file':str(model)},indent=2),encoding='utf-8')
print('READY',model,flush=True)
