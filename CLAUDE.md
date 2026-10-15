# growthhigh-policy — 그로스하이 검토서 사이트

`curation.growthhigh.co.kr` (= bluep2000-hub.github.io/growthhigh-policy) 를 GitHub Pages(main 브랜치 루트)로 배포한다.
뉴스레터(스티비)의 "더 알아보기" 링크가 이 사이트의 검토서를 가리킨다. 전체 로드맵은 `ROADMAP.md`.

## 검토서 추가 규칙
- 파일명 `NNN-slug.html`, 정본 양식은 `_template.html`을 복제한다.
- **레지스트리 등록 필수**: `data.json`·`data-full.json` 둘 다에 항목을 추가한다.
  `deadline_iso`(예: `2026-10-16T16:00:00+09:00`)가 없으면 D-day 자동 계산이 연결되지 않는다.
  상시·수시 접수는 `deadline_display`에 "상시"/"수시"/"소진"을 적는다(자동 계산 제외).
- **뉴스레터 발송 전 반드시 푸시**: 링크가 들어간 검토서가 저장소에 없으면 404가 난다.
  (2026-10-06 사고: 451~481을 다른 PC에서 만들고 푸시하지 않아 10월 1주차 뉴스레터 링크 15개가 404)

## D-day 자동 계산
- 검토서 D-day는 고정 문자가 아니다. `dday.js`가 페이지를 열 때마다 각 페이지의
  `data-deadline`으로 D−n / D−DAY / 마감, 색상, 상태 문구를 다시 계산한다.
- `data-deadline`은 `tools_dday_inject.py`가 레지스트리의 `deadline_iso`를 읽어 붙인다(재실행 안전).
- **자동 실행**: `.github/workflows/dday-inject.yml`이 main 푸시마다 이 스크립트를 돌리고,
  바뀐 게 있으면 봇이 커밋한 뒤 Pages 빌드를 요청한다. 손으로 돌릴 필요 없다.
- 봇이 커밋을 덧붙이므로 **작업 시작 전·푸시 전에 `git pull --rebase`** 를 먼저 한다.

## 404 신고가 오면
1. 뉴스레터 링크의 파일명이 저장소에 있는지 확인 (`git log`, `ls NNN-*`).
2. 없으면 노션 「정책정보 크롤링 DB」에서 사업명으로 원문 공고를 찾아 재작성 후 푸시.
