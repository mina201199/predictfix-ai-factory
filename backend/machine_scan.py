"""Nameplate scan, machine overview and AI summary routes."""
import io
import re
import time
import warnings
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from . import config, nameplate, store

ROOT=Path(__file__).resolve().parents[1]
SAMPLES=ROOT/'artifacts'/'demo-nameplates'
SAMPLE_NAME=re.compile(r'^[A-Z]{2,5}-\d{2}\.png$')
MAX_BYTES=6*1024*1024
MAX_PIXELS=20_000_000
# 手機原圖動輒 4000 像素寬，縮小後辨識率不變但速度快數倍
OCR_EDGE=1600


def prepared_image(content):
  try:
    with warnings.catch_warnings():
      warnings.simplefilter('error',Image.DecompressionBombWarning)
      with Image.open(io.BytesIO(content)) as image:
        if image.format not in ['JPEG','PNG','WEBP']:raise ValueError('format')
        if image.width*image.height>MAX_PIXELS:raise ValueError('size')
        image.load()
        # 手機直拍的照片靠 EXIF 記錄方向，不轉正 OCR 會讀到橫躺的字
        upright=ImageOps.exif_transpose(image).convert('RGB')
  except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
    raise HTTPException(422,'請上傳有效的 JPG、PNG 或 WebP 照片（最多 2,000 萬畫素）')
  upright.thumbnail((OCR_EDGE,OCR_EDGE))
  buffer=io.BytesIO()
  upright.save(buffer,'PNG')
  return buffer.getvalue()


def active_machine_ids():
  with store.Session() as db:
    return [m.id for m in db.scalars(select(store.Machine).where(store.Machine.active==1).order_by(store.Machine.id)).all()]


def register(app):
  @app.post('/api/scan/nameplate')
  async def scan_nameplate(request:Request):
    content=bytearray()
    async for chunk in request.stream():
      content.extend(chunk)
      if len(content)>MAX_BYTES:raise HTTPException(413,'照片上限 6 MB')
    image=prepared_image(bytes(content))
    started=time.perf_counter()
    lines=await run_in_threadpool(nameplate.recognize,image)
    candidates=nameplate.match_machine_ids(lines,active_machine_ids())
    info=nameplate.engine_info()
    return {'candidates':candidates,'decision':nameplate.decide(candidates),'text':[text for text,_ in lines],
            'elapsed_ms':round((time.perf_counter()-started)*1000),'engine':info['engine']+' '+info['version']}

  @app.get('/api/scan/samples')
  def scan_samples():
    if not config.demo():raise HTTPException(404)
    return [{'machine_id':path.stem,'url':'/api/scan/samples/'+path.name}
            for path in sorted(SAMPLES.glob('*.png')) if SAMPLE_NAME.match(path.name)]

  @app.get('/api/scan/samples/{name}')
  def scan_sample(name:str):
    # 檔名先過白名單再組路徑，避免 ../ 之類的路徑穿越
    if not config.demo() or not SAMPLE_NAME.match(name) or not (SAMPLES/name).is_file():raise HTTPException(404)
    return FileResponse(SAMPLES/name,media_type='image/png')
