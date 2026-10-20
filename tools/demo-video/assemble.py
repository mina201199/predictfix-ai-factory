"""Build the final video from captured frames, narration and captions.

Each segment's frames are retimed to its narration target, segments are joined with short
crossfades, then captions/step badges (ASS) are burned in and the narration is mixed under it.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
OUT = HERE / 'output'
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 30
XFADE = 0.3
VOICE_LEAD = 0.15
TAIL = 0.4
CARDS = {'s0_title', 's8_end'}
# Push in on a key detail near the end of a segment: focus point (1920x1080 px), zoom, seconds before the cut.
ZOOMS = {'s4_blocked': {'focus': (520, 66), 'zoom': 2.0, 'from_end': 1.7}}


def run(*args):
    subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', *map(str, args)], check=True)


def clip(mark, extra):
    """Encode one segment: frames in [start, end] stretched to the target, plus `extra` held seconds."""
    frames = json.loads((BUILD / 'frames' / mark['clip'] / 'index.json').read_text(encoding='utf-8'))
    start, end = mark['start'], mark['end']
    before = [f for f in frames if f[0] <= start]
    inside = [f for f in frames if start < f[0] < end]
    chosen = ([[start, before[-1][1]]] if before else []) + inside
    if not chosen:
        chosen = [[start, frames[0][1]]]
    chosen[0][0] = start
    factor = mark['target'] / (end - start)
    folder = (BUILD / 'frames' / mark['clip']).as_posix()
    lines = ['ffconcat version 1.0']
    for (t, name), nxt in zip(chosen, [c[0] for c in chosen[1:]] + [end]):
        lines += [f"file '{folder}/{name}'", f'duration {max(nxt - t, 0.001) * factor:.4f}']
    lines += [f"file '{folder}/{chosen[-1][1]}'", f'duration {extra + 0.05:.4f}', f"file '{folder}/{chosen[-1][1]}'"]
    listing = BUILD / 'seg' / f"{mark['id']}.txt"
    listing.write_text('\n'.join(lines), encoding='utf-8')
    out = listing.with_suffix('.mp4')
    vf = f'fps={FPS},scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv:in_color_matrix=bt601:out_color_matrix=bt709'
    if mark['id'] in ZOOMS:
        z = ZOOMS[mark['id']]
        (fx, fy), t0 = z['focus'], mark['target'] - z['from_end']
        ease = f"st(0,clip((it-{t0:.3f})/0.5,0,1));1+{z['zoom'] - 1}*ld(0)*ld(0)*(3-2*ld(0))"
        vf += f",zoompan=z='{ease}':x='{fx}*(1-1/zoom)':y='{fy}*(1-1/zoom)':d=1:s=1920x1080:fps={FPS}"
    run('-f', 'concat', '-safe', '0', '-i', listing,
        '-vf', vf + ',format=yuv420p',
        '-t', f"{mark['target'] + extra:.3f}", '-c:v', 'libx264', '-crf', '14', '-preset', 'fast', '-color_range', 'tv', '-colorspace', 'bt709', out)
    return out


def ass_time(t):
    cs = round(t * 100)
    return f'{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}'


def chunks(text, limit=18):
    """Split narration into caption lines: always at 。？；, and at commas when a line would run long."""
    out = []
    for sentence in [s for s in re.split(r'(?<=[。；？])', text) if s]:
        cur = ''
        for p in [p for p in re.split(r'(?<=[，、])', sentence) if p]:
            if cur and len(cur) + len(p) > limit:
                out.append(cur)
                cur = ''
            cur += p
        out.append(cur)
    return [c.rstrip('，。；、') for c in out]


def subtitles(timing, offsets, total):
    head = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Microsoft JhengHei,46,&H00FFFFFF,&H00FFFFFF,&H30140B06,&H00000000,1,0,0,0,100,100,1,0,3,16,0,2,60,60,46,1
Style: Step,Microsoft JhengHei,30,&H00EED322,&H00FFFFFF,&H10301F0D,&H00000000,1,0,0,0,100,100,1,0,3,14,0,9,40,40,30,1
Style: Demo,Microsoft JhengHei,21,&H00BDB08F,&H00FFFFFF,&H10301F0D,&H00000000,0,0,0,0,100,100,0,0,3,10,0,9,40,40,92,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    app = [(s, o) for s, o in zip(timing, offsets) if s['id'] not in CARDS]
    first, last = app[0][1], app[-1][1] + app[-1][0]['target']
    events.append(f'Dialogue: 1,{ass_time(first + XFADE)},{ass_time(last)},Demo,,0,0,0,,虛構展示資料 · 本機運行')
    for seg, off in app:
        events.append(f"Dialogue: 1,{ass_time(off + 0.1)},{ass_time(off + seg['target'] + 0.05)},Step,,0,0,0,,{seg['step']}")
        pieces = chunks(seg['text'])
        t0, span = off + VOICE_LEAD, seg['speech']
        weights = [len(p) for p in pieces]
        acc = 0
        for p, w in zip(pieces, weights):
            a = t0 + span * acc / sum(weights)
            acc += w
            b = t0 + span * acc / sum(weights) + (0.25 if acc == sum(weights) else 0)
            events.append(f'Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,,0,0,0,,{p}')
    path = BUILD / 'captions.ass'
    path.write_text(head + '\n'.join(events) + '\n', encoding='utf-8-sig')
    return path


def main():
    OUT.mkdir(exist_ok=True)
    (BUILD / 'seg').mkdir(exist_ok=True)
    timing = json.loads((BUILD / 'timing.json').read_text(encoding='utf-8'))
    marks = {m['id']: m for m in json.loads((BUILD / 'marks.json').read_text(encoding='utf-8'))}
    for seg in timing:
        m = marks[seg['id']]
        m['target'] = seg['target']
        speed = (m['end'] - m['start']) / m['target']
        print(f"{seg['id']:<14} speed x{speed:.2f}")

    offsets, acc = [], 0.0
    for seg in timing:
        offsets.append(acc)
        acc += seg['target']
    total = acc
    clips = [clip(marks[s['id']], XFADE if i < len(timing) - 1 else TAIL) for i, s in enumerate(timing)]

    # Fonts for libass: copy the system CJK font next to the build so rendering doesn't depend on fontconfig.
    fonts = BUILD / 'fonts'
    fonts.mkdir(exist_ok=True)
    for name in ['msjh.ttc', 'msjhbd.ttc']:
        if not (fonts / name).exists():
            shutil.copy(Path(r'C:\Windows\Fonts') / name, fonts / name)
    ass = subtitles(timing, offsets, total)

    inputs, graph, last = [], [], '[0:v]'
    for c in clips:
        inputs += ['-i', c]
    for i in range(1, len(clips)):
        graph.append(f'{last}[{i}:v]xfade=transition=fade:duration={XFADE}:offset={offsets[i]:.3f}[v{i}]')
        last = f'[v{i}]'
    rel = lambda p: p.relative_to(HERE).as_posix()
    graph.append(f"{last}subtitles={rel(ass)}:fontsdir={rel(fonts)},fade=t=out:st={total + TAIL - 0.6:.3f}:d=0.6[vout]")
    audio_in = len(clips)
    for seg in timing:
        inputs += ['-i', seg['audio']]
    delays = [f"[{audio_in + i}:a]adelay={round((o + VOICE_LEAD) * 1000)}:all=1[a{i}]" for i, o in enumerate(offsets)]
    graph += delays
    graph.append(''.join(f'[a{i}]' for i in range(len(timing))) +
                 f'amix=inputs={len(timing)}:normalize=0,apad,atrim=0:{total + TAIL:.3f},loudnorm=I=-16:TP=-1.5:LRA=11[aout]')
    final = OUT / 'predictfix-demo.mp4'
    subprocess.run([FFMPEG, '-y', '-hide_banner', '-loglevel', 'error', *map(str, inputs),
                    '-filter_complex', ';'.join(graph), '-map', '[vout]', '-map', '[aout]',
                    '-c:v', 'libx264', '-crf', '18', '-preset', 'slow', '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                    '-r', str(FPS), '-color_range', 'tv', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                    '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart',
                    '-t', f'{total + TAIL:.3f}', str(final)], check=True, cwd=HERE)
    print('wrote', final, f'{total + TAIL:.2f}s')
    previews(final, timing, offsets)


def previews(final, timing, offsets):
    """README GIF of the blocked-submit moment, plus a title-card thumbnail."""
    at = {s['id']: o for s, o in zip(timing, offsets)}
    start, end = at['s4_blocked'], at['s5_retest']
    gif = OUT / 'predictfix-preview.gif'
    run('-ss', f'{start + 0.1:.2f}', '-to', f'{end:.2f}', '-i', final, '-filter_complex',
        'fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=192:stats_mode=diff[p];'
        '[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle', '-loop', '0', gif)
    run('-ss', f"{at['s0_title'] + 5.2:.2f}", '-i', final, '-frames:v', '1', OUT / 'predictfix-thumbnail.png')
    print('wrote', gif, 'and thumbnail')


if __name__ == '__main__':
    main()
