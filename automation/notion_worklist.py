#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
검토서 워크리스트 생성기 (자동화 입력 큐)

노션 "정책정보 크롤링 DB"에서 뽑은 공고 행(JSON)을 입력으로 받아,
'검토서 안 만든 진행 중 기업마당 공고'만 걸러 번호 목록으로 보여준다.

[입력 rows JSON] — 노션 MCP 쿼리 결과를 그대로 저장한 배열. 각 원소:
  {"key": "PBLN_...", "name": "...", "deadline": "YYYY-MM-DD"|null, "status": "진행중|마감|예정|상시"}
  (URL은 key에서 재구성)

[필터]
  - 상태 == 진행중 (기본; --status all 로 해제)
  - 신청마감일 >= 오늘  (※ 노션 '상태'가 스테일할 수 있어 마감일로 실제 진행 여부 재확인)
  - 판별키 중복 제외: pblancId가 허브 data-full.json 항목의 source_url에 있음 (= 이미 검토서 있음)
  - 제목 중복 제외: 예전 검토서엔 source_url이 없어 판별키로 못 잡는다. 사업명을 정규화([지역]접두·
    회차·"공고/모집/지원사업" 제거) 후 검토서 제목과 유사도 대조(>=0.85)해 '이미 검토서 있는 공고'를 제외.
    ※ 1차/2차·연장·후속처럼 **회차가 다르면 다른 공고**로 보아 자동 제외하지 않고 남기되 ⚠로 표시한다.

사용:  python notion_worklist.py <rows.json> [--today YYYY-MM-DD] [--status 진행중|all]
"""
import json, os, re, argparse, unicodedata
from datetime import date
from difflib import SequenceMatcher

for _s in (__import__("sys").stdout, __import__("sys").stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

# <레포>/automation/ 기준으로 레포 루트 자동 산출 (다른 PC/경로 이식성)
REPO = os.environ.get("GH_POLICY_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data-full.json")
BIZ_URL = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={}"
SIM_THRESHOLD = 0.85   # 제목 정규화 유사도 문턱 (실측 확정: 이 값에서 확실중복/신규가 깔끔히 갈림)

# 회차·연장·후속 등 "같은 사업의 다른 회차" 표지 (다르면 다른 공고로 취급)
_ROUND = re.compile(r'제?\s*\d+\s*차|제?\s*\d+\s*회|\d+\s*기|\d+\s*단계|추가|연장|재공고|수정|변경|후속|상반기|하반기')


def _rounds(t):
    return tuple(sorted(re.sub(r'\s+', '', m) for m in _ROUND.findall(t or "")))


def _base(t):
    """제목 정규화: [지역]접두·회차·상투어("공고/모집/지원사업" 등)·기호·연도 제거."""
    t = unicodedata.normalize('NFC', t or "")
    t = re.sub(r'^\[[^\]]*\]', '', t)          # [경기]/[서울] 접두 제거
    t = _ROUND.sub('', t)                       # 회차 토큰 제거(비교 base에서만; 회차 판별은 _rounds가 별도)
    t = re.sub(r'(참여|참가|참가자|참여자|참여업소|수혜|수요|대상)?기업\s*모집|참가자\s*모집|모집\s*(재)?공고|모집공고|신청\s*공고|시행계획\s*공고|시행\s*공고|계획\s*공고|사업\s*공고|공고|모집|신청|접수|참여기업|참가기업|지원사업|사업|지원|프로그램|20\d\d년?', '', t)
    t = re.sub(r'[\s\(\)\[\]ㆍ·,\.\-—~/:’\'\"!]+', '', t)
    return t.lower()


def load_hub():
    """허브 data-full.json → (검토서 판별키 집합, [(base, rounds, title)])"""
    d = json.load(open(DATA, encoding="utf-8"))
    keys, reviews = set(), []
    for p in d["programs"]:
        m = re.search(r"PBLN_[0-9]+", p.get("source_url") or "")
        if m:
            keys.add(m.group(0))
        ti = p["title"]
        reviews.append((_base(ti), _rounds(ti), ti))
    return keys, reviews


def title_match(name, reviews):
    """사업명을 검토서 제목과 정규화 대조. 최고 매칭 (검토서제목, 유사도, 회차동일여부) 또는 None."""
    b, rd = _base(name), _rounds(name)
    if not b:
        return None
    best = None
    for rb, rr, ti in reviews:
        if not rb:
            continue
        s = SequenceMatcher(None, b, rb).ratio()
        if best is None or s > best[1]:
            best = (ti, s, rr)
    if best and best[1] >= SIM_THRESHOLD:
        return (best[0], round(best[1], 2), best[2] == rd)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--status", default="진행중")
    args = ap.parse_args()

    ty, tm, td = map(int, args.today.split("-"))
    tdate = date(ty, tm, td)
    reviewed_keys, reviews = load_hub()
    rows = json.load(open(args.rows, encoding="utf-8"))

    out = []
    exc_rev = exc_title = exc_status = exc_past = 0
    for r in rows:
        k, st, dl, nm = r["key"], r.get("status"), r.get("deadline"), r.get("name", "")
        if args.status != "all" and st != args.status:
            exc_status += 1; continue
        if dl and dl < args.today:
            exc_past += 1; continue
        if k in reviewed_keys:                 # 판별키 중복
            exc_rev += 1; continue
        m = title_match(nm, reviews)
        if m and m[2]:                          # 제목 일치 + 회차 동일 → 확실 중복(제외)
            exc_title += 1; continue
        dd = None
        if dl:
            y, mo, d = map(int, dl.split("-"))
            dd = (date(y, mo, d) - tdate).days
        # 제목은 비슷한데 회차가 다른 것 → 남기되 표시(다른 회차 공고일 수 있음)
        out.append({**r, "dday": dd, "round_dup": (m[0] if m else None)})
    out.sort(key=lambda x: (x["deadline"] or "9999-99-99"))

    print(f"오늘={args.today} · 기업마당 · 상태[{args.status}] · 마감>=오늘 · 미검토 = {len(out)}건")
    print(f"(제외 → 판별키 중복 {exc_rev} · 제목 중복 {exc_title} · 상태 불일치 {exc_status} · 마감 지남 {exc_past})\n")
    for i, r in enumerate(out, 1):
        dd = r["dday"]
        dds = f"D-{dd}" if dd is not None and dd >= 0 else "상시/미정"
        print(f"{i:2}. [{dds:>7} · {r.get('deadline') or '상시'}] {r['name']}")
        print(f"      {BIZ_URL.format(r['key'])}")
        if r.get("round_dup"):
            print(f"      ⚠ 회차중복 의심(검토서 있음: {r['round_dup']}) — 회차 달라 남김, 검토서 만들 때 확인")


if __name__ == "__main__":
    main()
