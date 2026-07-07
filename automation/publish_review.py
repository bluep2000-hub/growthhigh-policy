#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
검토서 자동 발행 오케스트레이터 (자동화 2·3단계 배관)

사람 확인 게이트를 없애고, 코드 자동 검증(게이트)으로 대체한다.
흐름:
  publish_review.py preflight <URL>   → 다운로드·변환 + 3대 게이트 검사
        - 통과(GREEN): 공고문 PDF를 staging에 준비 + job.json 출력 → 검토서 생성 단계로
        - 걸림(HALT):  발행 중단, 사람 말로 사유만 출력 (아래 3가지)
             · 공고문 선택 점수가 낮거나 후보가 동점이라 불확실
             · hwp 변환이 실패했거나 빈 PDF
             · 같은 공고가 이미 허브에 있음(중복)
  [검토서 생성]  모델이 job.json + 공고문 텍스트를 보고 NN-슬러그.html + entry.json 작성
  publish_review.py finalize <job.json> <entry.json>
        → PDF를 pdfs/로, data-full.json에 항목 삽입, git add·commit·push (자동 발행)

게이트/판정은 검증된 download_notice.py의 로직을 재사용한다.
"""
import argparse, json, os, sys, shutil, subprocess, re
from datetime import datetime, timezone, timedelta

# 콘솔 인코딩(cp949) 방어
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import download_notice as dn

# 이 스크립트는 <레포>/automation/ 에 있으므로 레포 루트 = 상위의 상위 (이식성: 다른 PC/경로에서도 동작)
REPO = os.environ.get("GH_POLICY_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data-full.json")
DATA_SMALL = os.path.join(REPO, "data.json")
KST = timezone(timedelta(hours=9))

# data.json은 data-full.json의 필드 부분집합만 쓴다(sub_industries·sent_to·source_url·curated 제외).
DATA_SMALL_FIELDS = ["id", "file", "title", "summary", "tags", "industries", "types",
                     "deadline_iso", "deadline_display", "meta", "notion_key", "notion_url", "added_at",
                     "brief_one"]

MIN_SCORE_DEFAULT = 100   # 공고문 후보 점수가 이 미만이면 '어느 게 공고문인지 불확실'로 판단
DEFAULT_TYPE = "경영/기타"


def _load_data():
    return json.load(open(DATA, encoding="utf-8"))


def _next_id(data):
    ids = [int(p["id"]) for p in data["programs"] if str(p.get("id", "")).isdigit()]
    return str(max(ids) + 1) if ids else "1"


def _dup_by_pblanc(data, pid):
    """data-full.json 항목 중 source_url에 이 pblancId를 가진 게 있으면 그 항목 반환."""
    for p in data["programs"]:
        if pid and pid in (p.get("source_url") or ""):
            return p
    return None


def _halt(reason_code, message, extra=None):
    out = {"status": "HALT", "reason_code": reason_code, "message": message}
    if extra:
        out.update(extra)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


# ── preflight ─────────────────────────────────────────────────────────────
def preflight(url, staging, min_score):
    os.makedirs(staging, exist_ok=True)
    pid = dn.extract_pblanc_id(url)

    html = dn.fetch(url).text
    refs = dn.extract_file_refs(html)
    if not refs:
        return _halt("NO_ATTACHMENT",
                     f"이 URL에서 첨부를 찾지 못했습니다. 공고 상세(view.do?pblancId=…) URL이 맞는지 확인해 주세요. (pblancId={pid})")

    files = dn.download_all(refs, staging)
    chosen, ranked = dn.pick_announcement(files)

    # ── GATE ①: 공고문 선택 불확실 ──
    doc_kinds = ("pdf", "hwp", "hwpx")
    docs = [f for f in ranked if f["kind"] in doc_kinds]
    if chosen["kind"] not in doc_kinds:
        return _halt("NO_DOC_NOTICE",
                     "공고문으로 볼 문서형(pdf/hwp/hwpx) 첨부가 없습니다. 첨부가 zip/이미지뿐입니다.",
                     {"attachments": [{"name": f["name"], "kind": f["kind"]} for f in files]})
    top = chosen["score"]
    tied = [f for f in docs if f["score"] == top]
    if top < min_score:
        names = "\n".join(f"    · [{f['kind']}] {f['name']} (점수 {f['score']})" for f in docs)
        return _halt("LOW_SCORE",
                     f"어느 첨부가 공고문인지 확실하지 않습니다(최고 점수 {top} < 기준 {min_score}). "
                     f"파일명에 '공고/공고문' 표시가 약합니다. 첨부 목록:\n{names}",
                     {"chosen": chosen["name"], "top_score": top})
    if len(tied) >= 2:
        names = "\n".join(f"    · [{f['kind']}] {f['name']}" for f in tied)
        return _halt("AMBIGUOUS_TIE",
                     f"공고문 후보가 동점({top}점)이라 어느 게 진짜 공고문인지 불확실합니다:\n{names}",
                     {"tied": [f["name"] for f in tied]})

    # ── GATE ③(먼저 검사, 값싸다): 중복 ──
    data = _load_data()
    dup = _dup_by_pblanc(data, pid)
    if dup:
        return _halt("DUPLICATE",
                     f"같은 공고가 이미 허브에 있습니다 — id {dup['id']} 「{dup['title']}」 (file {dup['file']}). "
                     f"중복 발행하지 않았습니다. (pblancId={pid})",
                     {"existing_id": dup["id"], "existing_title": dup["title"]})

    # ── GATE ②: hwp 변환 실패/빈 PDF ──
    notice_pdf = os.path.join(staging, f"{pid}_notice.pdf")
    try:
        if chosen["kind"] == "pdf":
            shutil.copyfile(chosen["path"], notice_pdf)
        else:  # hwp / hwpx
            dn.hwp_to_pdf(chosen["path"], notice_pdf, chosen["kind"])  # 빈 PDF/Open실패 시 예외
    except Exception as e:
        return _halt("CONVERT_FAILED",
                     f"공고문({chosen['kind']}) → PDF 변환에 실패했습니다: {e}. 발행하지 않았습니다.",
                     {"chosen": chosen["name"]})

    # 공고문 텍스트 추출(검토서 생성 참고용)
    notice_txt = os.path.join(staging, f"{pid}_notice.txt")
    try:
        from pypdf import PdfReader
        r = PdfReader(notice_pdf)
        txt = "\n".join(f"----- p{i+1} -----\n{(pg.extract_text() or '')}" for i, pg in enumerate(r.pages))
        open(notice_txt, "w", encoding="utf-8").write(txt)
    except Exception:
        notice_txt = None

    next_id = _next_id(data)
    job = {
        "status": "GREEN",
        "pblancId": pid,
        "source_url": url,
        "next_id": next_id,
        "chosen_name": chosen["name"],
        "chosen_kind": chosen["kind"],
        "chosen_score": top,
        "staged_pdf": notice_pdf,
        "notice_pdf_size": os.path.getsize(notice_pdf),
        "notice_text": notice_txt,
        "attachments": [{"name": f["name"], "kind": f["kind"], "score": f.get("score")} for f in files],
    }
    job_path = os.path.join(staging, "job.json")
    json.dump(job, open(job_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    job["job_path"] = job_path
    print(json.dumps(job, ensure_ascii=False, indent=2))
    return job


# ── finalize ──────────────────────────────────────────────────────────────
def _git(args):
    return subprocess.run(["git", "-C", REPO] + args, capture_output=True, text=True, encoding="utf-8")


def finalize(job_path, entry_path, do_push=True):
    job = json.load(open(job_path, encoding="utf-8"))
    entry = json.load(open(entry_path, encoding="utf-8"))

    slug = os.path.splitext(entry["file"])[0]
    html_path = os.path.join(REPO, entry["file"])
    if not os.path.isfile(html_path):
        return _halt("NO_HTML", f"검토서 HTML이 없습니다: {entry['file']}")
    html = open(html_path, encoding="utf-8").read()
    rel_pdf = f"pdfs/{slug}.pdf"
    is_decision = entry["file"].endswith("-decision.html")
    # 의사결정형은 로컬 PDF 모달이 아니라 공고문 원문 링크(.src-btn)를 쓰는 디자인이라
    # pdfs/ 상대경로를 HTML에 넣지 않는다 — 표준형만 이 참조를 강제한다.
    if not is_decision and rel_pdf not in html:
        return _halt("PDF_REF_MISSING", f"HTML이 상대경로 PDF({rel_pdf})를 참조하지 않습니다.")

    # 기본값·필수 필드 보정
    entry.setdefault("source_url", job.get("source_url"))
    if not entry.get("types"):
        entry["types"] = [DEFAULT_TYPE]

    data = _load_data()
    # 재확인 중복 (id/file/pblancId)
    pid = job.get("pblancId")
    dup = _dup_by_pblanc(data, pid) or next((p for p in data["programs"] if p["file"] == entry["file"] or p["id"] == entry["id"]), None)
    if dup:
        return _halt("DUPLICATE", f"이미 존재하는 항목과 충돌 — id {dup['id']} 「{dup['title']}」")

    # PDF 배치
    pdf_dst = os.path.join(REPO, "pdfs", f"{slug}.pdf")
    shutil.copyfile(job["staged_pdf"], pdf_dst)

    # 발행일(KST, YYYY-MM-DD) 심기 — 오늘 이후 신규 발행분부터, 기존 227건은 소급하지 않음
    entry["added_at"] = datetime.now(KST).strftime("%Y-%m-%d")
    # 한 줄 훅(brief_one) — 검토서 생성 모델이 공고문 근거로 이미 채웠어야 하는 필드(20~30자,
    # 추측·과장 금지). finalize는 값을 만들어내지 않고 비어 있으면 빈 값으로 둔다(플레이리스트가
    # summary로 폴백 렌더링함).
    entry.setdefault("brief_one", "")

    # data-full.json 삽입
    if entry["types"][0] not in data["filters"]["types"]:
        data["filters"]["types"].append(entry["types"][0])
    data["programs"].append(entry)
    data["updated_at"] = datetime.now(KST).replace(microsecond=0).isoformat()
    json.dump(data, open(DATA, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # data.json 병행 삽입(부분 필드만) — 평소 수동 유지지만 added_at은 여기서 함께 심는다
    data_small = json.load(open(DATA_SMALL, encoding="utf-8"))
    small_entry = {k: entry[k] for k in DATA_SMALL_FIELDS if k in entry}
    if entry["types"][0] not in data_small["filters"]["types"]:
        data_small["filters"]["types"].append(entry["types"][0])
    data_small["programs"].append(small_entry)
    data_small["updated_at"] = data["updated_at"]
    json.dump(data_small, open(DATA_SMALL, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # git add · commit · push
    _git(["add", entry["file"], rel_pdf, "data-full.json", "data.json"])
    msg = f"검토서 추가: {entry['title']} (id {entry['id']})\n\n자동 발행 (publish_review.py). source: {entry.get('source_url')}\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    c = _git(["commit", "-m", msg])
    push_out = ""
    if do_push:
        p = _git(["push", "origin", "main"])
        push_out = (p.stdout + p.stderr).strip()

    result = {
        "status": "PUBLISHED",
        "id": entry["id"], "file": entry["file"], "title": entry["title"],
        "types": entry["types"], "pdf": rel_pdf, "pdf_size": os.path.getsize(pdf_dst),
        "commit": (c.stdout + c.stderr).strip().splitlines()[0] if (c.stdout or c.stderr) else "",
        "push": push_out,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pf = sub.add_parser("preflight")
    pf.add_argument("url")
    pf.add_argument("--staging", required=True)
    pf.add_argument("--min-score", type=int, default=MIN_SCORE_DEFAULT)
    fz = sub.add_parser("finalize")
    fz.add_argument("job")
    fz.add_argument("entry")
    fz.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    if args.cmd == "preflight":
        r = preflight(args.url, args.staging, args.min_score)
        sys.exit(0 if r.get("status") == "GREEN" else 10)
    else:
        r = finalize(args.job, args.entry, do_push=not args.no_push)
        sys.exit(0 if r.get("status") == "PUBLISHED" else 11)


if __name__ == "__main__":
    main()
