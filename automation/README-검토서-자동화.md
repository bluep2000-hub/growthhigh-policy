# 검토서 자동화 — 재개용 메모 (2026-07-02 기준)

기업마당(정부지원사업) 공고 → 그로스하이 HTML 검토서 → 허브 레포 반영을 반자동화한 코드 모음.
**다른 PC에서 이어서 작업할 때 이 문서부터 읽을 것.**

---

## 0. 이 폴더에 뭐가 있나 (`automation/`)

| 파일 | 역할 |
|---|---|
| `download_notice.py` | 공고 URL → 첨부 다운로드 → 공고문 식별 → hwp/hwpx면 PDF 변환. (하위 로직, publish가 재사용) |
| `publish_review.py` | **오케스트레이터.** `preflight`(게이트 검사) / `finalize`(발행). 아래 3. 참조 |
| `notion_worklist.py` | 노션 크롤링 DB 조회 결과(JSON) + data-full.json → "검토서 안 만든 진행중 기업마당" 목록 |
| `검토서-자동화-스킬수정본.md` | `policy-review-html` 관리형 스킬에 가한 수정(복구본). 스킬 리셋 시 이걸로 재적용 |
| `README-검토서-자동화.md` | 이 문서 |

> 경로 이식성: 스크립트들은 `REPO = <이 파일의 상위의 상위>`로 레포 루트를 자동 산출한다.
> 즉 `<레포>/automation/`에 있기만 하면 어느 PC/경로에서도 동작. `GH_POLICY_REPO` 환경변수로 강제 지정도 가능.

---

## 1. 전체 흐름

```
노션 "정책정보 크롤링 DB"  ──(1)──▶  후보 목록(notion_worklist.py)
        │  사람이 공고 하나 선택
        ▼
publish_review.py preflight <URL>  ──▶  GREEN(job.json) 또는 HALT(사유 출력, 발행 안 함)
        │  GREEN이면
        ▼
[검토서 생성 = 모델 단계]  공고문 PDF/텍스트 → NN-슬러그.html + entry.json 작성
        ▼
publish_review.py finalize <job.json> <entry.json>  ──▶  PDF를 pdfs/로, data-full.json 삽입, git add·commit·push
        ▼
GitHub Pages 허브(full.html)에 라이브 반영 (푸시 후 CDN ~1분)
```

**⚠️ 핵심: 검토서 본문 생성은 순수 코드가 아니라 모델(Claude) 추론 단계다.** A/B/C 블록·요약·분류·톤은 모델이 공고문을 읽고 쓴다. 그래서 "완전 무인 배치"가 아니라, 사람 승인 게이트만 없애고 그 자리를 코드 게이트(점수·변환·중복)로 대체한 반자동이다. 무인화하려면 이 생성 단계를 헤드리스 Claude 호출로 바꿔야 함(남은 숙제).

---

## 2. 다른 PC 최초 세팅 (Windows 전제)

1. **레포 클론**: `git clone https://github.com/bluep2000-hub/growthhigh-policy.git`
2. **Python 설치**(3.12+): `winget install Python.Python.3.12 --scope user`.
   ※ `python`이라고만 치면 Windows 스토어 스텁이 잡히니, 실제 경로(`...\Programs\Python\Python312\python.exe`)로 호출.
3. **패키지**: `python -m pip install requests pywin32 pypdf`
4. **한컴오피스 설치 필수** — hwp/hwpx → PDF 변환은 한컴 COM(`HWPFrame.HwpObject`)을 쓴다. LibreOffice 아님.
   보안 팝업 차단용 `FilePathCheckerModule`이 등록돼 있어야 무인 변환됨(한컴 설치 시 보통 포함).
5. **git 자격증명**: 푸시하려면 GitHub 인증 필요(credential manager 캐시 또는 PAT). commit용 user.name/email 설정.
6. **노션 접근**: 노션 MCP 커넥터로 DB를 읽는다(코드가 직접 노션 API를 부르지 않음). Claude 세션에서 MCP로 조회 → 결과 JSON을 notion_worklist.py에 넘김.

---

## 3. 사용법

### (1) 후보 목록 — notion_worklist.py
- Claude가 노션 MCP로 "정책정보 크롤링 DB"(data source `collection://34a815d7-12b9-8193-9f37-000b826f88e4`)를 SQL 조회:
  `출처사이트='기업마당' AND 신청마감일>=오늘 AND (중복삭제대상 IS NULL OR ='__NO__')`
  (**주의: DB의 '상태' 값이 스테일**하므로 상태 대신 신청마감일>=오늘로 진행 여부 판단)
- 결과를 `rows.json`(배열, 각 원소 `{key,name,deadline,status}`)로 저장 후:
  `python automation/notion_worklist.py rows.json --today 2026-07-02`
- 출력: 기업마당·진행중·마감>=오늘·미검토 목록. **미검토 = pblancId가 data-full.json 항목의 source_url에 없음.**

### (2) preflight (발행 전 게이트) — 발행 안 함
```
python automation/publish_review.py preflight "<공고 URL>" --staging <임시폴더> [--min-score 100]
```
- GREEN이면 `<임시폴더>/job.json` + 공고문 PDF + 텍스트 생성.
- HALT면 발행하지 않고 사유만 출력 (사람 말):
  - `LOW_SCORE`/`AMBIGUOUS_TIE`: 어느 첨부가 공고문인지 불확실
  - `CONVERT_FAILED`: hwp 변환 실패/빈 PDF
  - `DUPLICATE`: 같은 공고(pblancId)가 이미 허브에 있음
  - `NO_ATTACHMENT`/`NO_DOC_NOTICE`: 첨부 없음/문서형 아님
- 실행은 COM 팝업 대비 타임아웃(job/subprocess)으로 감싸고, 끝나면 잔류 `Hwp.exe` 정리.

### (3) 검토서 생성 (모델)
- `job.json`의 `notice_text`(공고문 텍스트) + 필요시 PDF 렌더를 보고 표준형 HTML 작성.
- 기존 검토서(예: `172-*.html`)를 템플릿으로 복제 후 내용 교체. **PDF는 base64 아니라 `var PDF_DATA="pdfs/<슬러그>.pdf"` 상대경로.**
- `entry.json` 작성(스키마는 아래 4). 유형 애매하면 `경영/기타`.

### (4) finalize (자동 발행)
```
python automation/publish_review.py finalize <job.json> <entry.json> [--no-push]
```
- 검증(HTML 존재·pdfs/ 참조·중복 재확인) → PDF를 `pdfs/<슬러그>.pdf` → data-full.json `programs`에 append(+filters.types 자동보강) → git add(html·pdf·data-full.json)·commit·push.

---

## 4. data-full.json 항목 스키마 (신규는 반드시 `source_url` 포함)

```json
{
  "id": "173", "file": "173-슬러그.html", "title": "...", "summary": "...",
  "tags": ["분야라벨","신청형태"], "industries": ["제조업","지식서비스업","게임개발업"],
  "sub_industries": [], "types": ["경영/기타"],
  "deadline_iso": "2026-07-21T18:00:00+09:00", "deadline_display": "2026.07.21",
  "meta": {"지원":"최대 2,000만원","비율":"분담 40%","마감":"07.21"},
  "source_url": "https://www.bizinfo.go.kr/.../selectSIIA200Detail.do?pblancId=PBLN_..."
}
```
- **id = 기존 최대 +1** (preflight의 `next_id`가 계산).
- **types 8종**: R&D·창업·판로수출·인력·정책자금·인증·투자유치·**경영/기타**(2026-07 신설: 경영·컨설팅·진단·자문류 + 분류 애매).
- **source_url = 중복 판정 키**(pblancId). 없으면 중복 감지 안 됨 → 아래 숙제 참조.

---

## 5. 지금까지 진행 상황

### 최신 (2026-07-04) — 배치1

- **배치1 발행 상태**: id **174 바이오스타 2.0 초기창업기업 모집(1차)** 만 (최종)발행 완료.
- id **175~183** 검토서도 레포에 추가·커밋됨:
  175 IP-R&D 전략지원(4차), 176 해외홍보관 입점(UAE·베트남), 177 대구특구 이노폴리스캠퍼스,
  178 두바이 BIG5 SHOW 한국관, 179 방송영상콘텐츠 제작지원(드라마 장편), 180 소공인 클린제조환경조성,
  181 우수 기업부설연구소 지정, 182 중소기업기술혁신개발 구조혁신R&D, 183 SBA×LG K-뷰티 태국.
- data-full.json **다음 id = 184** (183까지 반영).
- **남은 일 → 톤 통일**: 검토서 **헤더 로고** 등 톤을 배치 전체에 걸쳐 통일하는 작업이 남음. **(다음 세션 시작점)**
- ⚠️ **배치 작업파일 미커밋**: `classified.json`(검토서 대상 분류)·`review-batches.md`(배치 기록)는
  스킬 세션(샌드박스) 산출물이라 이 레포에 없음. 배치 관리를 코드로 이어가려면 이 둘을 레포로 들일지 결정 필요.

### 이전 (2026-07-02)

- 검토서 3건 발행(라이브): **171** IFEZ ESG 경영 컨설팅(경영/기타), **172** 평택 해외플랫폼 입점(판로수출), **173** 지식재산 긴급지원 3차(경영/기타). 172·173은 오케스트레이터로 자동 발행.
- 배포 허브: https://bluep2000-hub.github.io/growthhigh-policy/full.html (유형칩은 filters.types에서 동적 생성).
- DB URL 형식(`selectSIIA200Detail.do`)도 다운로더와 호환 확인됨(173에서 검증).

---

## 6. 남은 숙제 (TODO)

1. **예전 검토서 중복 미탐지** — id ≤170 항목들은 `source_url`(pblancId)이 없어, 노션 후보가 이미 예전 수동 등록된 것과 겹쳐도 못 걸러냄. → (a) 예전 항목에 source_url 백필하거나, (b) 제목 유사도 기반 중복 매칭을 notion_worklist/preflight에 추가. 현재는 pblancId 완전일치만.
2. **크롤러 '상태' 값 스테일** — 마감 지난 공고도 '진행중'으로 남아있음. 지금은 신청마감일>=오늘로 우회. 크롤러(다른 PC) 수정은 이 프로젝트 범위 밖.
3. **무인 배치화** — 검토서 생성이 모델 단계라 사람/세션 없이 안 돌아감. 헤드리스 Claude 호출로 생성 단계 자동화 필요(안정화 후).
4. **관리형 스킬 덮어쓰기 위험** — `policy-review-html` 스킬에 가한 수정(base64→pdfs/, 경영/기타 유형, 로컬 산출경로)은 플러그인 재동기화 시 사라질 수 있음. 복구본: `automation/검토서-자동화-스킬수정본.md`.
5. **노션 SQL rate limit** — 조회 시 429 자주 남. 재시도 여유 둘 것.
6. **유형 분류 판단** — ESG 컨설팅·IP 지원 등은 경영/기타로 넣고 있으나, 향후 유형 세분화 여지.
