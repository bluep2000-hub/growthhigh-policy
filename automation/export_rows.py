#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notion 정책정보 크롤링 DB(34a815d7-12b9-804a-b06e-f297ce9d68d0)에서
notion_worklist.py 입력용 rows.json을 생성한다.

필터: 출처사이트='기업마당' AND 신청마감일>=오늘(KST) AND 중복삭제대상=false
      (※ DB '상태' 값이 스테일하므로 상태로 거르지 않고 마감일로 진행 여부 판단)

출력: rows.json — 배열, 각 원소 {"key","name","deadline","status"}
      key=중복판별키(PBLN_...), name=사업명, deadline=신청마감일(YYYY-MM-DD|null), status=상태

안전장치: API 에러이거나 결과가 0건이면 rows.json을 만들지 않고 exit 1.
방식은 ../../crawler/notion_export_keys.py와 동일(NOTION_API_KEY로 REST 직접 쿼리).
"""

import os
import json
import subprocess
from datetime import datetime, timedelta, timezone

DB_ID = "34a815d7-12b9-804a-b06e-f297ce9d68d0"
SOURCE_VALUE = "기업마당"
DEADLINE_PROP = "신청마감일"
DUP_DEL_PROP = "중복삭제대상"
KEY_PROP = "중복판별키"
TITLE_PROP = "사업명"
STATUS_PROP = "상태"

KST = timezone(timedelta(hours=9))

NOTION_API_KEY = os.getenv("NOTION_API_KEY", "").strip()

if not NOTION_API_KEY:
    # ~/.hermes/.env 에서 직접 읽기
    env_path = os.path.expanduser("~/.hermes/.env")
    try:
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("NOTION_API_KEY="):
                    NOTION_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except FileNotFoundError:
        pass

if not NOTION_API_KEY:
    print("❌ 에러: NOTION_API_KEY를 찾을 수 없음")
    print("   - 환경변수 NOTION_API_KEY 또는")
    print("   - ~/.hermes/.env의 NOTION_API_KEY=... 필요")
    exit(1)


def notion_query(payload):
    """Notion DB query 1회 호출. 실패 시 즉시 exit 1."""
    cmd = [
        "curl", "-s",
        "-H", f"Authorization: Bearer {NOTION_API_KEY}",
        "-H", "Notion-Version: 2022-06-28",
        "-H", "Content-Type: application/json",
        "-X", "POST",
        f"https://api.notion.com/v1/databases/{DB_ID}/query",
        "-d", json.dumps(payload),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("❌ 에러: curl 타임아웃 (60초) — rows.json 생성하지 않음")
        exit(1)

    if result.returncode != 0:
        print("❌ 에러: curl 실행 실패 — rows.json 생성하지 않음")
        print(result.stderr[:500])
        exit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("❌ 에러: Notion API 응답이 JSON이 아님 — rows.json 생성하지 않음")
        print(result.stdout[:500])
        exit(1)

    if data.get("object") == "error":
        print("❌ Notion API 에러 — rows.json 생성하지 않음")
        print(f"   status={data.get('status')} code={data.get('code')}")
        print(f"   message={data.get('message')}")
        exit(1)

    if data.get("object") != "list":
        print("❌ 에러: 예상치 못한 Notion 응답 형식 — rows.json 생성하지 않음")
        print(json.dumps(data, ensure_ascii=False)[:500])
        exit(1)

    return data


def plain(prop, kind):
    """title/rich_text 속성 → 평문. 타입 불일치면 빈 문자열."""
    if not prop or prop.get("type") != kind:
        return ""
    return "".join(t["plain_text"] for t in prop[kind]).strip()


today = datetime.now(KST).date().isoformat()

print("🔍 Notion 쿼리 중... (기업마당, 마감일 >= 오늘)")
print(f"   DB ID: {DB_ID}")
print(f"   필터: 출처사이트='{SOURCE_VALUE}' AND {DEADLINE_PROP}>={today}(KST) AND {DUP_DEL_PROP}=false")

base_filter = {
    "and": [
        {"property": "출처사이트", "select": {"equals": SOURCE_VALUE}},
        {"property": DEADLINE_PROP, "date": {"on_or_after": today}},
        {"property": DUP_DEL_PROP, "checkbox": {"equals": False}},
    ]
}

rows = []
seen = set()
skipped_nokey = 0
start_cursor = None
pages = 0

while True:
    payload = {
        "filter": base_filter,
        "sorts": [{"property": DEADLINE_PROP, "direction": "ascending"}],
        "page_size": 100,
    }
    if start_cursor:
        payload["start_cursor"] = start_cursor

    data = notion_query(payload)
    pages += 1

    for row in data.get("results", []):
        props = row.get("properties", {})

        key = plain(props.get(KEY_PROP), "rich_text")
        name = plain(props.get(TITLE_PROP), "title")

        if not key:
            skipped_nokey += 1
            continue
        if key in seen:            # 판별키 중복행은 1건만
            continue
        seen.add(key)

        dl_prop = props.get(DEADLINE_PROP) or {}
        deadline = (dl_prop.get("date") or {}).get("start")
        if deadline:
            deadline = deadline[:10]   # 'YYYY-MM-DD' (시각/타임존 부분 절단)

        st_prop = props.get(STATUS_PROP) or {}
        status = (st_prop.get("select") or {}).get("name")

        rows.append({
            "key": key,
            "name": name,
            "deadline": deadline,
            "status": status,
        })

    if data.get("has_more") and data.get("next_cursor"):
        start_cursor = data["next_cursor"]
    else:
        break

# 안전장치: 0건이면 파일을 만들지 않는다
if not rows:
    print("❌ 에러: 조건에 맞는 행이 0건입니다 — rows.json 생성하지 않음")
    print(f"   (조회 페이지 {pages}개, 판별키 없어 건너뛴 행 {skipped_nokey}건)")
    print(f"   확인 필요: DB_ID / 출처사이트='{SOURCE_VALUE}' / {DEADLINE_PROP}>={today} / {DUP_DEL_PROP} / 통합 권한")
    exit(1)

output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rows.json")
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)

print(f"✓ 저장 완료: {output_path}")
print(f"✓ 저장 건수: {len(rows)}건 (페이지 {pages}회 조회, 판별키 없어 건너뜀 {skipped_nokey}건)")
by_status = {}
for r in rows:
    by_status[r["status"]] = by_status.get(r["status"], 0) + 1
print(f"✓ 상태 분포: {by_status}")
print(f"✓ 샘플: {json.dumps(rows[0], ensure_ascii=False)}")
