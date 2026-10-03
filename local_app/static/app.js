(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const node = (tag, text = '', className = '') => {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const storage = {
    get(store, key) { try { return window[store].getItem(key); } catch (_) { return null; } },
    set(store, key, value) { try { window[store].setItem(key, value); } catch (_) { /* Storage can be disabled. */ } }
  };
  let token = location.hash.slice(1);
  if (token) {
    storage.set('sessionStorage', 'personal-kb-ui', token);
    history.replaceState(null, '', location.pathname);
  } else token = storage.get('sessionStorage', 'personal-kb-ui') || '';
  let stopped = false;
  let refreshing = false;
  let config = null;
  let selectedProvider = '';
  let selectedJob = '';
  let streamController = null;
  let detailSignature = '';
  let finalText = '';
  let routingDirty = false;
  let profileDirty = false;
  let configRefreshAt = 0;
  const testingJobs = new Set();
  const terminal = new Set(['succeeded', 'completed', 'failed', 'interrupted', 'cancelled', 'stale']);
  const jobNames = { prepare_semantic:'准备语义检索', prepare_video:'准备视频组件', index_vault:'建立或同步索引', index:'建立检索索引', query:'知识库问答', qa:'知识库问答', correlation:'关联分析', video_prepare:'视频转写', ingest:'整理笔记', generate_note:'整理笔记', model_test:'测试模型连接' };
  const statusNames = { queued:'排队中', pending:'排队中', running:'进行中', completed:'已完成', succeeded:'已完成', failed:'失败，可重试', interrupted:'已中断，可恢复', cancelled:'已停止', stale:'来源已变化' };
  const providerSymbols = { qwen:'Q', kimi:'K', glm:'G', deepseek:'D', ollama:'◉', custom:'⌘' };
  const providerShortNames = { qwen:'通义千问', kimi:'Kimi', glm:'智谱 GLM', deepseek:'DeepSeek', ollama:'本地 Ollama', custom:'自定义服务' };

  function message(text, error = false) {
    const target = byId(error ? 'error' : 'notice');
    target.textContent = text;
    target.hidden = !text;
    byId(error ? 'notice' : 'error').hidden = true;
    if (error && text) target.focus({preventScroll:true});
  }
  function errorText(error) {
    return error && error.message === 'Failed to fetch' ? '无法连接本机服务。请重新打开安装入口。' : (error && error.message) || '操作未完成，请重试。';
  }
  async function request(path, data, options = {}) {
    const response = await fetch(path, {
      method:data === undefined ? 'GET' : 'POST',
      headers:{'Authorization':'Bearer ' + token, 'Content-Type':'application/json'},
      body:data === undefined ? undefined : JSON.stringify(data),
      cache:'no-store', ...options
    });
    let value;
    try { value = await response.json(); } catch (_) { throw new Error('本机服务返回了无法读取的结果，请刷新后重试。'); }
    if (!response.ok) {
      const reason = typeof value.error === 'string' ? value.error : value.error && value.error.message;
      throw new Error(response.status === 401 ? '请通过安装入口重新打开此页面。' : reason || value.message || '操作未完成，请重试。');
    }
    return value;
  }
  async function withButton(button, callback) {
    if (button && button.disabled) return;
    if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
    try { return await callback(); }
    catch (error) { message(errorText(error), true); }
    finally { if (button) { button.disabled = false; button.removeAttribute('aria-busy'); } }
  }
  function showPage(page) {
    document.querySelectorAll('.page').forEach(element => { element.hidden = element.id !== 'page-' + page; });
    document.querySelectorAll('[data-page]').forEach(button => {
      const active = button.dataset.page === page;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
    });
    if (page === 'settings' && !config) loadModels().catch(error => message(errorText(error), true));
    window.scrollTo({top:0, behavior:'instant'});
  }
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    storage.set('localStorage', 'personal-kb-theme', theme);
    const button = byId('theme-toggle');
    button.replaceChildren(document.createTextNode(theme === 'dark' ? '☀ ' : '☾ '), node('span', theme === 'dark' ? '浅色' : '深色'));
    button.setAttribute('aria-label', theme === 'dark' ? '切换为浅色主题' : '切换为深色主题');
  }
  function badge(text, kind = '') { return node('span', text, 'badge' + (kind ? ' ' + kind : '')); }
  function providerById(id) { return config && (config.providers || []).find(provider => provider.id === id); }
  function profileById(id) { return config && (config.profiles || []).find(profile => profile.id === id); }

  function displayJobs(jobs) {
    const holder = byId('jobs');
    holder.replaceChildren();
    if (!jobs.length) { holder.append(node('p', '还没有任务。可以先整理一段灵感。', 'empty-state')); return; }
    jobs.slice(0, 16).forEach(job => {
      const item = node('div', '', 'job');
      const title = node('div', '', 'job-title');
      const titleContent = node('div');
      titleContent.append(node('span', jobNames[job.kind] || '知识库任务'), badge(statusNames[job.status] || job.status, job.status === 'succeeded' ? 'success' : job.status === 'failed' ? 'error' : ''));
      const actions = node('div', '', 'job-actions');
      const view = node('button', '查看结果'); view.type = 'button';
      view.addEventListener('click', () => withButton(view, () => selectJob(job.job_id)));
      actions.append(view);
      if (['failed', 'interrupted', 'cancelled'].includes(job.status)) {
        const retry = node('button', '继续 / 重试'); retry.type = 'button';
        retry.addEventListener('click', () => withButton(retry, () => retryJob(job.job_id)));
        actions.append(retry);
      }
      title.append(titleContent, actions); item.append(title);
      const progress = job.progress || {};
      if (progress.message || progress.file) item.append(node('p', progress.message || '正在处理：' + progress.file));
      if (progress.total > 0 && Number.isFinite(progress.downloaded)) {
        const meter = document.createElement('progress'); meter.max = progress.total; meter.value = progress.downloaded; meter.setAttribute('aria-label', '下载进度');
        item.append(meter, node('p', Math.floor(progress.downloaded / progress.total * 100) + '%'));
      }
      if (job.error) item.append(node('p', typeof job.error === 'string' ? job.error : job.error.message || '任务未完成。'));
      item.append(node('p', job.job_id, 'job-code'));
      holder.append(item);
      if (testingJobs.has(job.job_id) && terminal.has(job.status)) {
        testingJobs.delete(job.job_id);
        loadModels(false).catch(() => {});
      }
    });
  }
  async function refresh() {
    if (stopped || refreshing || !token) return;
    refreshing = true;
    try {
      const state = await request('/api/status');
      byId('app-version').textContent = state.version ? ' · v' + state.version : '';
      byId('service-dot').classList.add('connected');
      byId('service-dot').replaceChildren(node('i'), document.createTextNode('本机服务已连接'));
      byId('basic-state').textContent = state.basic_ready ? '已就绪' : '准备中';
      byId('basic-state').className = state.basic_ready ? 'ready' : '';
      const registered = !!(state.registration && state.registration.saved);
      const connected = !!(state.mcp && state.mcp.last_activity);
      byId('registration-state').textContent = registered ? '已保存' : '尚未保存';
      byId('handshake-state').textContent = connected ? '已收到 ' + (state.mcp.client || '客户端') + ' 握手' : '等待连接';
      byId('connection-state').textContent = connected ? '已收到客户端握手' : registered ? '等待原生信任' : '基础功能可用';
      byId('connection-state').className = 'badge' + (connected ? ' success' : '');
      byId('trust-hint').hidden = !registered || connected;
      byId('register').textContent = registered ? '修复连接配置' : '接入 WorkBuddy';
      const semantic = state.features && state.features.semantic || {};
      const video = state.features && state.features.video || {};
      byId('semantic-state').textContent = semantic.ready ? '已就绪' : semantic.phase === 'failed' ? '准备失败，可重试' : semantic.phase === 'preparing' ? '后台准备中' : '尚未准备';
      byId('video-state').textContent = video.ready ? (video.key_saved ? '组件就绪 · Key 已保存' : '组件就绪 · 需要音频 Key') : video.phase === 'failed' ? '准备失败，可重试' : video.phase === 'preparing' ? '后台准备中' : '未启用';
      byId('prepare-semantic').disabled = !!semantic.ready || semantic.phase === 'preparing';
      byId('prepare-video').disabled = !!video.ready || video.phase === 'preparing';
      byId('key-state').textContent = video.key_saved ? 'Key 已保存，实际转写时验证' : '尚未设置';
      byId('config-location').textContent = '连接配置位置：' + (state.workbuddy_config || '未获取');
      displayJobs(state.jobs || []);
      if (selectedJob) await refreshDetail();
      if (config && Date.now() - configRefreshAt > 15000) await loadModels(false);
    } catch (error) {
      byId('service-dot').classList.remove('connected');
      byId('service-dot').replaceChildren(node('i'), document.createTextNode('本机服务未连接'));
      message(errorText(error), true);
    } finally { refreshing = false; }
  }
  async function action(path, data, button) {
    return withButton(button, async () => {
      const result = await request(path, data);
      message(result.trust || (result.job_id ? '任务已加入后台队列，可以继续使用其他功能。' : '已完成。'));
      await refresh(); return result;
    });
  }

  function fillProfileSelect(select, value, isDefault = false) {
    select.replaceChildren();
    const empty = node('option', isDefault ? '未指定默认连接' : '跟随默认连接'); empty.value = ''; select.append(empty);
    (config.profiles || []).forEach(profile => {
      const option = node('option', profile.name + ' · ' + profile.model_id); option.value = profile.id; select.append(option);
    });
    select.value = value || '';
  }
  function renderModeSummary() {
    if (!config) return;
    const current = profileById(config.default_profile);
    byId('generation-summary').textContent = config.generation_mode === 'independent'
      ? '独立模型 · ' + (current ? current.name + ' / ' + current.model_id : '按任务指定')
      : '宿主模型 · 由 WorkBuddy 等客户端完成生成';
    byId('task-mode-hint').textContent = config.generation_mode === 'independent'
      ? '当前使用独立模型。任务内容将发送至所选服务，调用可能产生费用。'
      : '当前使用宿主模式。本页准备资料后，可将生成提示交给 WorkBuddy；选择独立模型可在本页完成生成。';
  }
  function renderRouting() {
    if (!config || routingDirty) return;
    document.querySelectorAll('[name="generation-mode"]').forEach(input => { input.checked = input.value === config.generation_mode; });
    fillProfileSelect(byId('default-profile'), config.default_profile, true);
    ['ingest', 'qa', 'correlation'].forEach(kind => fillProfileSelect(byId('profile-' + kind), (config.task_profiles || {})[kind]));
    byId('model-config-state').textContent = config.generation_mode === 'independent' ? '独立模型已启用' : '宿主模式已启用';
    byId('routing-state').textContent = '当前配置已保存';
    updateRoutingVisibility();
  }
  function updateRoutingVisibility() {
    const independent = document.querySelector('[name="generation-mode"]:checked');
    byId('routing-fields').hidden = false;
    byId('routing-fields-hint').textContent = independent && independent.value === 'independent' ? '以下连接用于新任务；任务指定优先于默认连接。' : '这些连接选择将在切回独立模式后生效。删除被引用的连接前，可在此清空引用并保存。';
  }
  function renderProfiles() {
    const holder = byId('profiles'); holder.replaceChildren();
    if (!(config.profiles || []).length) {
      holder.append(node('p', '还没有模型连接。选择下方的服务商，添加第一个连接。', 'empty-state')); return;
    }
    config.profiles.forEach(profile => {
      const item = node('div', '', 'profile');
      const head = node('div', '', 'profile-heading');
      const info = node('div', '', 'profile-info');
      info.append(node('strong', profile.name));
      info.append(node('p', ((providerById(profile.provider) || {}).name || profile.provider) + ' · ' + profile.model_id, 'profile-subtitle'));
      const tags = node('div', '', 'profile-tags');
      tags.append(badge('已保存'));
      const tested = profile.tested_revision != null && profile.tested_revision === profile.revision && (profile.test_status === 'passed' || profile.test_status === 'succeeded' || profile.test_status === 'success');
      tags.append(badge(tested ? '测试通过' : profile.test_status === 'failed' ? '测试失败' : profile.tested_revision != null ? '配置已变更，需重测' : '尚未测试', tested ? 'success' : profile.test_status === 'failed' ? 'error' : ''));
      const activeRoles = [];
      if (config.generation_mode === 'independent') {
        if (config.default_profile === profile.id) activeRoles.push('默认');
        [['ingest','整理'],['qa','问答'],['correlation','关联']].forEach(([key,label]) => { if ((config.task_profiles || {})[key] === profile.id) activeRoles.push(label); });
      }
      tags.append(badge(activeRoles.length ? '已启用 · ' + activeRoles.join(' / ') : '未启用', activeRoles.length ? 'success' : ''));
      tags.append(badge(profile.credential_error ? '凭据库暂不可用' : profile.credential_present ? 'Key 已保存' : ['ollama','custom'].includes(profile.provider) && /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::|\/|$)/.test(profile.base_url) ? '本机免 Key' : '未配置 Key'));
      info.append(tags);
      const buttons = node('div', '', 'profile-buttons');
      const edit = node('button', '编辑'); edit.type='button'; edit.addEventListener('click', () => editProfile(profile.id));
      const test = node('button', '测试'); test.type='button'; test.title='发送简短请求，可能产生 API 费用'; test.addEventListener('click', () => withButton(test, () => testProfile(profile.id)));
      const activate = node('button', '设为默认并启用'); activate.type='button'; activate.addEventListener('click', () => withButton(activate, async () => {
        applyConfig(await request('/api/models/save', {generation_mode:'independent',default_profile:profile.id}), true);
        message('已启用 ' + profile.name + '。新任务使用该默认连接；已有的任务覆盖配置继续生效。');
      }));
      const remove = node('button', '删除', 'danger'); remove.type='button'; remove.addEventListener('click', () => withButton(remove, async () => {
        if (!confirm('删除连接“' + profile.name + '”？该连接保存的 Key 也会移除。已被默认或任务配置引用时，请先解除引用。')) return;
        applyConfig(await request('/api/models/delete', {profile_id:profile.id}), true);
        if (byId('profile-id').value === profile.id) newProfile();
        message('连接已删除。');
      }));
      buttons.append(edit, test, activate, remove); head.append(info, buttons); item.append(head); holder.append(item);
    });
  }
  function renderProviders() {
    const holder = byId('provider-grid'); holder.replaceChildren();
    (config.providers || []).forEach(provider => {
      const button = node('button', '', 'provider-card' + (selectedProvider === provider.id ? ' active' : ''));
      button.type='button'; button.setAttribute('aria-pressed', selectedProvider === provider.id ? 'true' : 'false');
      button.append(node('span', providerSymbols[provider.id] || '◇', 'provider-symbol'), node('span', providerShortNames[provider.id] || provider.name));
      button.addEventListener('click', () => {
        if (byId('profile-id').value) newProfile(provider.id);
        else { selectProvider(provider.id, true); markProfileDirty(); }
      });
      holder.append(button);
    });
  }
  function applyConfig(value, forceRouting = false) {
    config = value.config || value;
    configRefreshAt = Date.now();
    if (forceRouting) routingDirty = false;
    renderModeSummary(); renderRouting(); renderProfiles(); renderProviders();
    if (!selectedProvider && (config.providers || []).length) selectProvider(config.providers[0].id, true);
    updateProfileButtons();
  }
  async function loadModels(forceRouting = true) {
    const value = await request('/api/models');
    applyConfig(value, forceRouting);
  }
  function updateThinking() {
    const provider = providerById(selectedProvider) || {};
    const modelId = byId('model-id').value.trim();
    const dynamic = provider.thinking_dynamic === true;
    const supported = Boolean(modelId) && (dynamic || (provider.thinking_models || []).includes(modelId));
    Array.from(byId('model-thinking').options).forEach(option => { option.disabled = option.value !== 'default' && !supported; });
    if (!supported) byId('model-thinking').value = 'default';
    byId('thinking-hint').textContent = dynamic ? '可选择思考模式；执行前会向本机 Ollama 查询模型能力，不支持时会明确提示。' : supported ? '此模型已支持显式思考开关；费用与响应速度由厂商和模型决定。' : '当前模型的思考开关尚未核验，使用服务商默认设置。';
  }
  function selectProvider(id, defaults) {
    const provider = providerById(id);
    if (!provider) return;
    selectedProvider = id;
    if (defaults) {
      byId('profile-name').value = '我的 ' + (providerShortNames[id] || provider.name);
      byId('model-url').value = provider.default_base_url || '';
      byId('model-id').value = provider.default_model || '';
      byId('model-thinking').value = 'default';
    }
    byId('provider-hint').textContent = provider.hint || '请使用该服务商的模型 API 地址和对应凭据。';
    const regions = provider.regions || [];
    byId('provider-region-field').hidden = !regions.length;
    byId('provider-region').replaceChildren();
    regions.forEach(region => { const option=node('option',region.name); option.value=region.base_url; byId('provider-region').append(option); });
    if (regions.length) {
      const custom=node('option','自定义地址');custom.value='';byId('provider-region').append(custom);
      byId('provider-region').value = regions.some(region => region.base_url === byId('model-url').value) ? byId('model-url').value : '';
    }
    renderProviders(); updateThinking();
  }
  function markProfileDirty() {
    profileDirty = true;
    byId('profile-save-state').textContent = '有未保存的修改';
    updateProfileButtons();
  }
  function updateProfileButtons() {
    const saved = !!byId('profile-id').value;
    byId('test-profile').disabled = !saved || profileDirty || !byId('model-id').value.trim();
    byId('list-models').disabled = !saved || profileDirty;
    byId('test-profile').title = profileDirty ? '请先保存修改' : '发送简短请求，可能产生 API 费用';
  }
  function newProfile(providerId) {
    byId('profile-form').reset(); byId('profile-id').value = '';
    byId('model-options').replaceChildren(); byId('clear-key-label').hidden = true;
    byId('model-key-label').textContent = '';
    byId('model-key').placeholder = '输入此服务商的 API Key；本机模型可留空';
    byId('editor-title').textContent = '添加模型连接'; byId('cancel-edit').hidden = true;
    byId('profile-save-state').textContent = '';
    profileDirty = false;
    selectProvider(providerId || selectedProvider || (config.providers[0] || {}).id, true);
    updateProfileButtons();
  }
  function editProfile(id) {
    const profile = profileById(id); if (!profile) return;
    byId('profile-id').value = profile.id;
    byId('profile-name').value = profile.name;
    byId('model-id').value = profile.model_id;
    byId('model-url').value = profile.base_url;
    byId('model-timeout').value = profile.timeout_seconds;
    byId('model-max-tokens').value = profile.max_output_tokens;
    byId('model-key').value = ''; byId('clear-model-key').checked = false;
    byId('clear-key-label').hidden = !profile.credential_present;
    byId('model-key-label').textContent = profile.credential_present ? '（已保存，留空保留）' : '（尚未保存）';
    byId('model-key').placeholder = profile.credential_present ? '留空保留现有 Key；输入新 Key 会替换' : '输入此服务商的 API Key；本机模型可留空';
    byId('editor-title').textContent = '编辑模型连接'; byId('cancel-edit').hidden = false;
    byId('profile-save-state').textContent = '已保存';
    profileDirty = false;
    selectProvider(profile.provider, false);
    byId('model-thinking').value = profile.thinking || 'default'; updateThinking(); updateProfileButtons();
    byId('profile-editor').scrollIntoView({block:'start',behavior:'smooth'});
  }
  async function testProfile(profileId) {
    const profile = profileById(profileId);
    if (!profile) throw new Error('请先保存模型连接。');
    const result = await request('/api/models/test', {profile_id:profileId});
    if (result.job_id) {
      testingJobs.add(result.job_id);
      message('正在测试“' + profile.name + '”，测试会产生少量 API 用量。结果可在后台任务中查看。');
      await selectJob(result.job_id);
    } else message('连接测试已提交。');
    await refresh();
  }

  function clearResult() {
    finalText = '';
    byId('detail-text').textContent = ''; byId('detail-text').hidden = true;
    byId('detail-meta').replaceChildren();
    byId('detail-references').replaceChildren(); byId('detail-references').hidden = true;
    byId('detail-metrics').replaceChildren(); byId('detail-metrics').hidden = true;
    byId('copy-result').hidden = true; byId('detail-stream-hint').hidden = true;
  }
  function renderJobHeader(job) {
    byId('detail-empty').hidden = true; byId('detail-content').hidden = false;
    byId('detail-state').hidden = false;
    byId('detail-state').textContent = statusNames[job.status] || (job.status === 'prepared' ? '资料已准备' : job.status);
    byId('detail-state').className = 'badge' + (job.status === 'succeeded' ? ' success' : job.status === 'failed' ? ' error' : '');
    byId('detail-id').textContent = (jobNames[job.kind] || '知识库任务') + (job.job_id ? ' · ' + job.job_id : '');
    const progress = job.progress || {};
    byId('detail-progress').textContent = progress.message || (job.status === 'queued' ? '任务正在等待处理。' : job.status === 'running' ? '任务正在进行，可以继续使用页面。' : '');
    byId('retry-detail').hidden = !['failed','interrupted','cancelled'].includes(job.status);
    byId('refresh-detail').hidden = !job.job_id;
    const error = job.error;
    byId('detail-error').hidden = !error;
    byId('detail-error').textContent = error ? typeof error === 'string' ? error : error.message || '任务未完成。' : '';
  }
  function invalidResult(job, result) {
    return job.status === 'stale' || result.stale === true || result.valid === false || ['stale','stale_result','invalidated','sources_changed','scope_changed','source_changed','not_authorized'].includes(result.status);
  }
  function renderMetrics(result) {
    const metrics = result.metrics || {};
    const usage = result.usage || {};
    const entries = [];
    const metricLabels = {
      first_event_ms:'首个事件', first_text_ms:'首个正文', first_token_ms:'首个正文', first_content_ms:'首个正文', first_delta_ms:'首个正文', total_ms:'总耗时',
      first_event_seconds:'首个事件', first_token_seconds:'首个正文', first_content_seconds:'首个正文', total_seconds:'总耗时',
      tokens_per_second:'输出速度', output_tokens_per_second:'输出速度', elapsed_seconds:'总耗时'
    };
    const used = new Set();
    Object.entries(metricLabels).forEach(([key,label]) => {
      const value = metrics[key];
      if (typeof value !== 'number' || used.has(label)) return;
      used.add(label);
      const unit = key.endsWith('_ms') ? ' ms' : key.endsWith('_seconds') ? ' s' : ' token/s';
      entries.push([label, Number(value.toFixed(2)) + unit]);
    });
    [['input_tokens','输入 Token'],['prompt_tokens','输入 Token'],['output_tokens','输出 Token'],['completion_tokens','输出 Token'],['total_tokens','总 Token']].forEach(([key,label]) => {
      if (typeof usage[key] === 'number' && !used.has(label)) { used.add(label); entries.push([label, String(usage[key])]); }
    });
    if (!entries.length) return;
    const holder = byId('detail-metrics');holder.replaceChildren(node('h3','本次调用'));
    const list = node('dl'); entries.forEach(([label,value]) => list.append(node('dt',label),node('dd',value)));
    holder.append(list);holder.hidden=false;
  }
  function renderResult(job) {
    const signature = JSON.stringify(job);
    if (detailSignature === signature) return;
    detailSignature = signature;
    renderJobHeader(job);
    const result = job.result && typeof job.result === 'object' ? job.result : {};
    if (invalidResult(job,result)) {
      clearResult();
      if (streamController) { streamController.abort();streamController=null; }
      byId('detail-error').hidden = false;
      byId('detail-error').textContent = '来源或索引授权范围已变化，之前的正文已清除。请重新执行任务获取有效结果。';
      byId('detail-state').textContent = '结果已失效';
      return;
    }
    if (!terminal.has(job.status) && job.status !== 'prepared') return;
    clearResult();
    if (!['succeeded','completed','prepared'].includes(job.status)) return;
    const metadata = byId('detail-meta');
    if (result.model && typeof result.model === 'object') {
      const model = result.model;
      metadata.append(badge(((providerById(model.provider) || {}).name || model.provider || '模型') + ' · ' + (model.model_id || model.model || '')));
      if (model.config_revision != null) metadata.append(badge('配置版本 ' + model.config_revision));
    } else if (typeof result.model === 'string') metadata.append(badge(result.model));
    if (result.generation_mode === 'independent') metadata.append(badge('独立模型'));
    if (result.status === 'staged') {
      metadata.append(badge('待审核草稿','success'));
      byId('detail-progress').textContent = '笔记已保存为待审核草稿。请在 Obsidian 中审核后再收录。';
    }
    if (result.note_path || result.absolute_path || result.path) metadata.append(badge('保存位置：' + (result.absolute_path || result.note_path || result.path)));
    let text = [result.answer,result.note_content,result.text,result.content].find(value => typeof value === 'string' && value.trim()) || '';
    if (result.prompt_for_host) {
      text = String(result.prompt_for_host);
      metadata.append(badge('由宿主继续生成'));
      byId('detail-progress').textContent = '资料已准备，尚未生成最终正文。请在 WorkBuddy 中继续对应任务；以下是供宿主使用的生成提示。';
    }
    if (!text && typeof result.no_hit_message === 'string' && result.no_hit_message) text = result.no_hit_message;
    if (['not_indexed','not_ready','no_hits'].includes(result.status)) {
      byId('detail-state').textContent = {not_indexed:'尚未建立索引',not_ready:'组件尚未就绪',no_hits:'暂无可引用资料'}[result.status];
      byId('detail-state').className = 'badge';
    }
    if (!text && result.status === 'no_hits') text = '没有找到可用的笔记片段。请确认已建立索引、笔记已审核，且问题处于授权检索范围内。';
    if (!text && result.message) text = typeof result.message === 'string' ? result.message : '';
    if (!text && ['model_test','test_model','test_connection'].includes(job.kind)) text = result.ok === false ? '连接测试未通过，请检查错误说明。' : '连接测试已完成，已收到模型服务响应。';
    if (!text && ['index_vault','index'].includes(job.kind)) {
      text = '索引任务已完成。原笔记保持不变。';
      if (typeof result.notes === 'number') text += '\n收录笔记：' + result.notes;
      if (typeof result.chunks === 'number') text += '\n索引片段：' + result.chunks;
    }
    if (!text && job.status === 'succeeded') text = '任务处理完成。';
    if (text) {
      finalText = text; byId('detail-text').textContent = text; byId('detail-text').hidden = false;
      byId('copy-result').hidden = false;
    }
    const references = result.citations || result.references || result.retrieved_chunks || result.candidates || [];
    if (Array.isArray(references) && references.length) {
      const holder = byId('detail-references');holder.replaceChildren(node('h3','参考笔记'));
      const list = node('ul');const seen = new Set();
      references.forEach(reference => {
        if (!reference) return;
        const path = typeof reference === 'string' ? reference : reference.path || reference.source_path || reference.note_path || reference.title;
        if (!path || seen.has(path)) return;
        seen.add(path);list.append(node('li', (reference.number != null ? '[' + reference.number + '] ' : '') + path));
      });
      if (seen.size) { holder.append(list);holder.hidden=false; }
    }
    renderMetrics(result);
  }
  async function refreshDetail() {
    const jobId = selectedJob;
    if (!jobId) return;
    try {
      const value = await request('/api/jobs/' + encodeURIComponent(jobId));
      if (selectedJob !== jobId) return;
      const job = value.job || value;
      renderResult(job);
      if (terminal.has(job.status) && streamController) { streamController.abort();streamController=null; }
    } catch (error) {
      if (selectedJob !== jobId) return;
      clearResult();detailSignature='';
      byId('detail-error').hidden=false;byId('detail-error').textContent=errorText(error);
    }
  }
  async function selectJob(jobId) {
    if (!jobId) return;
    if (streamController) streamController.abort();
    streamController=null;selectedJob=jobId;detailSignature='';
    clearResult();showPage('tasks');
    byId('detail-empty').hidden=true;byId('detail-content').hidden=false;
    byId('detail-progress').textContent='正在读取任务…';
    byId('detail-error').hidden=true;byId('detail-state').hidden=true;
    byId('detail-id').textContent=jobId;
    const value = await request('/api/jobs/' + encodeURIComponent(jobId));
    if (selectedJob !== jobId) return;
    const job=value.job || value;renderResult(job);
    if (!terminal.has(job.status)) streamJob(jobId);
  }
  async function streamJob(jobId) {
    const controller = new AbortController();streamController=controller;
    try {
      const response = await fetch('/api/jobs/' + encodeURIComponent(jobId) + '/events', {
        headers:{'Authorization':'Bearer ' + token,'Accept':'text/event-stream'},cache:'no-store',signal:controller.signal
      });
      if (!response.ok || !response.body) throw new Error('增量显示暂不可用，将继续检查任务结果。');
      const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
      while (true) {
        const {value,done}=await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value,{stream:true});
        buffer = buffer.replace(/\r\n/g,'\n');
        const blocks=buffer.split('\n\n');buffer=blocks.pop();
        for (const block of blocks) {
          const raw=block.split('\n').filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
          if (!raw) continue;
          let event;try {event=JSON.parse(raw);} catch (_) {continue;}
          if (selectedJob !== jobId || controller.signal.aborted) return;
          if (event.type === 'status' && event.job) renderJobHeader(event.job);
          else if (event.type === 'delta' && typeof event.text === 'string') {
            detailSignature='';byId('detail-text').hidden=false;byId('detail-stream-hint').hidden=false;
            byId('detail-text').textContent += event.text;
          } else if (event.type === 'result' && event.job) {
            detailSignature='';renderResult(event.job);
            if (testingJobs.has(jobId)) { testingJobs.delete(jobId);loadModels(false).catch(()=>{}); }
          } else if (event.type === 'error') {
            clearResult();detailSignature='';byId('detail-error').hidden=false;
            byId('detail-error').textContent=event.message || '任务未完成，请重新获取结果。';
          }
        }
        if (done) break;
        if (buffer.length > 1024 * 1024) throw new Error('增量消息过大，正在改用任务结果查询。');
      }
    } catch (error) {
      if (error.name !== 'AbortError' && selectedJob === jobId) {
        byId('detail-progress').textContent='增量连接已断开，正在定期获取已校验的任务结果。';
      }
    } finally {
      if (streamController === controller) streamController=null;
      if (selectedJob === jobId && !controller.signal.aborted) await refreshDetail();
    }
  }
  async function retryJob(jobId) {
    const result=await request('/api/retry',{job_id:jobId});
    message('任务已重新加入队列。');
    await selectJob(result.job_id || (result.job && result.job.job_id) || jobId);
    await refresh();
  }
  function lines(value) {return value.split(/\r?\n/).map(line=>line.trim()).filter(Boolean);}
  function updateTaskForm() {
    const kind=byId('task-kind').value;
    byId('task-folder-field').hidden=kind!=='ingest';
    byId('task-input-field').hidden=!['ingest','query'].includes(kind);
    byId('task-input').required=['ingest','query'].includes(kind);
    byId('task-input-label').textContent=kind==='query'?'想向知识库提出的问题':'想整理的原文或想法';
    byId('task-input').placeholder=kind==='query'?'例如：我的笔记中，RAG 检索质量有哪些优化方法？':'粘贴一段文字，让零散的记录成为有结构的笔记。';
    byId('task-note-field').hidden=kind!=='correlation';byId('task-note').required=kind==='correlation';
    byId('task-query-folder-field').hidden=kind!=='query';
    byId('task-index-fields').hidden=kind!=='index';byId('index-authorize').required=kind==='index';
    byId('submit-task').textContent={ingest:'开始整理',query:'开始提问',correlation:'发现关联',index:'建立 / 更新索引'}[kind];
    byId('task-submit-hint').textContent={ingest:'新笔记保存为待审核草稿，由你决定是否正式收录。',query:'问答只使用已授权且仍有效的索引资料。',correlation:'只分析已审核笔记的关联，不自动修改双链。',index:'只有你明确勾选授权后，才会建立本次范围的索引。'}[kind];
  }

  document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>showPage(button.dataset.page)));
  document.querySelector('.brand').addEventListener('click',event=>{event.preventDefault();showPage('home');});
  ['open-settings','hero-settings','edit-generation'].forEach(id=>byId(id).addEventListener('click',()=>showPage('settings')));
  byId('start-task').addEventListener('click',()=>showPage('tasks'));
  byId('theme-toggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
  byId('register').addEventListener('click',()=>action('/api/register',{},byId('register')));
  byId('refresh').addEventListener('click',()=>withButton(byId('refresh'),refresh));
  byId('prepare-semantic').addEventListener('click',()=>action('/api/prepare',{feature:'semantic'},byId('prepare-semantic')));
  byId('prepare-video').addEventListener('click',()=>action('/api/prepare',{feature:'video'},byId('prepare-video')));
  byId('key-form').addEventListener('submit',async event=>{
    event.preventDefault();const value=byId('api-key').value;byId('api-key').value='';
    await action('/api/key',{key:value},event.submitter);
  });
  byId('routing-form').addEventListener('change',()=>{routingDirty=true;byId('routing-state').textContent='有未应用的修改';updateRoutingVisibility();});
  byId('routing-form').addEventListener('submit',event=>{
    event.preventDefault();withButton(byId('save-routing'),async()=>{
      const mode=document.querySelector('[name="generation-mode"]:checked');
      if (!mode) throw new Error('请先等待模型配置加载完成。');
      const defaultProfile=byId('default-profile').value || null;
      const taskProfiles={};['ingest','qa','correlation'].forEach(key=>{taskProfiles[key]=byId('profile-'+key).value || null;});
      if (mode.value==='independent' && !defaultProfile && Object.values(taskProfiles).some(value=>!value)) throw new Error('请选择默认模型连接，或为三种任务分别指定连接。');
      applyConfig(await request('/api/models/save',{generation_mode:mode.value,default_profile:defaultProfile,task_profiles:taskProfiles}),true);
      message('生成配置已保存并应用，只影响之后开始的新任务。');
    });
  });
  byId('new-profile').addEventListener('click',()=>{if(!config)return;newProfile();byId('profile-editor').scrollIntoView({block:'start',behavior:'smooth'});byId('profile-name').focus({preventScroll:true});});
  byId('cancel-edit').addEventListener('click',()=>newProfile());
  byId('profile-form').addEventListener('input',()=>{markProfileDirty();updateThinking();});
  byId('profile-form').addEventListener('change',()=>{markProfileDirty();updateThinking();});
  byId('provider-region').addEventListener('change',()=>{if(byId('provider-region').value)byId('model-url').value=byId('provider-region').value;});
  byId('model-url').addEventListener('input',()=>{const provider=providerById(selectedProvider)||{};byId('provider-region').value=(provider.regions||[]).some(region=>region.base_url===byId('model-url').value)?byId('model-url').value:'';});
  byId('profile-form').addEventListener('submit',event=>{
    event.preventDefault();withButton(byId('save-profile'),async()=>{
      if (!selectedProvider) throw new Error('请先选择模型服务商。');
      const existingId=byId('profile-id').value;
      const profile={name:byId('profile-name').value.trim(),provider:selectedProvider,base_url:byId('model-url').value.trim(),model_id:byId('model-id').value.trim(),timeout_seconds:Number(byId('model-timeout').value),max_output_tokens:Number(byId('model-max-tokens').value),thinking:byId('model-thinking').value};
      if (existingId) profile.id=existingId;
      if (byId('model-key').value) profile.api_key=byId('model-key').value;
      if (byId('clear-model-key').checked) profile.clear_key=true;
      if (profile.api_key && profile.clear_key) throw new Error('输入新 Key 与移除 Key 不能同时选择。');
      const before=new Set((config.profiles||[]).map(item=>item.id));
      const value=await request('/api/models/save',{profile});
      byId('model-key').value='';applyConfig(value);
      const saved=existingId || ((config.profiles||[]).find(item=>!before.has(item.id))||{}).id;
      if (saved) editProfile(saved);
      message('模型连接已保存。可以测试连接，再选择是否启用。');
    });
  });
  byId('test-profile').addEventListener('click',()=>withButton(byId('test-profile'),()=>testProfile(byId('profile-id').value)));
  byId('list-models').addEventListener('click',()=>withButton(byId('list-models'),async()=>{
    const result=await request('/api/models/list',{profile_id:byId('profile-id').value});
    const list=byId('model-options');list.replaceChildren();
    (result.models||[]).forEach(value=>{const option=node('option');option.value=typeof value==='string'?value:value.id;list.append(option);});
    byId('profile-save-state').textContent='获取到 '+(result.models||[]).length+' 个模型；在模型 ID 输入框中选择，或直接输入。';
    byId('model-id').focus();
  }));
  byId('task-kind').addEventListener('change',updateTaskForm);
  byId('task-form').addEventListener('submit',event=>{
    event.preventDefault();withButton(byId('submit-task'),async()=>{
      const kind=byId('task-kind').value;
      const data={kind,vault_path:byId('task-vault').value.trim()};
      if (kind==='ingest') {data.user_input=byId('task-input').value.trim();data.folder=byId('task-folder').value.trim();}
      else if (kind==='query') {data.question=byId('task-input').value.trim();data.folders=lines(byId('task-query-folders').value);}
      else if (kind==='correlation') data.note_path=byId('task-note').value.trim();
      else {
        if (!byId('index-authorize').checked) throw new Error('请明确勾选索引范围授权。');
        data.include_existing=byId('index-existing').checked;data.include_dirs=lines(byId('index-include').value);data.exclude_dirs=lines(byId('index-exclude').value);data.auto_sync=byId('index-sync').checked;
      }
      const result=await request('/api/tasks',data);
      if (result.job_id) {message('任务已开始，生成结果会在来源校验后显示。');await selectJob(result.job_id);}
      else {
        if(streamController)streamController.abort();streamController=null;selectedJob='';detailSignature='';clearResult();
        renderResult({kind,status:'prepared',result});
        message(result.prompt_for_host?'资料已准备。当前为宿主模式，请在 WorkBuddy 中继续生成。':'任务请求已处理，请查看结果。');
      }
      await refresh();
    });
  });
  byId('copy-result').addEventListener('click',()=>withButton(byId('copy-result'),async()=>{
    if(!finalText)return;
    if(!navigator.clipboard)throw new Error('浏览器未开放剪贴板，请在结果区域手动选择并复制。');
    await navigator.clipboard.writeText(finalText);message('结果已复制。');
  }));
  byId('retry-detail').addEventListener('click',()=>withButton(byId('retry-detail'),()=>retryJob(selectedJob)));
  byId('refresh-detail').addEventListener('click',()=>withButton(byId('refresh-detail'),refreshDetail));
  byId('stop').addEventListener('click',()=>withButton(byId('stop'),async()=>{
    if(!confirm('停止本机服务？未完成的任务可在下次启动后恢复。'))return;
    await request('/api/shutdown',{});stopped=true;if(streamController)streamController.abort();
    byId('service-dot').classList.remove('connected');byId('service-dot').replaceChildren(node('i'),document.createTextNode('服务已停止'));
    message('服务正在停止。需要使用时，请重新双击安装入口。');
  }));
  setTheme(storage.get('localStorage','personal-kb-theme')==='light'?'light':'dark');
  updateTaskForm();
  if(!token)message('请双击安装入口打开此页面，认证信息会在本机自动传递。',true);
  else {
    loadModels().catch(error=>message(errorText(error),true));
    refresh();setInterval(refresh,3000);
  }
})();
