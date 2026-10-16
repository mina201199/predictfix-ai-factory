"""Render synthetic machine nameplates for the scan demo and OCR evaluation.

The manufacturer, model and serial numbers are fictional. Text is ASCII only and uses
Pillow's bundled font, so Windows and CI render the same pixels without font licences.
"""
import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

VARIANTS=('clean','perspective','blur','glare','low_contrast')
SIZE=(900,440)
PLATE=(203,206,210)
INK=(22,24,28)


def font(size):
  return ImageFont.load_default(size=size)


def draw_plate(machineId,rng):
  image=Image.new('RGB',SIZE,PLATE)
  draw=ImageDraw.Draw(image)
  # 細橫紋模擬髮絲紋鋁板，讓辨識不是在完全乾淨的背景上進行
  for y in range(0,SIZE[1],3):
    shade=PLATE[0]+rng.randint(-6,6)
    draw.line([(0,y),(SIZE[0],y)],fill=(shade,shade+3,shade+7))
  draw.rectangle([12,12,SIZE[0]-12,SIZE[1]-12],outline=INK,width=5)
  for x,y in [(30,30),(SIZE[0]-30,30),(30,SIZE[1]-30),(SIZE[0]-30,SIZE[1]-30)]:
    draw.ellipse([x-8,y-8,x+8,y+8],outline=INK,width=3)
  serial=f'{rng.randint(20,25)}-{rng.randint(100,9999):04}'
  draw.text((60,40),'TAIHO MACHINERY CO.',fill=INK,font=font(40))
  draw.text((60,108),f'MODEL VMC-850    SERIAL No. {serial}',fill=INK,font=font(30))
  draw.line([(60,160),(SIZE[0]-60,160)],fill=INK,width=2)
  draw.text((60,178),'MACHINE ID',fill=INK,font=font(30))
  draw.text((60,215),machineId,fill=INK,font=font(112))
  draw.text((60,370),f'3PH 220V 60Hz    MFG 20{rng.randint(18,25)}-{rng.randint(1,12):02}',fill=INK,font=font(28))
  return image


def perspective(image,rng):
  width,height=image.size
  shift=rng.uniform(0.05,0.09)
  # 模擬斜角拍攝：右側往內縮、上下略為傾斜
  source=[(0,0),(width,height*shift),(width,height*(1-shift)),(0,height)]
  target=[(0,0),(width,0),(width,height),(0,height)]
  return image.transform(image.size,Image.Transform.PERSPECTIVE,coefficients(target,source),
                         Image.Resampling.BICUBIC,fillcolor=(90,92,96))


def coefficients(target,source):
  import numpy as np
  rows=[]
  for (x,y),(u,v) in zip(target,source):
    rows.append([x,y,1,0,0,0,-u*x,-u*y])
    rows.append([0,0,0,x,y,1,-v*x,-v*y])
  return np.linalg.solve(np.array(rows,dtype=float),np.array([c for point in source for c in point],dtype=float)).tolist()


def glare(image,rng):
  overlay=Image.new('L',image.size,0)
  draw=ImageDraw.Draw(overlay)
  x=rng.randint(350,650)
  draw.ellipse([x-220,-120,x+220,260],fill=150)
  overlay=overlay.filter(ImageFilter.GaussianBlur(60))
  return Image.composite(Image.new('RGB',image.size,(250,250,250)),image,overlay)


def render_nameplate(machineId,variant='clean',seed=0):
  if variant not in VARIANTS:raise ValueError('Unknown variant: '+variant)
  rng=random.Random(f'{machineId}:{seed}')
  image=draw_plate(machineId,rng)
  if variant=='perspective':image=perspective(image,rng)
  elif variant=='blur':image=image.filter(ImageFilter.GaussianBlur(2.2))
  elif variant=='glare':image=glare(image,rng)
  elif variant=='low_contrast':image=ImageEnhance.Brightness(ImageEnhance.Contrast(image).enhance(0.35)).enhance(1.15)
  return image


def print_sheet(images,columns=3):
  width,height=SIZE[0]//2,SIZE[1]//2
  rows=(len(images)+columns-1)//columns
  sheet=Image.new('RGB',(columns*width+(columns+1)*20,rows*height+(rows+1)*20),(255,255,255))
  for index,image in enumerate(images):
    sheet.paste(image.resize((width,height)),(20+(index%columns)*(width+20),20+(index//columns)*(height+20)))
  return sheet


def main():
  parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--out',type=Path,default=Path('artifacts/demo-nameplates'))
  parser.add_argument('--count',type=int,default=18)
  args=parser.parse_args()
  args.out.mkdir(parents=True,exist_ok=True)
  images=[]
  for n in range(1,args.count+1):
    image=render_nameplate(f'CNC-{n:02}')
    image.save(args.out/f'CNC-{n:02}.png',optimize=True)
    images.append(image)
  print_sheet(images).save(args.out/'print-sheet.png',optimize=True)
  print(f'{len(images)} nameplates written to {args.out}')


if __name__=='__main__':
  main()
