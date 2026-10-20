"""Build a 60-second product introduction from real project screenshots."""
from pathlib import Path
import json
import math
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'video'
OUT.mkdir(parents=True, exist_ok=True)
W, H, FPS = 1920, 1080, 24
FONT = 'C:/Windows/Fonts/msjh.ttc'
BOLD = 'C:/Windows/Fonts/msjhbd.ttc'
CYAN = '#33dcf1'
WHITE = '#eff7ff'
MUTED = '#a4bbce'
SCENES = [
    dict(start=0, end=6, label='AI FACTORY / PredictFix AI', title='讓維修流程\n從資訊走到行動', body=['智慧工廠維修 Copilot', '一張工單，串起依據、人員與驗收'], image='neon-equipment-desktop.png', crop=(240, 185, 1505, 995), subtitle='AI Factory｜把維修依據、派工與驗收，接成同一套流程。'),
    dict(start=6, end=15, label='01 / 設備總覽', title='先看見\n需要關注的設備', body=['設備與零件狀態集中查看', '從總覽進入報修與工單'], image='neon-equipment-desktop.png', crop=(240, 185, 1505, 995), subtitle='從設備總覽出發，查看示範設備狀態，找到需要處理的項目。'),
    dict(start=15, end=25, label='02 / 維修依據', title='每一項排查\n都有來源可核對', body=['依機型查找手冊與已發布案例', '保留原文、來源版本與引用'], image='openai-demo-ui.png', crop=(706, 1026, 1397, 1466), subtitle='AI 協助選取相關原文；適用性與排查清單，由人員核對與主管核准。'),
    dict(start=25, end=35, label='03 / 人員與派工', title='把工作交給\n合適的人員', body=['核對技能、必要資格與出勤', '依剩餘容量推薦，主管確認派工'], image='quick-questions-desktop.png', crop=(254, 195, 1268, 890), subtitle='派工前核對資格、出勤與剩餘容量，讓推薦理由可以檢查。'),
    dict(start=35, end=46, label='04 / 排查與驗收', title='逐項記錄\n再確認真的修好', body=['排查結果與復測條件留在工單', '必填驗收通過，才能提交審核'], image='repair-flow-proof.png', crop=(249, 76, 1226, 670), subtitle='工程師依核准清單逐項記錄；必填驗收未通過，系統會阻擋提交。'),
    dict(start=46, end=54, label='05 / 審核與知識累積', title='讓一次維修\n成為下次的依據', body=['主管核對量測、照片與維修紀錄', '完成工單整理成案例，核對後發布'], image='repair-evidence-proof.png', crop=(90, 17, 605, 634), subtitle='主管審核後，完成案件可整理成案例；人工發布後供下一次檢索。'),
    dict(start=54, end=60, label='AI FACTORY / PredictFix AI', title='維修有依據\n交接有紀錄', body=['查找依據  →  合資格派工', '排查驗收  →  累積維修案例'], image='neon-equipment-desktop.png', crop=(1090, 510, 1492, 971), subtitle='AI Factory｜讓維修知識，回到每一次現場決策。'),
]

def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)

yy, xx = np.mgrid[0:H, 0:W]
glow = np.exp(-(((xx - 1520) / 760) ** 2 + ((yy - 350) / 720) ** 2))
arr = np.zeros((H, W, 3), dtype=np.uint8)
for c, (a, b) in enumerate([(6, 13), (17, 33), (30, 44)]):
    arr[:, :, c] = (a + glow * b).astype(np.uint8)
BG = Image.fromarray(arr)
BASES, SHOTS = [], []

for index, scene in enumerate(SCENES):
    im = BG.copy()
    d = ImageDraw.Draw(im)
    # Small grid and restrained cyan highlights keep the product UI central.
    for x in range(760, W, 80):
        d.line((x, 146, x, 895), fill='#142b3c', width=1)
    for y in range(175, 895, 80):
        d.line((755, y, 1863, y), fill='#142b3c', width=1)
    d.text((72, 43), 'AI FACTORY', font=font(29, True), fill=WHITE)
    d.text((287, 47), 'PredictFix AI', font=font(23), fill=CYAN)
    d.rounded_rectangle((1482, 40, 1848, 88), radius=24, fill='#143444', outline='#296070')
    d.text((1506, 48), '實際介面 · 虛構示範資料', font=font(22), fill='#b4e9e7')
    d.line((72, 116, 1848, 116), fill='#264052', width=2)
    d.text((72, 199), scene['label'], font=font(27, True), fill=CYAN)
    d.multiline_text((68, 265), scene['title'], font=font(67, True), fill=WHITE, spacing=23)
    d.line((74, 477, 170, 477), fill=CYAN, width=5)
    for j, line in enumerate(scene['body']):
        d.text((73, 516 + j * 53), line, font=font(27), fill=MUTED)
    pills = ['來源', '派工', '驗收', '案例']
    for j, label in enumerate(pills):
        x = 73 + j * 142
        active = (index == 2 and j == 0) or (index == 3 and j == 1) or (index == 4 and j == 2) or (index == 5 and j == 3) or index in (0, 6)
        d.rounded_rectangle((x, 724, x + 119, 782), radius=13, fill='#163645' if active else '#0c2233', outline='#2b7887' if active else '#203b4a')
        d.text((x + 29, 738), label, font=font(26), fill=CYAN if active else MUTED)
    d.text((73, 832), '本機 MVP · 人員核對與主管審核', font=font(22), fill='#8199ac')
    d.rounded_rectangle((735, 167, 1859, 887), radius=20, fill='#0b1c2b', outline='#366273', width=2)
    d.ellipse((757, 187, 769, 199), fill='#e37d85')
    d.ellipse((783, 187, 795, 199), fill='#d7be6a')
    d.ellipse((809, 187, 821, 199), fill='#54bdac')
    d.text((850, 178), 'PredictFix AI / DEMO', font=font(18), fill=MUTED)
    d.rounded_rectangle((72, 920, 1848, 1012), radius=17, fill='#112b3d', outline='#24485d')
    subtitle_font = font(30)
    bounds = d.textbbox((0, 0), scene['subtitle'], font=subtitle_font)
    d.text(((W - bounds[2]) / 2, 948), scene['subtitle'], font=subtitle_font, fill=WHITE)
    d.text((73, 1031), '60 秒產品介紹｜實際截圖剪輯', font=font(19), fill='#829aae')
    BASES.append(im)
    shot = Image.open(ROOT / 'artifacts' / scene['image']).convert('RGB').crop(scene['crop'])
    SHOTS.append(shot)

VW, VH, VX, VY = 1088, 653, 753, 217
def render_scene(index, progress):
    im = BASES[index].copy()
    shot = SHOTS[index]
    scale = max(VW / shot.width, VH / shot.height) * (1.012 + .025 * progress)
    sw, sh = math.ceil(shot.width * scale), math.ceil(shot.height * scale)
    shot = shot.resize((sw, sh), Image.Resampling.BICUBIC)
    x = round((sw - VW) * (.40 + .12 * progress))
    y = round((sh - VH) * (.36 + .24 * progress))
    im.paste(shot.crop((x, y, x + VW, y + VH)), (VX, VY))
    return im

def stamp(im, time):
    d = ImageDraw.Draw(im)
    d.line((72, 1071, 1848, 1071), fill='#1a3546', width=5)
    d.line((72, 1071, 72 + round(1776 * time / 60), 1071), fill=CYAN, width=5)
    d.text((1710, 1031), f'{int(time):02d} / 60 秒', font=font(19), fill=MUTED)
    return im

# Save the full-size preview frames and a compact contact sheet for visual QA.
contact = Image.new('RGB', (1280, 1440), '#071321')
for i, scene in enumerate(SCENES):
    preview = stamp(render_scene(i, .4), (scene['start'] + scene['end']) / 2)
    preview.save(OUT / f'scene-{i+1:02d}.jpg', quality=93)
    contact.paste(preview.resize((640, 360), Image.Resampling.LANCZOS), ((i % 2) * 640, (i // 2) * 360))
contact.save(OUT / 'storyboard.jpg', quality=94)
BASES[0].copy()
stamp(render_scene(0, .4), 2).save(OUT / 'poster.jpg', quality=95)
(OUT / 'storyboard.json').write_text(json.dumps(SCENES, ensure_ascii=False, indent=2), encoding='utf-8')

def srt_time(s):
    return f'00:00:{int(s):02d},000'
(OUT / 'AI-Factory-60s-zh-TW.srt').write_text('\n\n'.join(f"{i+1}\n{srt_time(s['start'])} --> {srt_time(s['end']) if s['end'] < 60 else '00:01:00,000'}\n{s['subtitle']}" for i, s in enumerate(SCENES)) + '\n', encoding='utf-8-sig')
if '--preview-only' in sys.argv:
    print(str(OUT / 'storyboard.jpg'))
    raise SystemExit(0)

# An original, softly pulsing instrumental bed; no borrowed music or voice.
SR = 48000
audio = np.zeros(SR * 60, dtype=np.float64)
chords = [(130.81, 164.81, 196.00), (110.00, 130.81, 164.81), (87.31, 110.00, 130.81), (98.00, 123.47, 146.83)]
for start in range(0, 60, 4):
    dur = min(5, 60-start)
    t = np.arange(SR*dur) / SR
    envelope = np.minimum(t / .5, 1) * np.minimum((dur-t) / 1.1, 1)
    signal = np.zeros_like(t)
    for freq in chords[(start//4) % 4]:
        signal += .023 * np.sin(2*np.pi*freq*t) + .009*np.sin(2*np.pi*(freq*2+.18)*t)
    signal *= envelope * (.87 + .13*np.cos(2*np.pi*.5*t))
    audio[start*SR:start*SR+len(t)] += signal
for k in range(120):
    start = k * .5
    t = np.arange(int(SR * .42)) / SR
    freq = [523.25, 659.25, 783.99, 659.25, 440, 523.25, 659.25, 523.25][k % 8]
    signal = .021*np.sin(2*np.pi*freq*t)*np.exp(-t*10)*np.minimum(t/.009,1)
    pos = int(start * SR)
    audio[pos:pos+len(t)] += signal
t = np.arange(len(audio))/SR
audio *= np.minimum(t/1.5,1)*np.minimum((60-t)/2,1)
stereo = np.column_stack((audio, .94*audio + .06*np.roll(audio, 370)))
with wave.open(str(OUT/'original-ambient.wav'), 'wb') as wf:
    wf.setnchannels(2)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes((np.clip(stereo,-1,1)*32767).astype('<i2').tobytes())

import imageio_ffmpeg
ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
cmd = [ffmpeg, '-y', '-hide_banner', '-loglevel', 'warning', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-i', str(OUT/'original-ambient.wav'), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', '-t', '60', '-movflags', '+faststart', '-metadata', 'title=AI Factory - PredictFix AI - 60 second product introduction', '-metadata', 'comment=Real project screenshots; synthetic demo data; edited screenshot tour.', str(OUT/'AI-Factory-60s-zh-TW.mp4')]
with (OUT/'encode.log').open('wb') as log:
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log)
    scene_index = 0
    for frame in range(FPS*60):
        time = frame/FPS
        while time >= SCENES[scene_index]['end'] and scene_index < len(SCENES)-1:
            scene_index += 1
        s = SCENES[scene_index]
        prog = (time-s['start'])/(s['end']-s['start'])
        im = render_scene(scene_index, prog)
        remaining = s['end']-time
        if remaining < .5 and scene_index < len(SCENES)-1:
            nxt = render_scene(scene_index+1, 0)
            blend = (1-remaining/.5)
            blend = blend*blend*(3-2*blend)
            im = Image.blend(im, nxt, blend)
        if time < .6:
            im = Image.blend(Image.new('RGB', (W,H), '#071321'), im, time/.6)
        if time > 59.6:
            im = Image.blend(im, Image.new('RGB', (W,H), '#071321'), (time-59.6)/.4)
        stamp(im, time)
        p.stdin.write(im.tobytes())
        if frame % (FPS*5) == 0:
            print(f'Rendered {int(time):02d}/60 seconds', flush=True)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError((OUT/'encode.log').read_text())
print(str(OUT/'AI-Factory-60s-zh-TW.mp4'), flush=True)
