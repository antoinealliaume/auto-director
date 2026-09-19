(() => {
  const quickTabs = [...document.querySelectorAll('[data-quick-tab]')];
  const navButtons = [...document.querySelectorAll('#nav button[data-tab]')];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function activeTab() {
    return document.querySelector('#nav button.active[data-tab]')?.dataset.tab || 'studio';
  }

  function syncNavigation() {
    const active = activeTab();
    navButtons.forEach(button => {
      const current = button.dataset.tab === active;
      if (current) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    quickTabs.forEach(button => button.classList.toggle('active', button.dataset.quickTab === active));
  }

  quickTabs.forEach(button => button.addEventListener('click', () => {
    if (typeof switchTab === 'function') switchTab(button.dataset.quickTab);
    syncNavigation();
  }));
  navButtons.forEach(button => button.addEventListener('click', () => requestAnimationFrame(syncNavigation)));

  const observer = !reducedMotion && 'IntersectionObserver' in window
    ? new IntersectionObserver(entries => entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('ui-visible');
          observer.unobserve(entry.target);
        }
      }), { threshold: .05 })
    : null;

  function enhance(root = document) {
    const selector = '.card,.job-card,.render-card,.dashboard-grid .metric';
    const elements = [...(root.matches?.(selector) ? [root] : []), ...root.querySelectorAll(selector)];
    elements.forEach(element => {
      if (element.dataset.uiEnhanced === '1') return;
      element.dataset.uiEnhanced = '1';
      if (!reducedMotion) element.classList.add('ui-reveal');
      if (observer) observer.observe(element);
      else element.classList.add('ui-visible');
    });
  }

  const mutations = new MutationObserver(records => {
    records.forEach(record => record.addedNodes.forEach(node => {
      if (node.nodeType === Node.ELEMENT_NODE) enhance(node);
    }));
  });
  mutations.observe(document.getElementById('studio') || document.body, { childList: true, subtree: true });

  addEventListener('scroll', () => document.querySelector('.topbar')?.classList.toggle('scrolled', scrollY > 12), { passive: true });
  document.documentElement.dataset.studioUi = '9.4';
  syncNavigation();
  enhance();
})();
