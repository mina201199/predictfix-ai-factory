"""Download the official portable Ollama distribution into this project."""
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/'.runtime'/'ollama'
TARGET.mkdir(parents=True, exist_ok=True)
if not (TARGET/'ollama.exe').exists():
    request=urllib.request.Request('https://api.github.com/repos/ollama/ollama/releases/latest',
                                 headers={'User-Agent':'PredictFix'})
    with urllib.request.urlopen(request, timeout=60) as response:
        release=json.load(response)
    asset=next(a for a in release['assets'] if a['name']=='ollama-windows-amd64.zip')
    archive=TARGET.parent/'ollama.zip'
    with urllib.request.urlopen(asset['browser_download_url'],timeout=120) as response, archive.open('wb') as output:
        total=0
        while chunk:=response.read(1024*1024):
            output.write(chunk)
            total+=len(chunk)
            if total%(100*1024*1024)==0:
                print(f'Downloaded {total//(1024*1024)} MiB',flush=True)
    with zipfile.ZipFile(archive) as bundle:
        # Reject paths outside the explicitly named runtime directory.
        for member in bundle.infolist():
            resolved=(TARGET/member.filename).resolve()
            if not resolved.is_relative_to(TARGET.resolve()):
                raise ValueError('Unexpected archive path')
        bundle.extractall(TARGET)
    (TARGET/'release.json').write_text(json.dumps({'version':release['tag_name'],
                                                 'url':asset['browser_download_url']}),encoding='utf-8')
print(TARGET/'ollama.exe',flush=True)
