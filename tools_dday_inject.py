"""검토서 D-day 자동화: 각 검토서의 D-day 요소에 data-deadline을 달고 dday.js를 연결한다.
재실행해도 안전(idempotent). 새 검토서를 추가한 뒤 다시 돌리면 된다:  python tools_dday_inject.py"""
import re, glob, json, sys
sys.stdout.reconfigure(encoding='utf-8')
reg = {p['file']: p for p in json.load(open('data-full.json', encoding='utf-8'))['programs']}
NONDATE = re.compile(r'상시|소진|수시')
STRIP = re.compile(r'(<div class="(?:dday-strip|dday)(?: (?:urgent|warning|closed))?")(?: data-deadline="[^"]*")?(>)')
tagged, skipped, mism = [], [], []
for f in sorted(glob.glob('[0-9]*.html')):
    s = open(f, encoding='utf-8', newline='').read()
    p = reg.get(f, {})
    iso, disp = p.get('deadline_iso'), p.get('deadline_display') or ''
    m = STRIP.search(s)
    if not m: skipped.append((f, '마감 표시 요소 없음')); continue
    if not iso or NONDATE.search(disp): skipped.append((f, f'날짜 없는 마감({disp or "미등록"})')); continue
    strip_txt = re.sub(r'<[^>]+>', ' ', s[m.end():m.end() + 600])
    head = strip_txt.split()
    if '상시' in strip_txt[:120]:
        skipped.append((f, '날짜 없는 마감(표시: 상시)')); continue
    if head and not re.match(r'(D[-−]|D&minus;|CLOSED|마감)', head[0]):
        skipped.append((f, f'날짜 없는 마감(표시: {head[0]})')); continue
    # 검수: 페이지 표기 마감일과 레지스트리 마감일 비교
    strip_txt = re.sub(r'<[^>]+>', ' ', s[m.end():m.end() + 600])
    y, mo, d = map(int, iso[:10].split('-'))
    pats = [f'{mo}.{d}', f'{mo:02d}.{d:02d}', f'{mo}/{d}', f'{mo}월 {d}일']
    if not any(re.search(r'(?<!\d)' + re.escape(x) + r'(?!\d)', strip_txt) for x in pats):
        mism.append((f, iso[:16], ' '.join(strip_txt.split())[:90]))
    s = s[:m.start()] + m.group(1) + f' data-deadline="{iso}"' + m.group(2) + s[m.end():]
    if 'src="dday.js"' not in s:
        s = re.sub(r'</body>', '<script src="dday.js" defer></script>\n</body>', s, count=1)
    open(f, 'w', encoding='utf-8', newline='').write(s)
    tagged.append(f)
print(f'자동 계산 연결 {len(tagged)}건, 제외 {len(skipped)}건, 마감일 불일치 의심 {len(mism)}건')
for x in skipped: print('  제외', *x)
for x in mism: print('  불일치', *x)
