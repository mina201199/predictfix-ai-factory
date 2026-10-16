"""Offline nameplate OCR and machine ID matching.

Keep this module free of backend.store imports: importing the store fixes DATABASE_URL,
and tests import this module during collection.
"""
import difflib
import io
import threading
from importlib import metadata

AUTO_OPEN=0.85
CONFIRM_MIN=0.50
# 兩個候選太接近時不自動開啟，例如照片裡同時拍到兩塊銘牌
AMBIGUITY_GAP=0.10
# OCR 常把數字看成外形相近的字母；只在機台編號該是數字的位置修正
DIGIT_LOOKALIKES={'O':'0','D':'0','Q':'0','I':'1','L':'1','|':'1','S':'5','B':'8','Z':'2','G':'6'}

_engine=None
_lock=threading.Lock()


def normalize_text(text):
  return ' '.join(text.upper().split())


def compact(text):
  return ''.join(ch for ch in text.upper() if ch.isalnum())


def fragments(line):
  # 單一 token 之外也看相鄰兩個 token，處理「CNC 07」這種被空白拆開的編號
  tokens=normalize_text(line).split(' ')
  pieces=set(tokens)|{a+b for a,b in zip(tokens,tokens[1:])}
  return {compact(p) for p in pieces if compact(p)}


def similarity(fragment,machineId):
  target=compact(machineId)
  fixed=''.join(DIGIT_LOOKALIKES.get(ch,ch) if i<len(target) and target[i].isdigit() else ch
                for i,ch in enumerate(fragment))
  return max(difflib.SequenceMatcher(None,candidate,target).ratio() for candidate in (fragment,fixed))


def match_machine_ids(lines,machine_ids):
  best={}
  for text,score in lines:
    for fragment in fragments(text):
      for machineId in machine_ids:
        confidence=round(float(score)*similarity(fragment,machineId),3)
        if confidence>best.get(machineId,{'confidence':-1})['confidence']:
          best[machineId]={'machine_id':machineId,'confidence':confidence,'raw_text':text}
  ranked=sorted((c for c in best.values() if c['confidence']>=CONFIRM_MIN),key=lambda c:(-c['confidence'],c['machine_id']))
  return ranked[:3]


def decide(candidates):
  if not candidates:return 'manual'
  top=candidates[0]['confidence']
  second=candidates[1]['confidence'] if len(candidates)>1 else 0
  return 'auto' if top>=AUTO_OPEN and top-second>=AMBIGUITY_GAP else 'confirm'


def engine():
  global _engine
  with _lock:
    if _engine is None:
      from rapidocr import RapidOCR
      # 預設 INFO 日誌每次啟動都會刷一串模型路徑，對操作者沒有幫助
      _engine=RapidOCR(params={'Global.log_level':'warning'})
    return _engine


def recognize(image_bytes):
  ocr=engine()
  # onnxruntime session 不保證同時多執行緒呼叫的安全，掃描請求依序處理
  with _lock:
    result=ocr(image_bytes)
  texts=result.txts or ()
  scores=result.scores or ()
  return [(text,float(score)) for text,score in zip(texts,scores) if text and text.strip()]


def engine_info():
  return {'engine':'rapidocr','version':metadata.version('rapidocr'),'runtime':'onnxruntime '+metadata.version('onnxruntime')}


def warmup():
  from PIL import Image, ImageDraw, ImageFont
  image=Image.new('RGB',(420,140),(255,255,255))
  ImageDraw.Draw(image).text((20,30),'CNC-01',fill=(0,0,0),font=ImageFont.load_default(size=64))
  buffer=io.BytesIO()
  image.save(buffer,'PNG')
  lines=recognize(buffer.getvalue())
  return {**engine_info(),'ready':any('CNC' in text.upper() for text,_ in lines)}
