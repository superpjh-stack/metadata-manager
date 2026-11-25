const addColumn = document.getElementById('add-column');
if (addColumn) addColumn.addEventListener('click', () => {
  const total = document.getElementById('id_columns-TOTAL_FORMS');
  const template = document.getElementById('empty-column');
  document.getElementById('column-rows').insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', total.value));
  total.value = Number(total.value) + 1;
});
const all = document.getElementById('select-all');
if (all) all.addEventListener('change', () => document.querySelectorAll('input[name="datasets"]').forEach(box => box.checked = all.checked));

const mobileMenu = document.querySelector('.mobile-menu');
const sidebar = document.querySelector('.sidebar');
if (mobileMenu && sidebar) {
  sidebar.classList.add('js-nav');
  const closeMenu = () => {
    sidebar.classList.remove('nav-open');
    mobileMenu.setAttribute('aria-expanded', 'false');
    mobileMenu.textContent = '메뉴';
  };
  mobileMenu.addEventListener('click', () => {
    const open = sidebar.classList.toggle('nav-open');
    mobileMenu.setAttribute('aria-expanded', String(open));
    mobileMenu.textContent = open ? '닫기' : '메뉴';
  });
  sidebar.addEventListener('keydown', event => {
    if (event.key === 'Escape' && sidebar.classList.contains('nav-open')) {
      closeMenu();
      mobileMenu.focus();
    }
  });
}
