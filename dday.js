/* 검토서 D-day를 열 때마다 다시 계산. [data-deadline]에 ISO 마감시각(+09:00). */
(function () {
  var fmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' });
  var day = function (d) { var p = fmt.format(d).split('-').map(Number); return Date.UTC(p[0], p[1] - 1, p[2]); };
  var OPEN_WORDS = /^(마감\s?임박|오늘 마감|접수 임박|모집\s?중|접수\s?중|신청\s?중|접수 종료|마감 완료|모집 마감)$/;
  document.querySelectorAll('[data-deadline]').forEach(function (el) {
    var dl = new Date(el.getAttribute('data-deadline')), now = new Date();
    if (isNaN(dl)) return;
    var n = Math.round((day(dl) - day(now)) / 86400000);
    var closed = now > dl;
    var status = closed ? 'closed' : n <= 3 ? 'urgent' : 'warning';
    var label = closed ? '마감' : n === 0 ? 'D−DAY' : 'D−' + n;
    el.classList.remove('urgent', 'warning', 'closed');
    el.classList.add(status);
    var badge = el.querySelector('.dday-badge');
    if (badge) {
      badge.textContent = label;
      var head = el.querySelector('.dday-text > strong:first-child');
      if (head && (closed || OPEN_WORDS.test(head.textContent.trim()))) {
        head.textContent = closed ? '접수 종료' : n === 0 ? '오늘 마감' : n <= 3 ? '마감 임박' : '모집중';
      }
    } else {
      // 구형 마크업: <span class="dot"></span><span>D-3</span> 또는 .dday 한 줄
      var span = el.querySelector('span:not(.dot):not(.dday-sub)');
      if (span) span.textContent = closed ? '마감' : label;
      else if (el.lastChild) el.lastChild.textContent = (closed ? '마감' : label) + el.lastChild.textContent.replace(/^\s*(D[-−]\S*|마감)/, '');
    }
  });
})();
