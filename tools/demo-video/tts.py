"""Synthesize each narration segment with edge-tts and record its duration in build/timing.json."""
import asyncio
import json
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

import edge_tts

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def duration(path):
    info = subprocess.run([FFMPEG, '-hide_banner', '-i', str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r'Duration: (\d+):(\d+):([\d.]+)', info).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


async def main():
    cfg = json.loads((HERE / 'narration.json').read_text(encoding='utf-8'))
    (BUILD / 'audio').mkdir(parents=True, exist_ok=True)
    timing = []
    for seg in cfg['segments']:
        mp3 = BUILD / 'audio' / f"{seg['id']}.mp3"
        wav = mp3.with_suffix('.wav')
        await edge_tts.Communicate(seg['text'], cfg['voice'], rate=cfg['rate']).save(str(mp3))
        # Trim leading/trailing silence so segment timing reflects actual speech.
        subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(mp3), '-af',
                        'silenceremove=start_periods=1:start_threshold=-45dB,areverse,'
                        'silenceremove=start_periods=1:start_threshold=-45dB,areverse',
                        '-ar', '48000', '-ac', '2', str(wav)], check=True)
        speech = duration(wav)
        timing.append({**seg, 'audio': str(wav), 'speech': round(speech, 3),
                       'target': round(speech + cfg['pad_after'] + seg.get('hold', 0), 3)})
        print(f"{seg['id']:<14} {speech:5.2f}s  {seg['text']}")
    (BUILD / 'timing.json').write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding='utf-8')
    print('total', round(sum(t['target'] for t in timing), 2), 's')


if __name__ == '__main__':
    asyncio.run(main())
