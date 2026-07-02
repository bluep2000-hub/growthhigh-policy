#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
기업마당(bizinfo.go.kr) 공고 다운로더 (자동화 1단계)

공고 상세 URL 하나를 받아서:
  1) 상세 HTML에서 첨부(atchFileId + fileSn) 목록을 뽑고
  2) 첨부를 전부 내려받아 실제 파일 종류(pdf/hwp/hwpx/...)를 magic byte로 판별하고
  3) 그 중 '공고문'을 골라
  4) hwp/hwpx면 한컴 COM으로 PDF 변환, 이미 PDF면 그대로 채택
최종적으로 '공고문 PDF' 한 개의 경로를 만들어 낸다.

사용:  python download_notice.py "<공고 상세 URL>" [출력폴더]
"""
import sys, os, re, json, zipfile, argparse, shutil

import requests

# Windows 콘솔 기본 인코딩(cp949)에서 비-cp949 문자 출력 시 크래시 방지 -> stdout/stderr UTF-8 고정
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE = "https://www.bizinfo.go.kr"
DOWN = BASE + "/cmm/fms/fileDown.do"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": BASE,
}

# 파일명에 못 쓰는 Windows 금지문자
_INVALID = re.compile(r'[\\/:*?"<>|\r\n\t]')


def log(msg):
    print(msg, flush=True)


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r


def extract_pblanc_id(url):
    m = re.search(r'pblancId=(PBLN_[0-9]+)', url)
    return m.group(1) if m else "notice"


def extract_file_refs(html):
    """상세 HTML에서 (atchFileId, fileSn) 순서 유지 + 중복 제거."""
    seen, out = set(), []
    for m in re.finditer(r'fileDown\.do\?atchFileId=(FILE_[0-9]+)&(?:amp;)?fileSn=(\d+)', html):
        key = (m.group(1), m.group(2))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def recover_filename(cd):
    """Content-Disposition의 파일명 복원.
    bizinfo는 공고마다 두 방식을 섞어 쓴다:
      (a) 퍼센트 인코딩:  filename="%EB%B6%99..."  또는  filename*=UTF-8''%EB...
      (b) UTF-8 바이트 그대로:  requests가 latin-1로 읽어 깨져 보임 -> latin1->utf8 복원
    """
    if not cd:
        return None
    from urllib.parse import unquote
    # RFC5987 filename*=UTF-8''.. 형태 우선
    m = re.search(r"filename\*=(?:UTF-8|utf-8)''([^;]+)", cd)
    if m:
        return unquote(m.group(1))
    m = re.search(r'filename="?([^";]+)"?', cd)
    if not m:
        return None
    raw = m.group(1).strip()
    # (a) 퍼센트 인코딩이면 unquote
    if re.search(r'%[0-9A-Fa-f]{2}', raw):
        try:
            return unquote(raw)
        except Exception:
            pass
    # (b) UTF-8 바이트가 latin-1로 읽힌 경우 복원
    try:
        return raw.encode('latin-1').decode('utf-8')
    except Exception:
        return raw


def sniff(path):
    """magic byte로 실제 파일 종류 판별 (확장자 신뢰 안 함)."""
    with open(path, 'rb') as f:
        head = f.read(8)
    if head[:4] == b'%PDF':
        return 'pdf'
    if head == b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1':  # OLE 복합문서 = HWP 5.x
        return 'hwp'
    if head[:4] == b'PK\x03\x04':                    # zip 계열
        try:
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if 'mimetype' in names:
                    mt = z.read('mimetype').decode('ascii', 'ignore')
                    if 'hwp' in mt:
                        return 'hwpx'
                    if 'opendocument' in mt:
                        return 'odf'
                if any(n.startswith('word/') for n in names):
                    return 'docx'
                if any(n.startswith('ppt/') for n in names):
                    return 'pptx'
                if any(n.startswith('xl/') for n in names):
                    return 'xlsx'
        except Exception:
            pass
        return 'zip'
    return 'bin'


_EXT = {'pdf': '.pdf', 'hwp': '.hwp', 'hwpx': '.hwpx',
        'docx': '.docx', 'pptx': '.pptx', 'xlsx': '.xlsx', 'zip': '.zip'}


def safe_name(name, fallback):
    if not name:
        return fallback
    return _INVALID.sub('_', name).strip() or fallback


def download_all(refs, outdir):
    files = []
    for i, (fid, sn) in enumerate(refs, 1):
        url = f"{DOWN}?atchFileId={fid}&fileSn={sn}"
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        name = recover_filename(r.headers.get('Content-Disposition'))
        kind_tmp = os.path.join(outdir, f"_att_{i}.tmp")
        with open(kind_tmp, 'wb') as f:
            f.write(r.content)
        kind = sniff(kind_tmp)
        # 실제 이름(확장자 보정)으로 rename
        base = safe_name(name, f"attachment_{i}")
        if not os.path.splitext(base)[1]:
            base += _EXT.get(kind, '')
        dest = os.path.join(outdir, base)
        if os.path.exists(dest):
            os.remove(dest)
        os.replace(kind_tmp, dest)
        files.append({'idx': i, 'atchFileId': fid, 'fileSn': sn,
                      'name': name or base, 'kind': kind,
                      'path': dest, 'size': len(r.content)})
    return files


def score_announcement(f):
    """'공고문'일 가능성 점수. 이름 키워드 + 종류로 판단."""
    n = (f['name'] or '')
    s = 0
    if '공고문' in n:
        s += 200
    if '모집공고' in n or '지원공고' in n:
        s += 150
    if '공고' in n:
        s += 100
    if '공모' in n:
        s += 70
    # 양식/서식/부속서류로 보이는 이름은 감점 (공고문 키워드가 있으면 그게 이김)
    for kw in ('양식', '서식', '신청서', '계획서', '신청양식', '제출서',
               '서약', '별지', '동의', '증빙', '체크리스트', 'FAQ', '요약'):
        if kw in n:
            s -= 40
    if f['kind'] == 'pdf':      # 이미 PDF면 변환 불필요라 살짝 가점
        s += 10
    return s


def pick_announcement(files):
    docs = [f for f in files if f['kind'] in ('pdf', 'hwp', 'hwpx')]
    if not docs:
        docs = files[:]
    ranked = sorted(docs, key=lambda f: (score_announcement(f), f['size']), reverse=True)
    for f in ranked:
        f['score'] = score_announcement(f)
    return ranked[0], ranked


def hwp_to_pdf(src, dst, kind):
    """한컴 COM으로 hwp/hwpx -> PDF.

    주의: 한컴 Open은 경로에 %/공백/·(가운뎃점) 등 특수문자가 있으면 조용히 실패하고,
    그래도 SaveAs가 '빈 PDF(~5KB)'를 만들어 버린다. 그래서
      (1) 소스를 ASCII-only 임시 경로로 복사해서 열고
      (2) 결과 PDF도 임시 ASCII 경로로 저장한 뒤 최종 이름으로 옮기며
      (3) Open 실패/빈 결과를 감지해 예외를 던진다.
    """
    import win32com.client as win32
    import tempfile

    ext = '.hwpx' if kind == 'hwpx' else '.hwp'
    tmpdir = tempfile.mkdtemp(prefix="hwpconv_")
    tmp_src = os.path.join(tmpdir, "input" + ext)
    tmp_pdf = os.path.join(tmpdir, "output.pdf")
    shutil.copyfile(src, tmp_src)

    hwp = win32.Dispatch("HWPFrame.HwpObject")
    hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")  # 보안 팝업 차단(무인 자동화)
    try:
        opened = hwp.Open(tmp_src, "", "forceopen:true")   # ""=확장자 자동감지 (hwp/hwpx 모두)
        if not opened:
            raise RuntimeError(f"한컴 Open 실패 (kind={kind})")
        hwp.SaveAs(tmp_pdf, "PDF", "")
    finally:
        try:
            hwp.Clear(1)
        except Exception:
            pass
        try:
            hwp.Quit()
        except Exception:
            pass

    if not os.path.exists(tmp_pdf):
        raise RuntimeError("변환 결과 PDF가 생성되지 않음")
    if os.path.getsize(tmp_pdf) < 8000:   # ~5KB = 빈 문서. 정상 공고문은 수십~수백 KB
        raise RuntimeError(f"변환 PDF가 비정상적으로 작음({os.path.getsize(tmp_pdf)}B) — Open이 실패했을 가능성")

    if os.path.exists(dst):
        os.remove(dst)
    shutil.move(tmp_pdf, dst)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("outdir", nargs="?", default=None)
    args = ap.parse_args()

    pid = extract_pblanc_id(args.url)
    outdir = args.outdir or os.path.join(os.getcwd(), "downloads", pid)
    os.makedirs(outdir, exist_ok=True)

    log(f"[1] 상세 페이지 요청: {args.url}")
    html = fetch(args.url).text
    refs = extract_file_refs(html)
    log(f"    첨부 링크 {len(refs)}개 발견")
    if not refs:
        log("!! 첨부를 찾지 못함. URL이 공고 상세(view.do?pblancId=...)가 맞는지 확인 필요.")
        sys.exit(2)

    log("[2] 첨부 다운로드 + 종류 판별")
    files = download_all(refs, outdir)
    for f in files:
        log(f"    - #{f['idx']} [{f['kind']:>4}] {f['size']:>8,}B  {f['name']}")

    log("[3] 공고문 선택")
    chosen, ranked = pick_announcement(files)
    for f in ranked:
        mark = "  <== 선택" if f is chosen else ""
        log(f"    score={f['score']:>4}  [{f['kind']:>4}]  {f['name']}{mark}")

    log("[4] 최종 공고문 PDF 준비")
    out_pdf = os.path.join(outdir, f"{pid}_공고문.pdf")
    if chosen['kind'] == 'pdf':
        shutil.copyfile(chosen['path'], out_pdf)
        log(f"    이미 PDF -> 그대로 채택")
    elif chosen['kind'] in ('hwp', 'hwpx'):
        log(f"    {chosen['kind']} -> 한컴 COM으로 PDF 변환 중...")
        ok = hwp_to_pdf(chosen['path'], out_pdf, chosen['kind'])
        if not ok:
            log("!! 변환 실패")
            sys.exit(3)
        log("    변환 완료")
    else:
        log(f"!! 공고문 후보가 문서형(pdf/hwp/hwpx)이 아님: {chosen['kind']}")
        sys.exit(4)

    result = {
        "pblancId": pid,
        "outdir": outdir,
        "attachments": [{k: f[k] for k in ('name', 'kind', 'size')} for f in files],
        "chosen": {"name": chosen['name'], "kind": chosen['kind'], "score": chosen['score']},
        "notice_pdf": out_pdf,
        "notice_pdf_size": os.path.getsize(out_pdf),
    }
    result_path = os.path.join(outdir, "result.json")
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log("\n=== RESULT JSON ===")
    log(json.dumps(result, ensure_ascii=False, indent=2))
    log(f"\n(결과 요약 저장: {result_path})")


if __name__ == "__main__":
    main()
