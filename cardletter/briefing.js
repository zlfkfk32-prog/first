const pages = Array.from(document.querySelectorAll('.page'));
const tabs = Array.from(document.querySelectorAll('nav a'));
const input = document.getElementById('search');
const tools = document.getElementById('detail-tools');
const status = document.getElementById('search-status');
let active = document.getElementById('home');
function filterArticles() {
  const query = input.value.trim().toLocaleLowerCase();
  let count = 0;
  active.querySelectorAll('.news-card').forEach(card => {
    card.hidden = !card.textContent.toLocaleLowerCase().includes(query);
    if (!card.hidden) count++;
  });
  status.textContent = query ? `검색 결과 ${count}건` : `이 부문의 기사 ${count}건을 표시합니다.`;
}
function route() {
  const id = location.hash.slice(1) || 'home';
  active = pages.find(page => page.id === id) || document.getElementById('home');
  pages.forEach(page => { page.hidden = page !== active; });
  tabs.forEach(tab => {
    if (tab.getAttribute('href') === '#' + active.id) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  });
  tools.hidden = !active.id.startsWith('section-');
  input.value = '';
  filterArticles();
  document.title = document.querySelector('header h1').textContent + ' · ' + (tabs.find(tab => tab.hasAttribute('aria-current'))?.textContent || '홈');
  window.scrollTo(0, 0);
}
input.addEventListener('input', filterArticles);
window.addEventListener('hashchange', route);
route();
