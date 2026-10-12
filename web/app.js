'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const model = { token: '', topics: [], settings: {}, papers: [], selected: new Set(), topic: '', show: 'all', detailId: null, task: null, previewIds: [], previewReady: false, previewBusy: false, importing: false, querySerial: 0, detailSerial: 0, previewSerial: 0, editingPaperId: null, classificationSerial: 0 };
  const statusNames = { create: '新增笔记', new: '新增笔记', import: '新增笔记', skip: '跳过已有论文', duplicate: '已在文献库', exists: '已在文献库', update_available: '已有笔记 · 新版可用', conflict: '需要核对', error: '失败', imported: '已入库', created: '已入库', skipped: '已跳过', success: '已入库', pending: '待核实', verified: '已核实', partial: '部分已核实', unavailable: '待核实', unknown: '待核实' };
  const taskNames = { running: '进行中', pending: '等待开始', completed: '已完成', complete: '已完成', failed: '失败', cancelled: '已取消', canceled: '已取消', idle: '暂无任务' };
  let pollTimer;
  let searchTimer;
  let connectionError = false;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function array(value) { return Array.isArray(value) ? value : []; }
  function label(value) { return statusNames[value] || String(value || '待核实'); }
  function date(value, includeTime = false) {
    if (!value) return '日期待核实';
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}) }).format(parsed);
  }

  function arxivLink(value) {
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== 'https:' || !['arxiv.org', 'www.arxiv.org', 'export.arxiv.org'].includes(parsed.hostname) || parsed.username || parsed.password || parsed.port) return null;
      if (!/^\/(abs|pdf|html)\/[A-Za-z0-9._/-]+$/.test(parsed.pathname)) return null;
      return parsed.href;
    } catch { return null; }
  }

  function reportLink(value) {
    try {
      const parsed = new URL(value, window.location.origin);
      if (parsed.origin !== window.location.origin || !/^\/reports\/[^/]+$/.test(parsed.pathname) || parsed.search || parsed.hash) return null;
      return parsed.href;
    } catch { return null; }
  }

  function link(text, href, external = true) {
    const anchor = node('a', '', text);
    anchor.href = href;
    if (external) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer'; }
    return anchor;
  }

  async function api(path, body) {
    const options = { credentials: 'same-origin', headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      if (!model.token) throw new Error('尚未连接本地论文雷达，请等待连接或刷新页面。');
      options.method = 'POST';
      options.headers['Content-Type'] = 'application/json';
      options.headers['X-Radar-Token'] = model.token;
      options.body = JSON.stringify(body);
    }
    let response;
    try { response = await fetch(path, options); }
    catch { throw new Error('无法连接本地论文雷达，请确认启动窗口仍在运行。'); }
    let data;
    try { data = await response.json(); }
    catch { throw new Error('服务返回了无法读取的内容，请稍后重试。'); }
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data.error || `请求失败（${response.status}）`);
      throw new Error(detail);
    }
    return data;
  }

  function notice(message, error = false) {
    $('notice').textContent = message;
    $('notice').classList.toggle('error', error);
    $('notice').hidden = !message;
  }

  function formError(id, error) {
    $(id).textContent = error ? error.message || String(error) : '';
    $(id).hidden = !error;
  }

  function openDialog(id) {
    const dialog = $(id);
    if (!dialog.open) dialog.showModal();
  }

  function topicName(id) { return model.topics.find((topic) => topic.id === id)?.name || id; }
  function imported(paper) { return Boolean(paper.imported || paper.existing_path); }

  function renderTopics() {
    const nav = $('topic-nav');
    nav.replaceChildren();
    const all = node('button', 'topic-button', '全部方向');
    all.type = 'button'; all.dataset.topic = ''; all.setAttribute('aria-pressed', String(model.topic === ''));
    all.classList.toggle('active', model.topic === '');
    nav.append(all);
    $('fetch-topics').replaceChildren();
    for (const topic of model.topics) {
      const button = node('button', 'topic-button', topic.name);
      button.type = 'button'; button.dataset.topic = topic.id;
      button.title = topic.description || topic.name;
      button.classList.toggle('active', model.topic === topic.id);
      button.setAttribute('aria-pressed', String(model.topic === topic.id));
      nav.append(button);
      const row = node('label', 'fetch-topic');
      const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.name = 'fetch-topic'; checkbox.value = topic.id; checkbox.checked = true;
      row.append(checkbox, node('span', '', topic.name));
      $('fetch-topics').append(row);
    }
  }

  function renderStats(stats) {
    const values = [stats?.total ?? stats?.papers, stats?.new ?? stats?.unimported, stats?.imported ?? stats?.existing];
    ['stat-total', 'stat-new', 'stat-imported'].forEach((id, index) => {
      $(id).textContent = values[index] == null ? '—' : Number(values[index]).toLocaleString('zh-CN');
    });
  }

  function renderTask(task) {
    const running = Boolean(task?.running);
    const counts = task && (task.fetched != null || task.new != null) ? `获取 ${task.fetched ?? 0} 篇 · 新增 ${task.new ?? 0} 篇` : '';
    const limitations = task?.truncated ? '已达到预算，检索范围尚未完整覆盖' : '';
    const failureCount = Array.isArray(task?.failures) ? task.failures.length : Number(task?.failures || 0);
    const failures = failureCount > 0 ? `${failureCount} 项请求失败，详见日志` : '';
    const description = task ? [taskNames[task.status] || task.status, task.message, counts, limitations, failures, task.error].filter(Boolean).join(' · ') : '暂无正在运行的任务';
    $('task-message').textContent = description;
    $('cancel-button').hidden = !running;
    $('fetch-button').disabled = running;
    $('empty-fetch-button').disabled = running;
    $('fetch-submit').disabled = running;
    const progress = $('task-progress');
    progress.hidden = !running;
    if (running && Number(task.total) > 0) { progress.max = Number(task.total); progress.value = Math.min(Number(task.completed) || 0, Number(task.total)); }
    else { progress.removeAttribute('value'); }
    for (const button of $('detail-content').querySelectorAll('[data-enrich]')) button.disabled = running;
    $('logs-button').textContent = running ? '● 任务进行中' : '任务与日志';
  }

  async function loadState() {
    const state = await api('/api/state');
    const oldRunning = Boolean(model.task?.running);
    model.token = state.token;
    model.settings = state.settings || {};
    model.task = state.task;
    const topicsChanged = JSON.stringify(model.topics) !== JSON.stringify(state.topics || []);
    model.topics = array(state.topics);
    if (topicsChanged) renderTopics();
    renderStats(state.stats); renderTask(state.task);
    $('connection-dot').classList.add('connected');
    $('connection-label').textContent = '本地服务已连接';
    const recovered = connectionError;
    if (recovered) { connectionError = false; notice('已重新连接本地论文雷达。'); }
    updateSelection();
    if (recovered && !(oldRunning && !state.task?.running)) { await loadPapers(); await loadReports(); }
    if (oldRunning && !state.task?.running) {
      await loadPapers();
      if (model.detailId) await loadDetail(model.detailId, false);
      await loadReports();
      if (state.task?.error || state.task?.status === 'failed') notice(state.task.error || state.task.message || '任务失败，请查看日志。', true);
      else notice(state.task?.message || '任务已结束，候选列表已刷新。');
    }
    return state;
  }

  function updateSelection() {
    const count = model.selected.size;
    $('selection-count').textContent = `已选 ${count} 篇`;
    $('preview-button').disabled = !count || !model.token;
    $('clear-selection').hidden = count === 0;
    const visible = model.papers.filter((paper) => model.selected.has(paper.id)).length;
    $('select-all').checked = model.papers.length > 0 && visible === model.papers.length;
    $('select-all').indeterminate = visible > 0 && visible < model.papers.length;
    $('select-all').disabled = !model.papers.length;
    for (const checkbox of $('paper-list').querySelectorAll('.paper-check')) checkbox.checked = model.selected.has(checkbox.value);
  }

  function renderPapers(papers, total) {
    const list = $('paper-list');
    list.replaceChildren();
    $('result-count').textContent = `${Number(total ?? papers.length).toLocaleString('zh-CN')} 篇候选`;
    $('list-empty').hidden = papers.length > 0;
    const filtered = model.topic || $('search-input').value || model.show !== 'all' || Number($('score-input').value) > 0;
    $('empty-title').textContent = filtered ? '当前条件下没有候选' : '研究从一个问题开始';
    $('empty-description').textContent = filtered ? '可以调整方向、关键词或最低分数，也可以抓取更多近期论文。' : '选择关注的方向，抓取近期论文。每一条候选都保留原始来源。';
    for (const paper of papers) {
      const card = node('article', 'paper-card');
      card.dataset.id = paper.id;
      card.addEventListener('click', (event) => {
        if (event.target.closest('button, a, input, label')) return;
        if (window.getSelection()?.toString()) return;
        loadDetail(paper.id);
      });
      card.classList.toggle('current', paper.id === model.detailId);
      const checkbox = node('input', 'paper-check');
      checkbox.type = 'checkbox'; checkbox.value = paper.id; checkbox.checked = model.selected.has(paper.id);
      checkbox.setAttribute('aria-label', `选择论文：${paper.title}`);
      checkbox.addEventListener('change', () => { if (checkbox.checked) model.selected.add(paper.id); else model.selected.delete(paper.id); updateSelection(); });
      const meta = node('div', 'paper-meta');
      const left = node('div', 'paper-meta-left');
      left.append(node('span', '', `arXiv ${paper.id}`), node('span', '', date(paper.published)));
      meta.append(left, node('span', 'score', `匹配 ${paper.score ?? 0}`));
      const title = node('button', 'paper-title', paper.title || '标题待核实');
      title.type = 'button'; title.addEventListener('click', () => loadDetail(paper.id));
      const authors = array(paper.authors).map((author) => typeof author === 'string' ? author : author.name).filter(Boolean);
      const byline = node('p', 'paper-authors', authors.slice(0, 3).join(' · ') + (authors.length > 3 ? ` 等 ${authors.length} 位作者` : ''));
      const footer = node('div', 'paper-footer');
      for (const id of array(paper.topics)) footer.append(node('span', 'tag', topicName(id)));
      const status = node('span', `status-tag${imported(paper) ? ' imported' : ''}`, imported(paper) ? '✓ 已在文献库' : '○ 尚未入库');
      if (paper.existing_path) status.title = paper.existing_path;
      footer.append(status);
      const view = node('button', 'text-button view-detail', '查看详情 →');
      view.type = 'button'; view.setAttribute('aria-label', `查看详情：${paper.title}`);
      view.addEventListener('click', () => loadDetail(paper.id));
      footer.append(view);
      const excerpt = node('p', 'paper-excerpt', paper.abstract_zh || paper.abstract || '暂无可用摘要');
      excerpt.lang = paper.abstract_zh ? 'zh-CN' : 'en';
      card.append(checkbox, meta, title, byline, excerpt, footer);
      list.append(card);
    }
    list.setAttribute('aria-busy', 'false');
    updateSelection();
  }

  async function loadPapers() {
    const serial = ++model.querySerial;
    $('paper-list').setAttribute('aria-busy', 'true');
    $('result-count').textContent = '正在加载…';
    const params = new URLSearchParams({ topic: model.topic, q: $('search-input').value.trim(), min_score: $('score-input').value || '0', show: model.show });
    try {
      const response = await api(`/api/papers?${params}`);
      if (serial !== model.querySerial) return;
      model.papers = array(response.papers);
      renderPapers(model.papers, response.total);
    } catch (error) {
      if (serial !== model.querySerial) return;
      $('paper-list').setAttribute('aria-busy', 'false');
      $('result-count').textContent = '加载失败';
      notice(error.message, true);
      if (!model.papers.length) {
        $('list-empty').hidden = false;
        $('empty-title').textContent = '暂时无法加载候选';
        $('empty-description').textContent = error.message;
      }
    }
  }

  function section(title) {
    const element = node('section', 'detail-section');
    element.append(node('h3', '', title));
    return element;
  }

  function renderDetail(paper) {
    const content = $('detail-content'); content.replaceChildren();
    $('detail-placeholder').hidden = true; content.hidden = false;
    const top = node('div', 'detail-top');
    top.append(node('span', '', '论文详情 · PAPER NOTES'));
    const close = node('button', 'icon-button', '×'); close.type = 'button'; close.setAttribute('aria-label', '关闭论文详情');
    close.addEventListener('click', closeDetail); top.append(close);
    const body = node('div', 'detail-body');
    body.append(node('h2', 'detail-title', paper.title));
    const version = String(paper.version || '1').replace(/^v/, '');
    body.append(node('p', 'detail-meta', `arXiv ${paper.id} · v${version}\n提交 ${date(paper.published)} · 更新 ${date(paper.updated)}`));
    const tags = node('div', 'detail-tags');
    array(paper.topics).forEach((id) => tags.append(node('span', 'tag', topicName(id))));
    array(paper.categories).forEach((category) => tags.append(node('span', 'tag', category)));
    body.append(tags);
    const links = node('div', 'detail-links');
    const original = arxivLink(paper.url); const pdf = arxivLink(paper.pdf_url);
    if (original) links.append(link('arXiv 原文 ↗', original));
    if (pdf) links.append(link('PDF ↗', pdf));
    body.append(links);
    if (imported(paper)) body.append(node('p', 'path-text', `已在文献库${paper.existing_path ? `\n${paper.existing_path}` : ''}`));
    const chinese = section('中文摘要');
    const chineseText = node('p', 'abstract', paper.abstract_zh || (paper.abstract_zh_status === 'outdated' ? '原文已更新，中文摘要待更新。' : '中文摘要待整理，完成后会显示在这里。'));
    chineseText.lang = 'zh-CN'; chinese.append(chineseText);
    if (paper.abstract_zh) {
      chinese.append(node('p', 'field-status', '依据对应版本的 arXiv 原始摘要整理。'));
      if (paper.abstract_zh_source) {
        const source = reportLink(`/reports/${encodeURIComponent(paper.abstract_zh_source)}`);
        if (source) chinese.append(link('查看中文简报 ↗', source));
      }
    }
    body.append(chinese);
    const classification = section('研究分类');
    classification.append(node('p', '', `方向：${array(paper.topics).map(topicName).join('；') || '尚未分类'}`));
    classification.append(node('p', '', `关键词：${array(paper.keywords).join('；') || '尚未设置'}`));
    if (paper.manual_topics) classification.append(node('p', 'field-status', '已按你的选择调整方向'));
    const edit = node('button', 'button small', '调整分类'); edit.type = 'button'; edit.addEventListener('click', () => editClassification(paper));
    classification.append(edit); body.append(classification);
    const authors = section('作者与单位');
    const authorList = node('ul', 'author-list');
    for (const author of array(paper.authors)) {
      const item = node('li', '', typeof author === 'string' ? author : author.name);
      const affiliations = array(author.affiliations);
      item.append(node('small', '', affiliations.length ? affiliations.join('；') : '单位待核实'));
      authorList.append(item);
    }
    authors.append(authorList);
    if (!authorList.children.length) authors.append(node('p', 'muted', '作者信息待核实'));
    if (array(paper.institutions).length) authors.append(node('p', '', `机构：${paper.institutions.join('；')}`));
    authors.append(node('p', 'field-status', `核实状态：${label(paper.affiliation_status)}`));
    if (paper.affiliation_source) {
      const source = arxivLink(paper.affiliation_source);
      authors.append(source ? link('查看单位来源 ↗', source) : node('p', 'field-status', `来源：${paper.affiliation_source}`));
    }
    const enrich = node('button', 'button small', '核实作者单位'); enrich.type = 'button'; enrich.dataset.enrich = 'true'; enrich.disabled = Boolean(model.task?.running);
    enrich.addEventListener('click', async () => {
      enrich.disabled = true;
      try { const task = await api('/api/enrich', { ids: [paper.id] }); model.task = task; renderTask(task); notice('单位核实已开始，可以在任务与日志中查看进度。'); await loadState(); }
      catch (error) { notice(error.message, true); enrich.disabled = false; }
    });
    authors.append(enrich); body.append(authors);
    const abstract = section('原始摘要');
    const abstractText = node('p', 'abstract', paper.abstract || '暂无可用摘要'); abstractText.lang = 'en'; abstract.append(abstractText); body.append(abstract);
    const reasons = section(`匹配依据 · ${paper.score ?? 0} 分`);
    const reasonList = node('ul', 'reason-list'); array(paper.reasons).forEach((reason) => reasonList.append(node('li', '', reason)));
    reasons.append(reasonList, node('p', 'field-status', '分数反映检索规则的命中程度，请结合原文判断相关性。'));
    body.append(reasons); content.append(top, body);
  }

  async function loadDetail(id, focus = true) {
    model.detailId = id;
    const serial = ++model.detailSerial;
    for (const card of $('paper-list').children) card.classList.toggle('current', card.dataset.id === id);
    const detail = $('paper-detail'); detail.classList.add('open');
    if (focus) detail.scrollTop = 0;
    if (window.matchMedia('(max-width: 1040px)').matches) { detail.setAttribute('role', 'dialog'); detail.setAttribute('aria-modal', 'true'); }
    $('detail-placeholder').hidden = true; $('detail-content').hidden = false;
    $('detail-content').replaceChildren(node('p', 'loading-text', '正在读取论文详情…'));
    try {
      const paper = await api(`/api/papers/${encodeURIComponent(id)}`);
      if (serial !== model.detailSerial) return;
      renderDetail(paper);
      if (focus && window.matchMedia('(max-width: 1040px)').matches) $('detail-content').querySelector('button')?.focus();
    } catch (error) {
      if (serial !== model.detailSerial) return;
      $('detail-content').replaceChildren(node('p', 'loading-text', error.message));
      const close = node('button', 'button', '关闭详情'); close.addEventListener('click', closeDetail); $('detail-content').append(close);
      notice(error.message, true);
    }
  }

  function closeDetail() {
    const id = model.detailId;
    model.detailSerial++; model.detailId = null;
    $('paper-detail').classList.remove('open'); $('paper-detail').removeAttribute('role'); $('paper-detail').removeAttribute('aria-modal'); $('detail-placeholder').hidden = false; $('detail-content').hidden = true;
    for (const card of $('paper-list').children) {
      card.classList.remove('current');
      if (card.dataset.id === id) card.querySelector('.paper-title')?.focus();
    }
  }

  async function loadLogs() {
    try {
      const response = await api('/api/logs'); const container = $('logs-list'); container.replaceChildren();
      for (const item of array(response.logs)) {
        const row = node('div', `log-row${item.level === 'error' ? ' error' : ''}`);
        row.append(node('time', '', date(item.time, true)), node('span', '', item.message)); container.append(row);
      }
      if (!container.children.length) container.append(node('p', 'muted', '暂无日志。开始抓取后，这里会记录检索进度。'));
      container.scrollTop = container.scrollHeight;
    } catch (error) { $('logs-list').replaceChildren(node('p', 'form-error', error.message)); }
  }

  function updateKeywordCount() {
    const count = $('classification-keywords').querySelectorAll('input:checked').length;
    $('keyword-count').textContent = `已选 ${count} / 4`;
  }

  async function editClassification(paper) {
    const serial = ++model.classificationSerial;
    model.editingPaperId = paper.id;
    $('classification-title').textContent = paper.title;
    $('keyword-search').value = '';
    formError('classification-error', null);
    $('classification-submit').disabled = true;
    $('classification-topics').replaceChildren();
    for (const topic of model.topics) {
      const row = node('label', 'fetch-topic');
      const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.value = topic.id; checkbox.checked = array(paper.topics).includes(topic.id);
      row.append(checkbox, node('span', '', topic.name)); $('classification-topics').append(row);
    }
    $('classification-keywords').replaceChildren(node('p', 'muted', '正在读取文献库关键词…'));
    $('keyword-count').textContent = '已选 0 / 4';
    openDialog('classification-dialog');
    try {
      const result = await api('/api/keywords');
      if (serial !== model.classificationSerial) return;
      const keywords = array(result.keywords).filter((keyword) => typeof keyword === 'string');
      const container = $('classification-keywords'); container.replaceChildren();
      for (const keyword of keywords) {
        const row = node('label', 'fetch-topic keyword-option'); row.dataset.keyword = keyword.toLocaleLowerCase();
        const checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.value = keyword; checkbox.checked = array(paper.keywords).includes(keyword);
        checkbox.addEventListener('change', () => {
          if (container.querySelectorAll('input:checked').length > 4) { checkbox.checked = false; formError('classification-error', new Error('最多选择四个关键词。')); }
          else formError('classification-error', null);
          updateKeywordCount();
        });
        row.append(checkbox, node('span', '', keyword)); container.append(row);
      }
      if (!keywords.length) container.append(node('p', 'muted', '当前文献库没有可复用的关键词，可以只保存研究方向。'));
      updateKeywordCount(); $('classification-submit').disabled = false;
    } catch (error) {
      if (serial !== model.classificationSerial) return;
      $('classification-keywords').replaceChildren(node('p', 'muted', '关键词读取失败，请关闭后重新打开。'));
      formError('classification-error', error);
    }
  }

  async function loadReports() {
    try {
      const response = await api('/api/digests'); const container = $('reports-list'); container.replaceChildren();
      for (const report of array(response.digests)) {
        const url = reportLink(report.url); const row = node('div', 'report-item');
        row.append(url ? link(`${report.name} ↓`, url, false) : node('span', '', report.name), node('time', '', date(report.created, true)));
        container.append(row);
      }
      if (!container.children.length) container.append(node('p', 'muted', '还没有简报。完成抓取后，新发现会汇总在这里。'));
    } catch (error) { $('reports-list').replaceChildren(node('p', 'form-error', error.message)); }
  }

  function renderPreview(preview) {
    $('preview-vault').textContent = `目标文献库：${preview.vault_path || model.settings.vault_path || '尚未设置'}`;
    $('preview-warnings').replaceChildren();
    array(preview.warnings).forEach((warning) => $('preview-warnings').append(node('p', '', warning)));
    const items = $('preview-items'); items.replaceChildren();
    for (const item of array(preview.items)) {
      const row = node('div', 'preview-item');
      row.append(node('h3', '', item.title || item.id), node('span', 'tag', label(item.action)));
      if (item.reason) row.append(node('p', '', item.reason));
      if (item.path) row.append(node('p', '', item.path));
      items.append(row);
    }
    if (!items.children.length) items.append(node('p', 'muted', '没有可导入的论文。'));
    const files = array(preview.files);
    const fileContainer = $('preview-files'); fileContainer.replaceChildren(); fileContainer.hidden = !files.length;
    if (files.length) {
      const details = node('details', 'file-change-details');
      details.append(node('summary', '', `本次文件变更（${files.length}）`));
      const fileList = node('ul', 'file-change-list');
      for (const file of files) {
        const row = node('li');
        row.append(node('span', 'tag', file.action === 'create' ? '新增' : file.action === 'modify' ? '追加修改' : file.action), node('span', 'file-change-path', file.path));
        fileList.append(row);
      }
      details.append(fileList); fileContainer.append(details);
    }
    model.previewReady = items.children.length > 0 && array(preview.items).length > 0;
    $('import-button').disabled = !model.previewReady;
  }

  async function loadPreview() {
    const serial = ++model.previewSerial;
    model.previewReady = false; model.previewBusy = true;
    $('import-button').disabled = true; $('queue-input').disabled = true;
    $('preview-files').hidden = true; $('preview-files').replaceChildren();
    $('preview-items').replaceChildren(node('p', 'loading-text', '正在核对文献库与写入计划…'));
    formError('preview-error', null);
    try {
      const preview = await api('/api/preview', { ids: model.previewIds, queue: $('queue-input').checked });
      if (serial === model.previewSerial) renderPreview(preview);
    } catch (error) {
      if (serial === model.previewSerial) { $('preview-items').replaceChildren(); formError('preview-error', error); }
    } finally {
      if (serial === model.previewSerial) { model.previewBusy = false; $('queue-input').disabled = false; }
    }
  }

  async function doImport() {
    if (!model.previewReady || model.importing || model.previewBusy) return;
    model.importing = true; $('import-button').disabled = true; $('queue-input').disabled = true;
    $('import-button').textContent = '正在入库…'; formError('preview-error', null);
    try {
      const result = await api('/api/import', { ids: model.previewIds, queue: $('queue-input').checked });
      const container = $('import-results'); container.replaceChildren(node('h3', '', '本次入库结果')); container.hidden = false;
      for (const item of array(result.results)) {
        const row = node('div', 'import-result'); const title = model.papers.find((paper) => paper.id === item.id)?.title || item.id;
        row.append(node('h3', '', title), node('span', 'tag', label(item.status)));
        if (item.message) row.append(node('p', '', item.message));
        if (item.path) row.append(node('p', '', item.path));
        container.append(row);
        if (!['error', 'conflict', 'failed'].includes(item.status)) model.selected.delete(item.id);
      }
      if (result.backup_path) container.append(node('p', 'backup-note', `备份已保存：${result.backup_path}`));
      model.previewReady = false; $('preview-items').hidden = true; $('preview-warnings').hidden = true;
      await loadState(); await loadPapers();
      if (model.detailId) await loadDetail(model.detailId, false);
      notice('入库请求已处理，请查看每篇论文的结果。');
    } catch (error) { formError('preview-error', error); $('import-button').disabled = false; }
    finally { model.importing = false; $('queue-input').disabled = !model.previewReady; $('import-button').textContent = '确认入库'; }
  }

  function showFetch() { formError('fetch-error', null); openDialog('fetch-dialog'); }
  function togglePanel(id, buttonId) {
    $(id).hidden = !$(id).hidden;
    $(buttonId).setAttribute('aria-expanded', String(!$(id).hidden));
    if (!$(id).hidden) (id === 'activity-panel' ? loadLogs() : loadReports());
  }

  $('topic-nav').addEventListener('click', (event) => {
    const button = event.target.closest('[data-topic]'); if (!button) return;
    model.topic = button.dataset.topic;
    for (const item of $('topic-nav').querySelectorAll('button')) { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', String(active)); }
    const topic = model.topics.find((item) => item.id === model.topic);
    $('page-title').textContent = topic?.name || '发现值得阅读的论文';
    $('page-description').textContent = topic?.description || '关注模型与智能体安全，把线索沉淀为知识。';
    $('breadcrumb-current').textContent = topic?.name || '候选论文';
    loadPapers();
  });
  for (const button of document.querySelectorAll('[data-show]')) button.addEventListener('click', () => {
    model.show = button.dataset.show;
    for (const item of document.querySelectorAll('[data-show]')) { item.classList.toggle('active', item === button); item.setAttribute('aria-pressed', String(item === button)); }
    loadPapers();
  });
  $('search-input').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadPapers, 250); });
  $('score-input').addEventListener('change', () => { $('score-input').value = String(Math.max(0, Math.min(100, Number($('score-input').value) || 0))); loadPapers(); });
  $('select-all').addEventListener('change', () => { for (const paper of model.papers) { if ($('select-all').checked) model.selected.add(paper.id); else model.selected.delete(paper.id); } updateSelection(); });
  $('clear-selection').addEventListener('click', () => { model.selected.clear(); updateSelection(); });
  $('fetch-button').addEventListener('click', showFetch); $('empty-fetch-button').addEventListener('click', showFetch);
  $('logs-button').addEventListener('click', () => togglePanel('activity-panel', 'logs-button'));
  $('reports-button').addEventListener('click', () => togglePanel('reports-panel', 'reports-button'));
  $('refresh-logs').addEventListener('click', loadLogs); $('refresh-reports').addEventListener('click', loadReports);
  $('generate-report').addEventListener('click', async () => {
    $('generate-report').disabled = true;
    try {
      const result = await api('/api/digest', {});
      await loadReports(); notice(result.count ? `简报已生成，收录 ${result.count} 篇新论文。` : '没有尚未汇总的新论文。');
    } catch (error) { notice(error.message, true); }
    finally { $('generate-report').disabled = false; }
  });
  $('settings-button').addEventListener('click', () => { $('vault-path').value = model.settings.vault_path || ''; formError('settings-error', null); openDialog('settings-dialog'); });
  for (const button of document.querySelectorAll('[data-close]')) button.addEventListener('click', () => { if (button.dataset.close === 'preview-dialog' && model.importing) return; $(button.dataset.close).close(); });
  $('preview-dialog').addEventListener('cancel', (event) => { if (model.importing) event.preventDefault(); });
  document.addEventListener('keydown', (event) => {
    if (document.querySelector('dialog[open]')) return;
    if (event.key === 'Escape') closeDetail();
    if (event.key === 'Tab' && model.detailId && window.matchMedia('(max-width: 1040px)').matches) {
      const focusable = Array.from($('detail-content').querySelectorAll('button:not(:disabled),a[href]'));
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (!first) return;
      if (event.shiftKey && (document.activeElement === first || !$('paper-detail').contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !$('paper-detail').contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    }
  });

  $('fetch-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const topics = Array.from($('fetch-topics').querySelectorAll('input:checked'), (input) => input.value);
    if (!topics.length) { formError('fetch-error', new Error('请至少选择一个研究方向。')); return; }
    const startDate = $('fetch-start-date').value; const endDate = $('fetch-end-date').value;
    if (Boolean(startDate) !== Boolean(endDate)) { formError('fetch-error', new Error('历史补抓需要同时填写开始日期和结束日期，或将两项都留空。')); return; }
    if (startDate && startDate > endDate) { formError('fetch-error', new Error('开始日期不能晚于结束日期。')); return; }
    const payload = { topics, budget: Number($('fetch-budget').value), enrich: $('fetch-enrich').checked };
    if (startDate && endDate) { payload.start_date = startDate; payload.end_date = endDate; }
    else payload.days = Number($('fetch-days').value);
    $('fetch-submit').disabled = true; formError('fetch-error', null);
    try {
      const task = await api('/api/fetch', payload);
      model.task = task; renderTask(task); $('fetch-dialog').close();
      $('activity-panel').hidden = false; $('logs-button').setAttribute('aria-expanded', 'true');
      notice('抓取已开始，已有候选仍可浏览。'); await loadState(); await loadLogs();
    } catch (error) { formError('fetch-error', error); $('fetch-submit').disabled = false; }
  });
  for (const id of ['fetch-start-date', 'fetch-end-date']) $(id).addEventListener('change', () => {
    $('fetch-days').disabled = Boolean($('fetch-start-date').value || $('fetch-end-date').value);
    formError('fetch-error', null);
  });
  $('settings-form').addEventListener('submit', async (event) => {
    event.preventDefault(); $('settings-submit').disabled = true; formError('settings-error', null);
    try {
      model.settings = await api('/api/settings', { vault_path: $('vault-path').value.trim() });
      model.previewReady = false; $('settings-dialog').close(); notice('文献库路径已保存。'); await loadState(); await loadPapers();
    } catch (error) { formError('settings-error', error); }
    finally { $('settings-submit').disabled = false; }
  });
  $('keyword-search').addEventListener('input', () => {
    const query = $('keyword-search').value.trim().toLocaleLowerCase();
    for (const option of $('classification-keywords').querySelectorAll('.keyword-option')) option.hidden = !option.dataset.keyword.includes(query);
  });
  $('clear-keywords').addEventListener('click', () => {
    for (const checkbox of $('classification-keywords').querySelectorAll('input')) checkbox.checked = false;
    updateKeywordCount(); formError('classification-error', null);
  });
  $('classification-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const topics = Array.from($('classification-topics').querySelectorAll('input:checked'), (input) => input.value);
    const keywords = Array.from($('classification-keywords').querySelectorAll('input:checked'), (input) => input.value);
    if (!topics.length || topics.length > 5) { formError('classification-error', new Error('请选择一至五个研究方向。')); return; }
    if (keywords.length > 4) { formError('classification-error', new Error('最多选择四个关键词。')); return; }
    const id = model.editingPaperId;
    $('classification-submit').disabled = true; formError('classification-error', null);
    try {
      await api('/api/classify', { id, topics, keywords });
      model.previewReady = false;
      $('classification-dialog').close();
      notice('候选分类已保存，已有笔记保持原样。');
      await loadState(); await loadPapers();
      if (model.detailId === id) await loadDetail(id, false);
    } catch (error) { formError('classification-error', error); }
    finally { $('classification-submit').disabled = false; }
  });
  $('cancel-button').addEventListener('click', async () => {
    $('cancel-button').disabled = true;
    try { await api('/api/cancel', {}); notice('已请求取消，等待当前请求结束。'); await loadState(); }
    catch (error) { notice(error.message, true); }
    finally { $('cancel-button').disabled = false; }
  });
  $('preview-button').addEventListener('click', () => {
    if (model.selected.size > 100) { notice('每批最多入库 100 篇，请减少选择后再预览。', true); return; }
    model.previewIds = [...model.selected]; $('queue-input').checked = false;
    $('import-results').hidden = true; $('preview-items').hidden = false; $('preview-warnings').hidden = false;
    openDialog('preview-dialog'); loadPreview();
  });
  $('queue-input').addEventListener('change', loadPreview);
  $('import-button').addEventListener('click', doImport);

  async function poll() {
    try { await loadState(); if (!$('activity-panel').hidden) await loadLogs(); }
    catch (error) { connectionError = true; $('connection-dot').classList.remove('connected'); $('connection-label').textContent = '连接中断'; model.token = ''; updateSelection(); }
    finally { pollTimer = setTimeout(poll, model.task?.running ? 2500 : 8000); }
  }

  async function start() {
    $('today-label').textContent = date(new Date());
    try { await loadState(); await loadPapers(); await loadReports(); }
    catch (error) { connectionError = true; notice(error.message, true); $('connection-label').textContent = '连接中断'; $('result-count').textContent = '尚未连接'; $('paper-list').setAttribute('aria-busy', 'false'); $('list-empty').hidden = false; }
    pollTimer = setTimeout(poll, model.task?.running ? 2500 : 8000);
  }
  window.addEventListener('pagehide', () => { clearTimeout(pollTimer); clearTimeout(searchTimer); });
  start();
})();
