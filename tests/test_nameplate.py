import io
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
# 這兩個模組刻意不匯入 backend.store，收集測試時才不會固定 test_api 的 DATABASE_URL
from backend import nameplate
from scripts import generate_nameplates

IDS=[f'CNC-{n:02}' for n in range(1,19)]


def png(image):
  buffer=io.BytesIO()
  image.save(buffer,'PNG')
  return buffer.getvalue()


def test_exact_match_auto_opens():
  candidates=nameplate.match_machine_ids([('MACHINE ID CNC-07',0.98)],IDS)
  assert candidates[0]['machine_id']=='CNC-07'
  assert nameplate.decide(candidates)=='auto'


def test_confuses_letters_and_digits():
  assert nameplate.match_machine_ids([('CNC-0l',0.95)],IDS)[0]['machine_id']=='CNC-01'
  assert nameplate.match_machine_ids([('CNC O7',0.95)],IDS)[0]['machine_id']=='CNC-07'


def test_ignores_model_and_serial_numbers():
  lines=[('MODEL VMC-850',0.99),('SERIAL No. 24-0137',0.99),('MACHINE ID CNC-12',0.97)]
  candidates=nameplate.match_machine_ids(lines,IDS)
  assert candidates[0]['machine_id']=='CNC-12'
  assert all(c['machine_id'] in IDS for c in candidates)
  assert nameplate.decide(candidates)=='auto'


def test_unknown_id_never_auto_opens():
  assert nameplate.decide(nameplate.match_machine_ids([('CNC-99',0.99)],IDS))!='auto'


def test_production_style_ids():
  candidates=nameplate.match_machine_ids([('ID MILL-001',0.9)],['MILL-001','M01'])
  assert candidates[0]['machine_id']=='MILL-001'


def test_no_text_means_manual():
  assert nameplate.match_machine_ids([],IDS)==[]
  assert nameplate.decide([])=='manual'


def test_candidates_are_capped_and_sorted():
  lines=[('CNC-01',0.9),('CNC-02',0.95),('CNC-03',0.99),('CNC-04',0.7)]
  candidates=nameplate.match_machine_ids(lines,IDS)
  assert len(candidates)<=3
  assert [c['confidence'] for c in candidates]==sorted((c['confidence'] for c in candidates),reverse=True)
  assert all(c['confidence']>=nameplate.CONFIRM_MIN for c in candidates)


def test_every_variant_renders_an_image():
  for variant in generate_nameplates.VARIANTS:
    image=generate_nameplates.render_nameplate('CNC-03',variant,seed=1)
    assert image.size[0]>=600 and image.mode=='RGB'


def test_reads_rendered_nameplate():
  lines=nameplate.recognize(png(generate_nameplates.render_nameplate('CNC-07')))
  candidates=nameplate.match_machine_ids(lines,IDS)
  assert candidates[0]['machine_id']=='CNC-07'
  assert candidates[0]['confidence']>=nameplate.AUTO_OPEN


def test_blank_image_has_no_candidates():
  from PIL import Image
  lines=nameplate.recognize(png(Image.new('RGB',(400,300),(128,128,128))))
  assert nameplate.match_machine_ids(lines,IDS)==[]


def test_engine_info_names_engine():
  info=nameplate.engine_info()
  assert info['engine']=='rapidocr' and info['version']


def test_unknown_similar_id_requires_confirmation():
  candidates=nameplate.match_machine_ids([('MILL-0002',0.99)],['MILL-0001','LATHE-001'])
  assert candidates[0]['machine_id']=='MILL-0001'
  assert nameplate.decide(candidates)=='confirm'
