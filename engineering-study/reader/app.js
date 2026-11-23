(function () {
  'use strict';

  const STORAGE_KEY = 'jdev-study-reader-v1';
  const state = loadState();
  const els = Object.fromEntries([
    'toc', 'sidebar', 'scrim', 'toc-toggle', 'theme-toggle', 'search-trigger', 'search-overlay',
    'search-input', 'search-results', 'search-status', 'chapter', 'chapter-content', 'chapter-toolbar',
    'breadcrumb', 'chapter-nav', 'complete-button', 'reading-progress-fill', 'book-progress-fill',
    'completed-count', 'completed-percent', 'welcome', 'begin-button', 'mobile-chapter-label'
  ].map((id) => [id.replace(/-([a-z])/g, (_, c) => c.toUpperCase()), document.getElementById(id)]));

  let manifest;
  let chapters = [];
  let byId = new Map();
  let bySourcePath = new Map();
  let activeId = null;
  let searchIndex = null;
  let searchSelection = 0;
  let mermaidPromise = null;
  let saveTimer = 0;
  let scrollTimer = 0;
  let currentOutline = [];

  function loadState() {
    try {
      return Object.assign({ theme: 'light', sidebarCollapsed: false, completed: [], scroll: {}, lastChapter: null },
        JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'));
    } catch (_) {
      return { theme: 'light', sidebarCollapsed: false, completed: [], scroll: {}, lastChapter: null };
    }
  }

  function saveState() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (_) { /* storage can be disabled */ }
    }, 120);
  }

  function setTheme(theme) {
    state.theme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = state.theme;
    document.querySelector('meta[name="theme-color"]').content = state.theme === 'dark' ? '#191c1b' : '#f5f3ee';
    els.themeToggle.setAttribute('aria-label', `Switch to ${state.theme === 'dark' ? 'light' : 'dark'} theme`);
    els.themeToggle.title = `Switch to ${state.theme === 'dark' ? 'light' : 'dark'} theme`;
    els.themeToggle.innerHTML = `<span aria-hidden="true">${state.theme === 'dark' ? '☼' : '◐'}</span>`;
    saveState();
  }

  function allChapters() { return manifest.sections.flatMap((section) => section.chapters.map((chapter) => ({ ...chapter, section: section.title }))); }

  function makeTOC() {
    let number = 0;
    els.toc.innerHTML = manifest.sections.map((section) => {
      const entries = section.chapters.map((chapter) => {
        number++;
        const done = state.completed.includes(chapter.id);
        return `<a class="toc-link${done ? ' is-complete' : ''}" data-chapter="${chapter.id}" href="?chapter=${encodeURIComponent(chapter.id)}" title="${StudyMarkdown.escapeHTML(chapter.summary || '')}"><span class="chapter-number">${String(number).padStart(2, '0')}</span><span>${StudyMarkdown.escapeHTML(chapter.title)}</span><span class="toc-check" aria-label="Complete">✓</span></a>${chapter.id === activeId ? '<div class="toc-outline" id="toc-outline"></div>' : ''}`;
      }).join('');
      return `<div class="toc-section"><div class="toc-section-title">${StudyMarkdown.escapeHTML(section.title)}</div>${entries}</div>`;
    }).join('');
    els.toc.querySelectorAll('[data-chapter]').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault();
      navigate(link.dataset.chapter);
      closeSidebarOnNarrow();
    }));
    updateBookProgress();
    updateTOCActive();
  }

  function updateTOCActive() {
    els.toc.querySelectorAll('.toc-link').forEach((link) => {
      const active = link.dataset.chapter === activeId;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
  }

  function updateBookProgress() {
    const done = new Set(state.completed);
    const total = chapters.length;
    const percent = total ? Math.round(done.size / total * 100) : 0;
    els.completedCount.textContent = `${done.size} of ${total} complete`;
    els.completedPercent.textContent = `${percent}%`;
    els.bookProgressFill.style.width = `${percent}%`;
  }

  function sourceUrl(chapter) { return `/engineering-study/${chapter.path.split('/').map(encodeURIComponent).join('/')}`; }

  function resolveMarkdownLink(target, image, sourceChapter) {
    const trimmed = target.trim().replace(/^<|>$/g, '');
    if (/^(?:https?:|mailto:)/i.test(trimmed)) return trimmed;
    if (/^(?:javascript|data|vbscript):/i.test(trimmed)) return '#unsafe-link';
    const docUrl = new URL(sourceUrl(sourceChapter), window.location.origin);
    let resolved;
    try { resolved = new URL(trimmed, docUrl); } catch (_) { return '#invalid-link'; }
    const internalPath = decodeURIComponent(resolved.pathname).replace(/^\//, '');
    const targetChapter = bySourcePath.get(internalPath);
    if (targetChapter && !image) {
      return `?chapter=${encodeURIComponent(targetChapter.id)}${resolved.hash || ''}`;
    }
    if (resolved.pathname.startsWith('/engineering-study/')) {
      const maybeStudyFile = decodeURIComponent(resolved.pathname.slice('/engineering-study/'.length));
      const studyChapter = bySourcePath.get(`engineering-study/${maybeStudyFile}`);
      if (studyChapter && !image) return `?chapter=${encodeURIComponent(studyChapter.id)}${resolved.hash || ''}`;
    }
    return `${resolved.pathname}${resolved.search}${resolved.hash}`;
  }

  const markdownContext = (chapter) => ({
    resolveLink: (target, image) => resolveMarkdownLink(target, image, chapter)
  });

  async function fetchMarkdown(chapter) {
    const url = sourceUrl(chapter);
    if (!chapter._contentPromise) {
      chapter._contentPromise = fetch(url).then((response) => {
        if (!response.ok) throw new Error(`Could not load ${chapter.path} (${response.status})`);
        return response.text();
      });
    }
    return chapter._contentPromise;
  }

  function routeURL(id, hash = '') {
    return `${window.location.pathname}?chapter=${encodeURIComponent(id)}${hash || ''}`;
  }

  function navigate(id, hash = '', options = {}) {
    const chapter = byId.get(id);
    if (!chapter) return;
    if (options.push !== false) history.pushState({ chapter: id }, '', routeURL(id, hash));
    else history.replaceState({ chapter: id }, '', routeURL(id, hash));
    renderChapter(chapter, hash);
  }

  function showLoadError(error) {
    els.welcome.hidden = true;
    els.chapterContent.innerHTML = `<div class="load-error"><strong>The chapter could not be loaded.</strong><br>${StudyMarkdown.escapeHTML(error.message || String(error))}<br><br>Use the local server command in <a href="README.md">reader instructions</a>, then reload this page.</div>`;
  }

  async function renderChapter(chapter, hash = '') {
    activeId = chapter.id;
    state.lastChapter = chapter.id;
    saveState();
    updateTOCActive();
    els.welcome.hidden = true;
    els.chapterToolbar.hidden = false;
    els.chapterNav.hidden = false;
    els.chapterContent.innerHTML = '<div class="loading">Opening chapter…</div>';
    document.title = `${chapter.title} · JDev Engineering Study`;
    els.mobileChapterLabel.textContent = chapter.title;
    const sectionLabel = chapter.section;
    els.breadcrumb.innerHTML = `<span class="crumb-section">${StudyMarkdown.escapeHTML(sectionLabel)}</span><span class="crumb-sep">/</span><span>${StudyMarkdown.escapeHTML(chapter.title)}</span>`;
    const isComplete = state.completed.includes(chapter.id);
    els.completeButton.setAttribute('aria-pressed', String(isComplete));
    els.completeButton.querySelector('span:last-child').textContent = isComplete ? 'Chapter complete' : 'Mark chapter complete';
    buildChapterNav(chapter);

    try {
      const markdown = await fetchMarkdown(chapter);
      els.chapterContent.innerHTML = StudyMarkdown.render(markdown, markdownContext(chapter));
      buildOutline();
      await renderDiagrams();
      restoreScroll(chapter.id, hash);
    } catch (error) { showLoadError(error); }
  }

  function buildChapterNav(chapter) {
    const index = chapters.findIndex((item) => item.id === chapter.id);
    const previous = chapters[index - 1];
    const next = chapters[index + 1];
    const previousHTML = previous
      ? `<a href="?chapter=${encodeURIComponent(previous.id)}" data-chapter="${previous.id}"><small>← Previous chapter</small><strong>${StudyMarkdown.escapeHTML(previous.title)}</strong></a>`
      : '<div></div>';
    const nextHTML = next
      ? `<a class="next" href="?chapter=${encodeURIComponent(next.id)}" data-chapter="${next.id}"><small>Next chapter →</small><strong>${StudyMarkdown.escapeHTML(next.title)}</strong></a>`
      : '<div></div>';
    els.chapterNav.innerHTML = previousHTML + nextHTML;
    els.chapterNav.querySelectorAll('[data-chapter]').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault(); navigate(link.dataset.chapter);
    }));
  }

  function buildOutline() {
    currentOutline = [...els.chapterContent.querySelectorAll('h2, h3')].map((heading) => ({
      id: heading.id, title: heading.textContent.replace(/#$/, '').trim(), level: Number(heading.tagName.slice(1))
    }));
    const outline = document.getElementById('toc-outline');
    if (!outline) return;
    outline.innerHTML = currentOutline.map((heading) => `<a href="#${encodeURIComponent(heading.id)}" data-heading="${StudyMarkdown.escapeHTML(heading.id)}" class="outline-level-${heading.level}">${StudyMarkdown.escapeHTML(heading.title)}</a>`).join('');
    outline.querySelectorAll('[data-heading]').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault(); document.getElementById(link.dataset.heading)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      history.replaceState({ chapter: activeId }, '', routeURL(activeId, `#${encodeURIComponent(link.dataset.heading)}`));
      closeSidebarOnNarrow();
    }));
  }

  function restoreScroll(id, hash) {
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (hash) {
        const targetId = decodeURIComponent(hash.slice(1));
        document.getElementById(targetId)?.scrollIntoView();
      } else {
        const ratio = Number(state.scroll[id] || 0);
        const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        window.scrollTo(0, max * Math.min(1, Math.max(0, ratio)));
      }
      updateReadingProgress();
    }));
  }

  function updateReadingProgress() {
    const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const pct = Math.min(100, Math.max(0, window.scrollY / max * 100));
    els.readingProgressFill.style.width = `${pct}%`;
    if (activeId) {
      state.scroll[activeId] = pct / 100;
      clearTimeout(scrollTimer);
      scrollTimer = setTimeout(saveState, 220);
    }
  }

  function closeSidebarOnNarrow() {
    if (window.matchMedia('(max-width: 1050px)').matches) setSidebar(false);
  }

  function setSidebar(open) {
    const narrow = window.matchMedia('(max-width: 1050px)').matches;
    if (narrow) {
      document.body.classList.toggle('sidebar-open', open);
      els.tocToggle.setAttribute('aria-expanded', String(open));
    } else {
      state.sidebarCollapsed = !open;
      document.body.classList.toggle('sidebar-collapsed', !open);
      els.tocToggle.setAttribute('aria-expanded', String(open));
      saveState();
    }
  }

  function toggleComplete() {
    if (!activeId) return;
    const done = state.completed.includes(activeId);
    state.completed = done ? state.completed.filter((id) => id !== activeId) : [...state.completed, activeId];
    els.completeButton.setAttribute('aria-pressed', String(!done));
    els.completeButton.querySelector('span:last-child').textContent = done ? 'Mark chapter complete' : 'Chapter complete';
    makeTOC();
    saveState();
  }

  function mermaidScript() {
    if (window.mermaid) return Promise.resolve(true);
    if (mermaidPromise) return mermaidPromise;
    mermaidPromise = new Promise((resolve) => {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
      script.async = true;
      script.onload = () => resolve(Boolean(window.mermaid));
      script.onerror = () => resolve(false);
      document.head.appendChild(script);
      setTimeout(() => resolve(Boolean(window.mermaid)), 4500);
    });
    return mermaidPromise;
  }

  async function renderDiagrams() {
    const nodes = [...els.chapterContent.querySelectorAll('.mermaid')];
    if (!nodes.length) return;
    const available = await mermaidScript();
    if (available) {
      try {
        window.mermaid.initialize({
          startOnLoad: false, securityLevel: 'strict',
          theme: state.theme === 'dark' ? 'dark' : 'neutral',
          flowchart: { htmlLabels: false, curve: 'linear' }
        });
        await window.mermaid.run({ nodes });
        els.chapterContent.querySelectorAll('.diagram-source').forEach((details) => { details.open = false; });
      } catch (_) { markDiagramsUnavailable(nodes); }
    } else markDiagramsUnavailable(nodes);
    els.chapterContent.querySelectorAll('.diagram-source-toggle').forEach((button) => button.addEventListener('click', () => {
      const details = button.closest('.diagram-block').querySelector('.diagram-source');
      details.open = !details.open;
      button.textContent = details.open ? 'Hide source' : 'Show source';
    }));
  }

  function markDiagramsUnavailable(nodes) {
    nodes.forEach((node) => {
      const block = node.closest('.diagram-block');
      block.classList.add('no-mermaid');
      const details = block.querySelector('.diagram-source');
      details.open = true;
      block.querySelector('.diagram-source-toggle').textContent = 'Hide source';
      const note = document.createElement('div');
      note.className = 'diagram-unavailable';
      note.textContent = 'Diagram renderer unavailable; showing the original diagram source.';
      block.appendChild(note);
    });
  }

  function openSearch() {
    els.searchOverlay.classList.add('open');
    els.searchOverlay.setAttribute('aria-hidden', 'false');
    els.searchInput.value = '';
    els.searchResults.innerHTML = '';
    els.searchStatus.querySelector('span:last-child').textContent = 'Type at least 2 characters';
    setTimeout(() => els.searchInput.focus(), 0);
  }

  function closeSearch() {
    els.searchOverlay.classList.remove('open');
    els.searchOverlay.setAttribute('aria-hidden', 'true');
    els.searchTrigger.focus();
  }

  function buildSearchIndex() {
    if (searchIndex) return Promise.resolve(searchIndex);
    searchIndex = Promise.all(chapters.map(async (chapter) => {
      const text = await fetchMarkdown(chapter);
      const sections = [];
      let heading = chapter.title;
      let lines = [];
      const flush = () => {
        const body = lines.join(' ').replace(/[`*_>#|]/g, ' ').replace(/\s+/g, ' ').trim();
        if (body) sections.push({ chapter, heading, body, searchable: `${chapter.title} ${heading} ${body}`.toLowerCase() });
        lines = [];
      };
      for (const line of text.split(/\r?\n/)) {
        const match = line.match(/^#{1,6}\s+(.+)/);
        if (match) { flush(); heading = match[1].replace(/[`*_]/g, '').trim(); }
        else if (!/^\s*```/.test(line) && line.trim()) lines.push(line);
      }
      flush();
      return sections;
    })).then((all) => all.flat()).catch((error) => {
      searchIndex = null;
      throw error;
    });
    return searchIndex;
  }

  function makeSnippet(text, query) {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const lower = text.toLowerCase();
    const at = Math.max(0, Math.min(...words.map((word) => {
      const found = lower.indexOf(word); return found < 0 ? lower.length : found;
    })) - 62);
    let snippet = text.slice(at, at + 180);
    if (at > 0) snippet = `…${snippet}`;
    if (at + 180 < text.length) snippet += '…';
    const escaped = StudyMarkdown.escapeHTML(snippet);
    const pattern = new RegExp(`(${query.trim().split(/\s+/).filter(Boolean).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig');
    return escaped.replace(pattern, '<mark>$1</mark>');
  }

  let searchResultsData = [];
  function renderSearchResults(query) {
    if (query.trim().length < 2) {
      els.searchResults.innerHTML = '';
      els.searchStatus.querySelector('span:last-child').textContent = 'Type at least 2 characters';
      return;
    }
    els.searchStatus.querySelector('span:last-child').textContent = 'Searching chapters…';
    buildSearchIndex().then((index) => {
      const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
      searchResultsData = index.map((item) => ({
        ...item,
        score: terms.reduce((score, term) => score + (item.searchable.includes(term) ? 1 : -100), 0) +
          (item.heading.toLowerCase().includes(query.toLowerCase()) ? 2 : 0)
      })).filter((item) => item.score >= terms.length).sort((a, b) => b.score - a.score).slice(0, 15);
      searchSelection = 0;
      els.searchStatus.querySelector('span:last-child').textContent = `${searchResultsData.length} result${searchResultsData.length === 1 ? '' : 's'}`;
      if (!searchResultsData.length) {
        els.searchResults.innerHTML = '<div class="search-empty">No matching chapter text. Try another phrase.</div>';
        return;
      }
      els.searchResults.innerHTML = searchResultsData.map((item, indexNo) => `<button class="search-result${indexNo === 0 ? ' selected' : ''}" data-result="${indexNo}"><span class="result-top"><span class="result-chapter">${StudyMarkdown.escapeHTML(item.chapter.title)}</span><span class="result-section">${StudyMarkdown.escapeHTML(item.chapter.section)}</span></span><span class="result-heading">${StudyMarkdown.escapeHTML(item.heading)}</span><span class="result-snippet">${makeSnippet(item.body, query)}</span></button>`).join('');
      els.searchResults.querySelectorAll('[data-result]').forEach((button) => button.addEventListener('click', () => openSearchResult(Number(button.dataset.result))));
    }).catch((error) => {
      els.searchStatus.querySelector('span:last-child').textContent = 'Search unavailable';
      els.searchResults.innerHTML = `<div class="search-empty">${StudyMarkdown.escapeHTML(error.message)}</div>`;
    });
  }

  function updateSearchSelection(delta) {
    if (!searchResultsData.length) return;
    searchSelection = (searchSelection + delta + searchResultsData.length) % searchResultsData.length;
    els.searchResults.querySelectorAll('.search-result').forEach((result, index) => result.classList.toggle('selected', index === searchSelection));
    els.searchResults.querySelector('.search-result.selected')?.scrollIntoView({ block: 'nearest' });
  }

  function openSearchResult(index) {
    const result = searchResultsData[index];
    if (!result) return;
    const chapterText = result.chapter._contentPromise;
    closeSearch();
    navigate(result.chapter.id);
    Promise.resolve(chapterText).then((text) => {
      const match = text.split(/\r?\n/).find((line) => line.match(/^#{1,6}\s+/) && line.replace(/^#+\s*/, '').replace(/[`*_]/g, '').trim() === result.heading);
      if (match) {
        const headingId = StudyMarkdown.slugify(match.replace(/^#+\s*/, '').replace(/[`*_]/g, ''));
        setTimeout(() => document.getElementById(headingId)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 90);
      }
    });
  }

  function bindEvents() {
    els.tocToggle.addEventListener('click', () => {
      const narrow = window.matchMedia('(max-width: 1050px)').matches;
      const open = narrow ? !document.body.classList.contains('sidebar-open') : document.body.classList.contains('sidebar-collapsed');
      setSidebar(open);
    });
    els.scrim.addEventListener('click', () => setSidebar(false));
    els.themeToggle.addEventListener('click', () => setTheme(state.theme === 'dark' ? 'light' : 'dark'));
    els.searchTrigger.addEventListener('click', openSearch);
    els.searchOverlay.addEventListener('click', (event) => { if (event.target === els.searchOverlay) closeSearch(); });
    els.searchInput.addEventListener('input', () => renderSearchResults(els.searchInput.value));
    els.searchInput.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') { event.preventDefault(); updateSearchSelection(1); }
      if (event.key === 'ArrowUp') { event.preventDefault(); updateSearchSelection(-1); }
      if (event.key === 'Enter') { event.preventDefault(); openSearchResult(searchSelection); }
      if (event.key === 'Escape') closeSearch();
    });
    els.completeButton.addEventListener('click', toggleComplete);
    els.beginButton.addEventListener('click', () => navigate(chapters[0].id));
    els.chapterContent.addEventListener('click', (event) => {
      const anchor = event.target.closest('a[href]');
      if (!anchor) return;
      const target = new URL(anchor.href, location.href);
      if (target.origin !== location.origin) return;
      const chapterId = new URLSearchParams(target.search).get('chapter');
      if (target.pathname === location.pathname && chapterId && byId.has(chapterId)) {
        event.preventDefault();
        navigate(chapterId, target.hash);
      } else if (target.pathname === location.pathname && target.hash && !target.search) {
        event.preventDefault();
        document.getElementById(decodeURIComponent(target.hash.slice(1)))?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
    window.addEventListener('scroll', updateReadingProgress, { passive: true });
    window.addEventListener('popstate', () => {
      const params = new URLSearchParams(location.search);
      const chapter = byId.get(params.get('chapter'));
      if (chapter) renderChapter(chapter, location.hash);
      else showWelcome();
    });
    window.addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch(); }
      if (event.key === 'Escape' && els.searchOverlay.classList.contains('open')) closeSearch();
      if (event.altKey && event.key === 'ArrowLeft') { const index = chapters.findIndex((c) => c.id === activeId); if (chapters[index - 1]) navigate(chapters[index - 1].id); }
      if (event.altKey && event.key === 'ArrowRight') { const index = chapters.findIndex((c) => c.id === activeId); if (chapters[index + 1]) navigate(chapters[index + 1].id); }
    });
  }

  function showWelcome() {
    activeId = null;
    document.title = 'JDev Engineering Study';
    els.welcome.hidden = false;
    els.chapterContent.innerHTML = '';
    els.chapterToolbar.hidden = true;
    els.chapterNav.hidden = true;
    els.mobileChapterLabel.textContent = '';
    updateTOCActive();
    els.readingProgressFill.style.width = '0';
  }

  async function init() {
    setTheme(state.theme);
    const narrow = window.matchMedia('(max-width: 1050px)').matches;
    if (!narrow) document.body.classList.toggle('sidebar-collapsed', Boolean(state.sidebarCollapsed));
    bindEvents();
    try {
      const response = await fetch('/engineering-study/reader/chapters.json');
      if (!response.ok) throw new Error(`Could not load chapter manifest (${response.status})`);
      manifest = await response.json();
      chapters = allChapters();
      byId = new Map(chapters.map((chapter) => [chapter.id, chapter]));
      bySourcePath = new Map(chapters.map((chapter) => [`engineering-study/${chapter.path}`, chapter]));
      makeTOC();
      const params = new URLSearchParams(location.search);
      const initial = byId.get(params.get('chapter')) || byId.get(state.lastChapter);
      if (initial) {
        if (!params.get('chapter')) history.replaceState({ chapter: initial.id }, '', routeURL(initial.id));
        renderChapter(initial, location.hash);
      } else showWelcome();
    } catch (error) {
      els.chapterContent.innerHTML = `<div class="load-error">Reader could not start: ${StudyMarkdown.escapeHTML(error.message)}. Run the local server from the repository root as described in README.md.</div>`;
    }
  }

  init();
})();
