"""Drive the local Vulkrion demo and capture frames, paced to the narration in build/timing.json.

Frames come from the Chrome DevTools screencast (JPEG, 1920x1080) and are stored with their
arrival time; build/marks.json records where each narration segment starts and ends.
"""
import asyncio
import base64
import json
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build'
REPO = HERE.parents[1]
BASE = 'http://127.0.0.1:8082'
VIEW = {'width': 1440, 'height': 810}
SCALE = 4 / 3  # 1440x810 CSS px -> 1920x1080 frames
GREEN, RED, CYAN, AMBER = '#34d399', '#f87171', '#22d3ee', '#fbbf24'


class Recorder:
    """CDP screencast of one page into build/frames/<name>/."""

    def __init__(self, page, name):
        self.page, self.name = page, name
        self.dir = BUILD / 'frames' / name
        self.dir.mkdir(parents=True, exist_ok=True)
        for old in self.dir.glob('*.jpg'):
            old.unlink()
        self.frames = []

    async def start(self):
        self.cdp = await self.page.context.new_cdp_session(self.page)
        self.cdp.on('Page.screencastFrame', self._frame)
        await self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92,
                                                     'maxWidth': 1920, 'maxHeight': 1080, 'everyNthFrame': 1})

    def _frame(self, params):
        at = time.time()
        name = f'{len(self.frames):06d}.jpg'
        (self.dir / name).write_bytes(base64.b64decode(params['data']))
        self.frames.append([at, name])
        asyncio.ensure_future(self.cdp.send('Page.screencastFrameAck', {'sessionId': params['sessionId']}))

    async def stop(self):
        await self.cdp.send('Page.stopScreencast')
        (self.dir / 'index.json').write_text(json.dumps(self.frames), encoding='utf-8')


class Timeline:
    def __init__(self):
        self.timing = {s['id']: s for s in json.loads((BUILD / 'timing.json').read_text(encoding='utf-8'))}
        self.marks = []

    @asynccontextmanager
    async def segment(self, page, rec, sid):
        target = self.timing[sid]['target']
        start = time.time()

        async def until(fraction):
            wait = start + fraction * target - time.time()
            if wait > 0:
                await page.wait_for_timeout(wait * 1000)

        yield until
        await until(1.0)
        end = time.time()
        self.marks.append({'id': sid, 'clip': rec.name, 'start': start, 'end': end, 'target': target})
        print(f'{sid:<14} raw {end - start:5.2f}s  target {target:5.2f}s', flush=True)


# ---------- on-screen actions ----------

def L(page, target, text=None):
    loc = page.locator(target) if isinstance(target, str) else target
    return (loc.filter(has_text=text) if text else loc).first


async def into_view(page, loc):
    moved = await loc.evaluate("""el => { const r = el.getBoundingClientRect();
        if (r.top >= 90 && r.bottom <= innerHeight - 140) return false;
        __demo.clear(); el.style.scrollMarginTop = '96px';
        el.scrollIntoView({behavior: 'smooth', block: r.height > innerHeight - 260 ? 'start' : 'center'}); return true; }""")
    if moved:
        await page.wait_for_timeout(650)


async def point(page, loc, ms=320):
    await into_view(page, loc)
    b = await loc.bounding_box()
    x, y = b['x'] + min(b['width'] / 2, 70), b['y'] + b['height'] / 2
    await page.evaluate('([x, y, ms]) => __demo.move(x, y, ms)', [x, y, ms])
    await page.wait_for_timeout(ms + 30)


async def click(page, target, text=None, after=160):
    loc = L(page, target, text)
    await point(page, loc)
    await page.evaluate('__demo.ripple()')
    await loc.click()
    await page.wait_for_timeout(after)


async def type_in(page, target, value, delay=35, replace=False):
    loc = L(page, target)
    await click(page, loc, after=60)
    if replace:
        await loc.fill('')
    await loc.press_sequentially(value, delay=delay)


async def fill_at(page, target, value):
    loc = L(page, target)
    await click(page, loc, after=60)
    await loc.fill(value)
    await page.wait_for_timeout(150)


async def choose(page, target, value):
    loc = L(page, target)
    await point(page, loc)
    await page.evaluate('__demo.ripple()')
    await loc.select_option(value)
    await page.wait_for_timeout(200)


async def spot(page, target, color=AMBER, text=None, view=True):
    loc = L(page, target, text)
    if view:
        await into_view(page, loc)
    await loc.evaluate('(el, c) => __demo.spot(el, c)', color)


async def clear(page):
    await page.evaluate('__demo.clear()')


async def notice(page, text, timeout=60000):
    await page.wait_for_function('t => document.querySelector("#notice")?.textContent.includes(t)', arg=text, timeout=timeout)


async def scroll_top(page):
    await page.evaluate("""() => { __demo.clear(); for (const el of [document.scrollingElement, ...document.querySelectorAll('main,.main')])
        el && el.scrollTo({top: 0, behavior: 'smooth'}); }""")
    await page.wait_for_timeout(500)


async def login(page, role, path='/workflow.html'):
    """Off-camera role switch through the demo quick-login."""
    pos = await page.evaluate('__demo.pos()') if await page.evaluate('!!window.__demo') else {'x': 900, 'y': 500}
    if await page.get_by_role('button', name='登出').count():
        async with page.expect_navigation():
            await page.get_by_role('button', name='登出').click()
    if not page.url.endswith(path):
        await page.goto(BASE + path)
    await page.locator(f'[data-demo-login={role}]').first.click()
    await notice(page, '已載入')
    await page.evaluate('([x, y]) => __demo.place(x, y)', [pos['x'], pos['y']])


async def card(ctx, tl, sid, html):
    page = await ctx.new_page()
    await page.goto((HERE / 'cards' / html).as_uri())
    rec = Recorder(page, sid)
    await rec.start()
    async with tl.segment(page, rec, sid):
        pass
    await page.wait_for_timeout(400)
    await rec.stop()
    await page.close()


# ---------- the story ----------

async def story(page, tl, rec):
    photo = BUILD / 'cnc-03-after-repair.jpg'
    csv = REPO / 'demo-measurements.csv'

    async with tl.segment(page, rec, 's1_report') as until:
        await choose(page, '#report-machine', 'CNC-03')
        await fill_at(page, '#report-form [name=machine_model]', 'PF-VMC850-DEMO')
        await type_in(page, '#report-form [name=symptoms]', '換刀卡住，只發生在特定刀位', delay=45)
        await click(page, 'button[value=analyze]')
        await page.wait_for_selector('#comparison .tag', timeout=90000)
        await page.locator('#comparison').evaluate("el => { el.style.scrollMarginTop = '96px'; el.scrollIntoView({behavior: 'smooth', block: 'start'}); }")
        await page.wait_for_timeout(650)
        await spot(page, '#comparison .tag', CYAN, view=False)
        await spot(page, '#comparison ul', AMBER, view=False)
        await page.wait_for_timeout(1300)
        await clear(page)
        await click(page, '#comparison .candidate summary', after=300)
        await spot(page, '#comparison .candidate .source', CYAN)
        await page.wait_for_timeout(900)

    # Off camera: save the report as a work order, then return to the compared sources.
    await clear(page)
    await page.locator('#save-report').click()
    await notice(page, '已建立待指派工單')
    ticket = re.search(r'工單 (\S+?)，', await page.locator('#report-status').text_content()).group(1)
    await page.locator('[data-panel=report]').click()
    await page.locator('#comparison [data-use-source="0"]').evaluate("el => el.scrollIntoView({block: 'center'})")
    await page.wait_for_timeout(300)

    async with tl.segment(page, rec, 's2_checklist') as until:
        await click(page, '#comparison [data-use-source="0"]', after=400)
        await spot(page, '#order-detail details', CYAN)
        await page.wait_for_timeout(500)
        await type_in(page, '#step-editors .edit-step:nth-child(2) [name=criterion]', '連續換刀 20 次無卡刀，刀號與刀位一致', delay=14)
        await fill_at(page, '#procedure-form [name=approval_note]', '已核對 ATC-002 第 04 節，適用本機型')
        await click(page, '#procedure-form button.primary')
        await notice(page, '核准清單已加入工單')
        await page.locator('#order-detail').evaluate("el => { el.style.scrollMarginTop = '96px'; el.scrollIntoView({behavior: 'smooth', block: 'start'}); }")
        await page.wait_for_timeout(600)
        await spot(page, '#order-detail .step.inspect', GREEN, view=False)
        await spot(page, '#order-detail .step.verify', AMBER, view=False)
        await page.wait_for_timeout(1000)

    # Off camera: estimate and required qualification.
    await clear(page)
    await L(page, '#order-summary .order-actions button', '估時與資格').click()
    await page.fill('#estimate-form [name=remaining_minutes]', '60')
    await page.fill('#estimate-form [name=qualifications]', 'ATC 換刀機構維修')
    await page.fill('#estimate-form [name=note]', '依核准清單估 60 分鐘')
    await page.locator('#estimate-form button.primary').click()
    await notice(page, '估時與資格已保存')
    await scroll_top(page)

    async with tl.segment(page, rec, 's3_dispatch') as until:
        await spot(page, '#order-summary p', CYAN)
        await page.wait_for_timeout(600)
        await click(page, '#order-summary .order-actions button', '合資格與容量派工', after=400)
        await page.wait_for_selector('#rank-list article')
        await spot(page, '#rank-list article', GREEN, text='可派工')
        await page.wait_for_timeout(900)
        await spot(page, '#rank-list li', RED, text='資格缺少')
        await spot(page, '#rank-list li', RED, text='出勤：leave', view=False)
        await page.wait_for_timeout(1200)
        await clear(page)
        await click(page, '#rank-list button', '指派給 Amy Chen')
        await notice(page, '已指派工程師')

    # Off camera: switch to the assigned engineer and start the job.
    await login(page, 'engineer')
    await page.locator('[data-panel=orders]').click()
    await page.select_option('#order-select', ticket)
    await L(page, '#order-summary .order-actions button', '開始維修').click()
    await notice(page, '已開始維修')
    await L(page, '#order-summary .order-actions button', '逐項記錄結果').click()
    await page.locator('[data-step-id]').nth(0).locator('[name=outcome]').select_option('pass')
    await page.locator('[data-step-id]').nth(0).locator('[name=note]').fill('第 7 刀位資料不一致，已修正')
    await page.locator('#results-form').evaluate("el => { el.style.scrollMarginTop = '96px'; el.scrollIntoView({block: 'start'}); }")
    await page.wait_for_timeout(300)

    async with tl.segment(page, rec, 's4_blocked') as until:
        await spot(page, page.locator('[data-step-id]').nth(0), GREEN, view=False)
        await page.wait_for_timeout(600)
        await clear(page)
        await choose(page, page.locator('[data-step-id]').nth(1).locator('[name=outcome]'), 'fail')
        await type_in(page, page.locator('[data-step-id]').nth(1).locator('[name=note]'), '復測第 3 次仍卡刀', delay=20)
        await click(page, '#results-form button.primary')
        await notice(page, '逐項結果已保存')
        await click(page, '#order-summary .order-actions button', '提交復測與維修證據', after=150)
        await fill_at(page, '#submit-form [name=note]', '已修正刀位資料')
        await click(page, '#submit-form button.primary')
        await notice(page, '尚有未通過')
        await spot(page, '#notice', RED, view=False)
        await page.wait_for_timeout(1800)

    async with tl.segment(page, rec, 's5_retest') as until:
        await clear(page)
        await click(page, '#order-summary .order-actions button', '逐項記錄結果', after=200)
        await choose(page, page.locator('[data-step-id]').nth(1).locator('[name=outcome]'), 'pass')
        await type_in(page, page.locator('[data-step-id]').nth(1).locator('[name=note]'), '連續換刀 20 次無卡刀', delay=14, replace=True)
        await click(page, '#results-form button.primary')
        await notice(page, '逐項結果已保存')
        await click(page, '#order-summary .order-actions button', '提交復測與維修證據', after=150)
        await page.fill('#submit-form [name=note]', '修正第 7 刀位資料；20 次換刀復測通過')
        await page.set_input_files('#measurements', str(csv))
        await point(page, L(page, '#proof-photos'))
        await page.set_input_files('#proof-photos', str(photo))
        await click(page, '#submit-form button.primary')
        await notice(page, '已提交主管審核')
        await spot(page, '#notice', GREEN, view=False)
        await page.wait_for_timeout(1100)

    # Off camera: back to the supervisor.
    await login(page, 'supervisor')
    await page.locator('[data-panel=orders]').click()
    await page.select_option('#order-select', ticket)

    async with tl.segment(page, rec, 's6_review') as until:
        await click(page, '#order-summary .order-actions button', '主管審核', after=250)
        await spot(page, '#order-detail img.photo', CYAN)
        await page.wait_for_timeout(400)
        await fill_at(page, '#review-form [name=note]', '證據齊全，同意結案')
        await click(page, '#review-form button.primary')
        await notice(page, '工單已完成')
        await spot(page, '#notice', GREEN, view=False)
        await page.wait_for_timeout(700)

    # Off camera: create the case draft, fill in what the draft leaves open, save it.
    await L(page, '#order-summary .order-actions button', '累積為維修案例').click()
    await page.wait_for_url('**/knowledge.html')
    await page.wait_for_function('document.querySelector("#notice")?.textContent.includes("已載入")')
    await page.locator('[data-panel=cases]').click()
    await page.locator('[data-case]').first.click()
    for name, value in {'component': '換刀機構／刀位資料', 'conditions': '新增刀具後，僅第 7 刀位換刀卡住',
                        'findings': '刀具主檔與第 7 刀位資料不一致',
                        'verification': '連續換刀 20 次無卡刀，刀號與刀位一致'}.items():
        await page.fill(f'#case-form [name={name}]', value)
    await page.locator('#case-form button.primary').click()
    await page.wait_for_function('document.querySelector("#notice")?.textContent === "已完成"')
    await page.locator('#publish-case').evaluate("el => el.scrollIntoView({block: 'center'})")
    await page.wait_for_timeout(300)

    async with tl.segment(page, rec, 's7_case') as until:
        await click(page, '#publish-case', after=300)
        await page.wait_for_selector('#withdraw-case')
        await scroll_top(page)
        await spot(page, '#case-editor .pill', GREEN, view=False)
        await page.wait_for_timeout(600)
        await clear(page)
        await click(page, '[data-panel=assist]', after=150)
        await click(page, '[data-example]', '換刀卡住', after=100)
        await click(page, '#ask-form button.primary', after=100)
        await page.wait_for_function('document.querySelector("#answer .tag")', timeout=90000)
        case_source = page.locator('#answer details.source').filter(has_text='原工單').first
        if not await case_source.count():
            case_source = page.locator('#answer details.source').first
        await case_source.evaluate("el => { el.open = true; el.style.scrollMarginTop = '96px'; el.scrollIntoView({behavior: 'smooth', block: 'start'}); }")
        await page.wait_for_timeout(600)
        await spot(page, case_source, GREEN, view=False)
        await page.wait_for_timeout(1300)


async def main():
    BUILD.mkdir(exist_ok=True)
    tl = Timeline()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport=VIEW, device_scale_factor=SCALE, locale='zh-TW', timezone_id='Asia/Taipei')
        await ctx.add_init_script(path=str(HERE / 'overlay.js'))
        await card(ctx, tl, 's0_title', 'title.html')

        page = await ctx.new_page()
        await page.goto(BASE + '/workflow.html')
        await login(page, 'supervisor')
        await page.evaluate('__demo.place(1100, 430)')
        rec = Recorder(page, 'app')
        await rec.start()
        await page.wait_for_timeout(500)
        try:
            await story(page, tl, rec)
        except Exception:
            await page.screenshot(path=str(BUILD / 'failure.png'))
            raise
        finally:
            await page.wait_for_timeout(400)
            await rec.stop()
            (BUILD / 'marks.json').write_text(json.dumps(tl.marks, indent=2), encoding='utf-8')

        await card(ctx, tl, 's8_end', 'end.html')
        (BUILD / 'marks.json').write_text(json.dumps(tl.marks, indent=2), encoding='utf-8')
        await browser.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
