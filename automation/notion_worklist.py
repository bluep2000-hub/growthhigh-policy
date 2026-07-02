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
  - pblancId가 허브 data-full.json 항목의 source_url에 없음 (= 아직 검토서 안 만듦)

사용:  python notion_worklist.py <rows.json> [--today YYYY-MM-DD] [--status 진행중|all]
"""
import json, os, re, argparse
from datetime import date

for _s in (__import__("sys").stdout, __import__("sys").stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

# <레포>/automation/ 기준으로 레포 루트 자동 산출 (다른 PC/경로 이식성)
REPO = os.environ.get("GH_POLICY_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data-full.json")
BIZ_URL = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={}"


def reviewed_pblanc_ids():
    d = json.load(open(DATA, encoding="utf-8"))
    s = set()
    for p in d["programs"]:
        m = re.search(r"PBLN_[0-9]+", p.get("source_url") or "")
        if m:
            s.add(m.group(0))
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rows")
    ap.add_argument("--today", default=date.today().isoformat())
    ap.add_argument("--status", default="진행중")
    args = ap.parse_args()

    ty, tm, td = map(int, args.today.split("-"))
    tdate = date(ty, tm, td)
    reviewed = reviewed_pblanc_ids()
    rows = json.load(open(args.rows, encoding="utf-8"))

    out, exc_rev, exc_status, exc_past = [], 0, 0, 0
    for r in rows:
        k, st, dl = r["key"], r.get("status"), r.get("deadline")
        if args.status != "all" and st != args.status:
            exc_status += 1; continue
        if dl and dl < args.today:
            exc_past += 1; continue
        if k in reviewed:
            exc_rev += 1; continue
        dd = None
        if dl:
            y, m, d = map(int, dl.split("-"))
            dd = (date(y, m, d) - tdate).days
        out.append({**r, "dday": dd})
    out.sort(key=lambda x: (x["deadline"] or "9999-99-99"))

    print(f"오늘={args.today} · 기업마당 · 상태[{args.status}] · 마감>=오늘 · 미검토 = {len(out)}건")
    print(f"(제외 → 이미 검토서 있음 {exc_rev} · 상태 불일치 {exc_status} · 마감 지남 {exc_past})\n")
    for i, r in enumerate(out, 1):
        dd = r["dday"]
        dds = f"D-{dd}" if dd is not None and dd >= 0 else "상시/미정"
        print(f"{i:2}. [{dds:>7} · {r.get('deadline') or '상시'}] {r['name']}")
        print(f"      {BIZ_URL.format(r['key'])}")


if __name__ == "__main__":
    main()
