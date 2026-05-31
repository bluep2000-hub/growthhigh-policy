document.querySelectorAll('.check').forEach(check => {
  check.addEventListener('click', () => check.classList.toggle('checked'));
});
