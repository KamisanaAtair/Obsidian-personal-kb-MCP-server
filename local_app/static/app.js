(() => {
  'use strict';
  const viewNames = {home:'工作台',tasks:'本地任务',models:'我的模型','model-new':'添加模型连接','model-edit':'编辑模型连接','model-routing':'模型用途',help:'使用帮助'};
  const helpTopics = {
    saved: {title:'添加的连接保存到哪里了？', paragraphs:['点击“保存并返回我的模型”后，连接会出现在“我的模型”的列表中。每张卡片显示连接名称、服务商、各能力型号、凭据和测试状态，以及它实际负责的任务。','连接记录保存在本机配置中，Key 由本机凭据服务保存。连接不是新增到 WorkBuddy 的模型菜单，也不会更换 WorkBuddy 自己的对话模型。'], action:'打开我的模型', view:'models'},
    workflow: {title:'保存、测试和启用有什么区别？', paragraphs:['保存：记录你填写的连接信息，返回“我的模型”。不会自动调用服务或产生测试费用。','测试：由你点击“测试文字 / 视觉 / 语音”，向对应服务发送小型合成请求，可能产生费用。通过表示接口可用，不代表真实任务质量。获取模型列表与生成测试也是两件事。','启用：进入“配置模型用途”，选择需要使用的连接，再点击“保存并应用”。文字、视觉和语音分别选择；保存连接后不会自动启用。'], action:'打开模型用途', view:'model-routing'},
    'base-url': {title:'服务地址应该填什么？', paragraphs:['填写服务商提供的 API 基础地址（Base URL），不要填控制台、登录页、聊天网站或完整的 /chat/completions 请求地址。应用会自行补全所需请求路径。','选择服务商预设会填写建议地址。千问还需明确选择“按量 API”或“Token Plan”；若你有账户专属地址，可以选择“保留 / 手动填写地址”并手填。地址与 Key 必须属于同一平台、地域和计费入口。','修改已有连接的服务商或地址时，按页面提示重新填写目标服务的 Key。应用不会把旧 Key 自动发送到另一个地址。']},
    qwen: {title:'千问AI平台与旧百炼、Token Plan 怎么选？', paragraphs:['新建千问连接默认使用千问AI平台的按量 API：https://maas.qianwenaiapi.com/compatible-mode/v1。Token Plan 使用 https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1，需要对应订阅的专属 Key。个人版与团队版共用套餐地址。','新千问 Token Plan 与旧百炼 Coding Plan 不是同一入口。请以千问AI平台账户显示的订阅、Key 和可用型号为准，不要混用旧地址或仅凭 Key 前缀推断入口。','已有百炼连接保留原地址，避免把现有 Key 静默发往新域名。需要迁移时，在编辑页明确选择千问入口，并填写新平台对应的 Key。','本版支持的原生语音协议可使用千问按量接口与 qwen3-asr-flash 类型号。Token Plan 语音采用新协议，本版尚未适配；这不表示套餐没有语音能力。文字与视觉按账户支持的型号配置。'], links:[['千问 API Key 官方说明','https://platform.qianwenai.com/docs/api-reference/preparation/api-key'],['Token Plan 官方说明','https://platform.qianwenai.com/docs/token-plan/overview']]},
    'model-id': {title:'获取不到模型列表怎么办？', paragraphs:['模型 ID 是服务商 API 使用的精确型号，不是你给连接取的名称。可以从对应平台文档或控制台复制，再手动填写。','部分服务没有 /models 接口，返回 404、405 或 501 不一定表示生成不可用。填写官方支持的型号并保存，然后单独点击对应能力的测试。','文字、视觉和语音可以用不同型号，共享同一连接的地址与 Key；如果这些能力需要不同地址或 Key，请分开添加连接。']},
    key: {title:'为什么保存后看不到 Key？更换地址怎么办？', paragraphs:['Key 是凭据，保存后不会返回页面。编辑时留空表示保留已有 Key；输入新值会替换，勾选“移除”会删除它。列表用“Key 已保存”或“未配置 Key”显示状态。','修改服务商或域名时必须重新填写目标服务的 Key，或明确移除旧 Key，防止凭据发往错误地址。不能直接沿用旧百炼 Key 到新千问平台。','未保存的 Key 只保留在当前页面输入框内存中，不进入网址、历史记录或浏览器存储。刷新、关闭页面会丢失草稿；请勿把 Key 发到聊天中。']},
    capabilities: {title:'文字、视觉、语音怎样配合？', paragraphs:['文字模型：把原文、转写或检索资料整理成笔记、问答与关联。视觉模型：理解选中的视频画面，并结合前后讲解解释结构、层级和箭头。语音模型：在没有可用字幕时把音频转成文字。','先在连接编辑页勾选实际支持的能力并填写型号，再到“模型用途”分别选择。视觉与语音不会自动跟随默认文字连接。相同地址和 Key 可共用一个连接；接口不同则分开添加。','测试与真实任务会把必要文字、选定图片或音频发送给对应服务商。图文笔记需要视觉能力，纯文字视频笔记可优先使用字幕。'], action:'打开模型用途',view:'model-routing'},
    host: {title:'宿主模式包含视觉和语音吗？', paragraphs:['宿主模式让 WorkBuddy 等客户端完成文字生成。本页准备资料与生成提示，不会替换宿主自己的对话模型。','视觉理解与语音识别由本项目单独调用，需要在“模型用途”中配置。选择宿主文字模式并不代表宿主会自动承担这两项能力。']},
    gateway: {title:'出现 401、403 或网关错误怎么处理？', paragraphs:['401 / 403：核对平台、计费入口、Key 权限和型号是否配套。不要把真实 Key 放进问题描述。','502：网关收到异常上游响应；503：服务暂时不可用；504：网关等待上游超时。这些状态只能描述响应，不能单独证明网络、模型或订阅的具体故障原因。','记录 Base URL、模型 ID、错误码和发生步骤（获取列表、测试或生成），再排查服务状态和账户权限。应用不会自动切换计费入口、使用另一把 Key 或替你重试付费请求。']}
  };
  function parseRoute(search) {
    const query = new URLSearchParams(search);
    const view = Object.hasOwn(viewNames, query.get('view')) ? query.get('view') : 'home';
    const route = {view};
    if (['model-edit','model-routing'].includes(view)) {
      const id = query.get('profile') || '';
      if (/^[a-zA-Z0-9_-]{1,64}$/.test(id)) route.profile = id;
      else if (view === 'model-edit') return {view:'models'};
    }
    if (view === 'help' && Object.hasOwn(helpTopics, query.get('topic'))) route.topic = query.get('topic');
    return route;
  }
  function routeURL(route) {
    const query = new URLSearchParams();
    query.set('view', route.view);
    if (route.profile) query.set('profile', route.profile);
    if (route.topic) query.set('topic', route.topic);
    const clean = parseRoute(query.toString());
    const safe = new URLSearchParams(clean);
    return '?'+safe.toString();
  }
  function handleProfileFormChange(event, actions) {
    // A select emits input before change. Its dedicated change handler must read
    // the chosen billing entry before a generic refresh can infer it from the URL.
    if (['test-capability','provider-option'].includes(event.target.id)) return;
    actions.markDirty(); actions.updateCapabilities(); actions.updateThinking();
  }
  function acceptConfigSnapshot(current, value) {
    const incoming=value.config||value;
    // public_config exposes revision (config_revision belongs to task snapshots).
    // A GET started before a write may finish after it; never roll the UI back.
    if(current&&Number.isFinite(current.revision)&&
       (!Number.isFinite(incoming.revision)||incoming.revision<current.revision))return current;
    return incoming;
  }
  async function withDisabledControls(controls, action) {
    const previous=Array.from(controls,element=>[element,element.disabled]);
    previous.forEach(([element])=>{element.disabled=true;});
    try { return await action(); }
    finally { previous.forEach(([element,disabled])=>{element.disabled=disabled;}); }
  }
  // The same route and event boundaries are exercised by dependency-free Node tests.
  if (typeof document === 'undefined') { module.exports = {parseRoute, routeURL, handleProfileFormChange, withDisabledControls, acceptConfigSnapshot}; return; }
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
    history.replaceState(null, '', location.pathname + location.search);
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
  let profileSaving = false;
  let configRefreshAt = 0;
  let currentRoute = parseRoute(location.search);
  let editorIdentity = '';
  let helpReturn = null;
  let highlightedProfile = '';
  let profilesSignature = '';
  let routeIndex = Number.isSafeInteger(history.state && history.state.kbRouteIndex) ? history.state.kbRouteIndex : 0;
  const testingJobs = new Set();
  const terminal = new Set(['succeeded', 'completed', 'failed', 'interrupted', 'cancelled', 'stale']);
  const jobNames = { prepare_semantic:'准备语义检索', prepare_video:'准备视频组件', index_vault:'建立或同步索引', index:'建立检索索引', query:'知识库问答', qa:'知识库问答', correlation:'关联分析', video_prepare:'视频转写', ingest:'整理笔记', generate_note:'整理笔记', model_test:'测试模型连接' };
  const statusNames = { queued:'排队中', pending:'排队中', running:'进行中', completed:'已完成', succeeded:'已完成', failed:'失败，可重试', interrupted:'已中断，可恢复', cancelled:'已停止', stale:'来源已变化' };
  const providerSymbols = { qwen:'Q', kimi:'K', glm:'G', deepseek:'D', ollama:'◉', custom:'⌘' };
  const providerShortNames = { qwen:'千问AI平台', kimi:'Kimi', glm:'智谱 GLM', deepseek:'DeepSeek', ollama:'本地 Ollama', custom:'自定义服务' };
  const capabilityNames = {text:'文字',vision:'视觉',asr:'语音'};
  const capabilitiesOf = profile => Array.isArray(profile.capabilities) ? profile.capabilities : ['text'];
  const modelFor = (profile, capability) => capability === 'text' ? profile.model_id || '' : (profile.capability_models || {})[capability] || '';

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
    finally {
      if (button) {
        button.disabled = false; button.removeAttribute('aria-busy');
        if (['test-profile','list-models','import-template-key','import-legacy-key'].includes(button.id)) updateProfileButtons();
      }
    }
  }
  function editorKey(route) { return route.view === 'model-edit' ? 'edit:' + route.profile : route.view === 'model-new' ? 'new' : ''; }
  function focusRoute(route, targetId) {
    requestAnimationFrame(() => {
      const page = byId('page-' + (editorKey(route) ? 'model-editor' : route.view));
      const target = targetId && byId(targetId) || (page && page.querySelector('h1,h2'));
      if (target && !target.closest('[hidden]')) {
        if(target.matches('h1,h2,.profile'))target.setAttribute('tabindex','-1');
        target.focus({preventScroll:true});
        if(targetId)target.scrollIntoView({block:'center',behavior:'instant'});
      }
    });
  }
  function renderHelp() {
    const topic = currentRoute.topic;
    const sidebar = byId('help-topics'); sidebar.replaceChildren();
    const overview = node('a','帮助目录'); overview.href='?view=help'; overview.dataset.help='';
    if (!topic) overview.setAttribute('aria-current','page'); sidebar.append(overview);
    Object.entries(helpTopics).forEach(([id, item]) => {
      const link=node('a',item.title); link.href=routeURL({view:'help',topic:id}); link.dataset.help=id;
      if(topic===id)link.setAttribute('aria-current','page'); sidebar.append(link);
    });
    const content=byId('help-content'); content.replaceChildren();
    if (topic) {
      const item=helpTopics[topic]; content.append(node('h2',item.title));
      item.paragraphs.forEach(text=>content.append(node('p',text)));
      (item.links||[]).forEach(([label,url])=>{const link=node('a',label,'help-source');link.href=url;link.target='_blank';link.rel='noopener noreferrer';content.append(link);});
      if(item.view){const button=node('button',item.action);button.type='button';button.addEventListener('click',()=>navigate({view:item.view}));content.append(button);}
    } else {
      content.append(node('h2','从哪里开始？'),node('p','先添加连接，再按需要测试和分配用途。点击一个问题，只查看对应说明；输入框旁也有直达帮助。'));
      Object.entries(helpTopics).forEach(([id,item])=>{const link=node('a',item.title,'help-directory-link');link.href=routeURL({view:'help',topic:id});link.dataset.help=id;content.append(link);});
    }
    byId('help-return').textContent=helpReturn?'返回'+(editorKey(helpReturn.route)?'刚才的输入框':viewNames[helpReturn.route.view]):'返回我的模型';
  }
  function renderRoute({focus=true, targetId} = {}) {
    if (config && currentRoute.profile && !profileById(currentRoute.profile)) {
      currentRoute={view:'models'};history.replaceState({kbRouteIndex:routeIndex},'',routeURL(currentRoute));
      message('这个连接已不存在，请从“我的模型”重新选择。');
    }
    const key=editorKey(currentRoute);
    byId('profile-editor').hidden=!config;
    byId('editor-loading').hidden=!!config;
    if (config && key && key!==editorIdentity) {
      if(currentRoute.view==='model-new')newProfile(); else populateProfile(currentRoute.profile);
      editorIdentity=key;
    }
    const page=key?'model-editor':currentRoute.view;
    document.querySelectorAll('.page').forEach(element=>{element.hidden=element.id!=='page-'+page;});
    document.querySelectorAll('.main-nav [data-page]').forEach(button=>{
      const active=button.dataset.page===(page.startsWith('model')?'models':page);
      button.classList.toggle('active',active);
      if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
    if(currentRoute.view==='help')renderHelp();
    if(currentRoute.view==='model-routing') {
      const profile=profileById(currentRoute.profile);byId('routing-context').hidden=!profile;
      byId('routing-context').textContent=profile?'正在查看“'+profile.name+'”的用途。下面保留当前选择，请手动分配后保存；进入此页不会自动启用。':'';
    }
    byId('model-draft-notice').hidden=!profileDirty;
    document.title=(currentRoute.view==='help'&&currentRoute.topic?helpTopics[currentRoute.topic].title:viewNames[currentRoute.view])+' · Personal KB';
    if(focus){window.scrollTo({top:0,behavior:'instant'});focusRoute(currentRoute,targetId);}
  }
  function canNavigate(route) {
    if(profileSaving){message('正在保存连接，请等待保存结果后再切换页面。');return false;}
    const key=editorKey(route);
    return !key || !editorIdentity || key===editorIdentity || !profileDirty || confirm('切换到另一份连接会丢弃当前未保存的草稿（包括输入的 Key）。仍要继续吗？');
  }
  function navigate(route, {replace=false, targetId} = {}) {
    route=parseRoute(routeURL(route));
    if(!canNavigate(route))return false;
    if (editorKey(route) && editorKey(route)!==editorIdentity) profileDirty=false;
    const same=routeURL(route)===routeURL(currentRoute);
    currentRoute=route;
    if(!same&&!replace)routeIndex+=1;
    history[same||replace?'replaceState':'pushState']({kbRouteIndex:routeIndex},'',routeURL(route));
    renderRoute({targetId});return true;
  }
  function showPage(page) { navigate({view:page==='settings'?'models':page}); }
  window.addEventListener('popstate',event=>{
    const route=parseRoute(location.search);
    const targetIndex=Number.isSafeInteger(event.state&&event.state.kbRouteIndex)?event.state.kbRouteIndex:0;
    if(!canNavigate(route)) {
      if(targetIndex!==routeIndex)history.go(routeIndex-targetIndex);
      else history.replaceState({kbRouteIndex:routeIndex},'',routeURL(currentRoute));
      return;
    }
    if(editorKey(route)&&editorKey(route)!==editorIdentity)profileDirty=false;
    const focusId=currentRoute.view==='help'&&helpReturn&&routeURL(route)===routeURL(helpReturn.route)?helpReturn.focusId:null;
    routeIndex=targetIndex;currentRoute=route;
    history.replaceState({kbRouteIndex:routeIndex},'',routeURL(route));renderRoute({targetId:focusId});
  });
  window.addEventListener('beforeunload',event=>{if(profileDirty||routingDirty||profileSaving){event.preventDefault();event.returnValue='';}});
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
      byId('video-state').textContent = video.ready ? '视频组件已就绪' : video.phase === 'failed' ? '准备失败，可重试' : video.phase === 'preparing' ? '后台准备中' : '未启用';
      byId('prepare-semantic').disabled = !!semantic.ready || semantic.phase === 'preparing';
      byId('prepare-video').disabled = !!video.ready || video.phase === 'preparing';
      renderCapabilitySummary();
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

  function fillProfileSelect(select, value, isDefault = false, capability = 'text') {
    select.replaceChildren();
    const empty = node('option', capability !== 'text' ? '未配置' : isDefault ? '未指定默认连接' : '跟随默认文字连接'); empty.value = ''; select.append(empty);
    (config.profiles || []).filter(profile => capabilitiesOf(profile).includes(capability)).forEach(profile => {
      const model = modelFor(profile, capability);
      const option = node('option', profile.name + ' · ' + (model || '尚未填写型号')); option.value = profile.id; select.append(option);
    });
    select.value = value || '';
  }
  function renderCapabilitySummary() {
    const routes = config && config.capability_profiles || {};
    const labels = ['vision','asr'].map(capability => {
      const profile = profileById(routes[capability]);
      return capabilityNames[capability] + '：' + (profile ? profile.name : '未配置');
    });
    byId('key-state').textContent = labels.join(' · ') + '。可在“模型用途”中分别选择。';
  }
  function renderModeSummary() {
    if (!config) return;
    const current = profileById(config.default_profile);
    byId('generation-summary').textContent = config.generation_mode === 'independent'
      ? '独立模型 · ' + (current ? current.name + ' / ' + current.model_id : '按任务指定')
      : '宿主模型 · 由 WorkBuddy 等客户端完成生成';
    byId('model-list-summary').textContent = byId('generation-summary').textContent;
    byId('task-mode-hint').textContent = config.generation_mode === 'independent'
      ? '当前使用独立模型。任务内容将发送至所选服务，调用可能产生费用。'
      : '当前使用宿主模式。本页准备资料后，可将生成提示交给 WorkBuddy；选择独立模型可在本页完成生成。';
  }
  function renderRouting() {
    if (!config || routingDirty) return;
    document.querySelectorAll('[name="generation-mode"]').forEach(input => { input.checked = input.value === config.generation_mode; });
    fillProfileSelect(byId('default-profile'), config.default_profile, true);
    ['ingest', 'qa', 'correlation'].forEach(kind => fillProfileSelect(byId('profile-' + kind), (config.task_profiles || {})[kind]));
    ['vision','asr'].forEach(capability => fillProfileSelect(byId('profile-' + capability), (config.capability_profiles || {})[capability], false, capability));
    byId('model-config-state').textContent = config.generation_mode === 'independent' ? '独立模型已启用' : '宿主模式已启用';
    byId('routing-state').textContent = '当前配置已保存';
    updateRoutingVisibility();
  }
  function updateRoutingVisibility() {
    const independent = document.querySelector('[name="generation-mode"]:checked');
    byId('routing-fields').hidden = false;
    const asrProfile=profileById(byId('profile-asr').value);
    byId('routing-asr-hint').hidden=!(asrProfile&&isTokenPlan(asrProfile.base_url)&&asrProfile.audio_api_style==='dashscope');
    byId('routing-fields-hint').textContent = independent && independent.value === 'independent' ? '以下连接用于新任务；任务指定优先于默认连接。' : '这些连接选择将在切回独立模式后生效。删除被引用的连接前，可在此清空引用并保存。';
  }
  function renderProfiles() {
    const signature=JSON.stringify([config.profiles,config.generation_mode,config.default_profile,config.task_profiles,config.capability_profiles,highlightedProfile]);
    if(signature===profilesSignature)return;
    profilesSignature=signature;
    const holder = byId('profiles'); holder.replaceChildren();
    byId('profile-count').textContent=String((config.profiles||[]).length);
    if (!(config.profiles || []).length) {
      holder.append(node('p', '还没有模型连接。点击“添加模型连接”，保存后会显示在这里。', 'empty-state')); return;
    }
    config.profiles.forEach(profile => {
      const item = node('article', '', 'profile'+(profile.id===highlightedProfile?' recently-saved':''));
      item.id='model-card-'+profile.id;item.tabIndex=-1;item.setAttribute('aria-label',profile.name);
      const head = node('div', '', 'profile-heading');
      const info = node('div', '', 'profile-info');
      info.append(node('strong', profile.name));
      const capabilities = capabilitiesOf(profile);
      info.append(node('p', (profile.provider==='qwen'&&isLegacyQwen(profile.base_url)?'百炼（原有连接）':(providerById(profile.provider) || {}).name || profile.provider) + ' · ' + capabilities.map(capability => capabilityNames[capability] + ' ' + (modelFor(profile, capability) || '未填型号')).join(' / '), 'profile-subtitle'));
      const tags = node('div', '', 'profile-tags');
      tags.append(badge('已保存'));
      capabilities.forEach(capability => {
        const test = capability === 'text' ? {status:profile.test_status,tested_revision:profile.tested_revision} : (profile.capability_test_status || {})[capability] || {};
        const current = test.tested_revision != null && test.tested_revision === profile.revision;
        const passed = current && ['passed','succeeded','success'].includes(test.status);
        const failed = test.status === 'failed' && (test.tested_revision == null || current);
        const label = passed ? '测试通过' : failed ? '测试失败' : test.tested_revision != null ? '配置已变更，需重测' : '尚未测试';
        tags.append(badge(capabilityNames[capability] + ' · ' + label, passed ? 'success' : failed ? 'error' : ''));
      });
      const activeRoles = [];
      if (config.generation_mode === 'independent') {
        [['ingest','笔记整理'],['qa','知识问答'],['correlation','关联分析']].forEach(([key,label]) => { if (((config.task_profiles || {})[key] || config.default_profile) === profile.id) activeRoles.push(label); });
      }
      ['vision','asr'].forEach(capability => { if ((config.capability_profiles || {})[capability] === profile.id) activeRoles.push(capabilityNames[capability]); });
      info.append(node('p','实际用途：'+(activeRoles.length?activeRoles.join(' / '):'尚未分配'),'profile-usage'));
      tags.append(badge(profile.credential_error ? '凭据库暂不可用' : profile.credential_present ? 'Key 已保存' : ['ollama','custom'].includes(profile.provider) && /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(?::|\/|$)/.test(profile.base_url) ? '本机免 Key' : '未配置 Key'));
      info.append(tags);
      const buttons = node('div', '', 'profile-buttons');
      const edit = node('button', '编辑'); edit.type='button'; edit.addEventListener('click', () => editProfile(profile.id));
      const activate = node('button', '配置用途'); activate.type='button'; activate.addEventListener('click',()=>navigate({view:'model-routing',profile:profile.id}));
      const remove = node('button', '删除', 'danger'); remove.type='button'; remove.addEventListener('click', () => withButton(remove, async () => {
        if (!confirm('删除连接“' + profile.name + '”？该连接保存的 Key 也会移除。已被默认或任务配置引用时，请先解除引用。')) return;
        applyConfig(await request('/api/models/delete', {profile_id:profile.id}), false);
        if (byId('profile-id').value === profile.id) { newProfile(); editorIdentity=''; renderRoute({focus:false}); }
        message('连接已删除。');
      }));
      buttons.append(edit);
      capabilities.forEach(capability => {
        const test = node('button', '测试' + capabilityNames[capability]); test.type='button';
        test.title = testDescription(capability); test.disabled = !modelFor(profile, capability);
        test.addEventListener('click', () => withButton(test, () => testProfile(profile.id, capability)));
        buttons.append(test);
      });
      buttons.append(activate);
      buttons.append(remove); head.append(info, buttons); item.append(head); holder.append(item);
    });
  }
  function renderProviders() {
    const holder = byId('provider-grid'); holder.replaceChildren();
    (config.providers || []).forEach(provider => {
      const button = node('button', '', 'provider-card' + (selectedProvider === provider.id ? ' active' : ''));
      button.type='button'; button.setAttribute('aria-pressed', selectedProvider === provider.id ? 'true' : 'false');
      button.append(node('span', providerSymbols[provider.id] || '◇', 'provider-symbol'), node('span', providerShortNames[provider.id] || provider.name));
      button.addEventListener('click', () => {
        if(selectedProvider===provider.id)return;
        if(!confirm('切换服务商会更新建议地址和文字型号，并清空尚未保存的 Key；连接名称和其他能力仍保留。继续吗？'))return;
        const name=byId('profile-name').value;
        byId('model-key').value='';selectProvider(provider.id,true);byId('profile-name').value=name;markProfileDirty();
      });
      holder.append(button);
    });
  }
  function applyConfig(value, forceRouting = false) {
    const incoming=acceptConfigSnapshot(config,value);
    if(incoming===config)return;
    config=incoming;
    configRefreshAt = Date.now();
    if (forceRouting) routingDirty = false;
    renderModeSummary(); renderCapabilitySummary(); renderRouting(); renderProfiles(); renderProviders(); renderSecretSources();
    if (!selectedProvider && (config.providers || []).length) selectProvider(config.providers[0].id, true);
    updateProfileButtons();
    renderRoute({focus:false});
  }
  async function loadModels(forceRouting = false) {
    if(profileSaving)return;
    const value = await request('/api/models');
    if(!profileSaving)applyConfig(value, forceRouting);
  }
  function updateThinking() {
    const provider = providerById(selectedProvider) || {};
    const modelId = byId('model-id').value.trim();
    const dynamic = provider.thinking_dynamic === true;
    const supported = byId('capability-text').checked && Boolean(modelId) && (dynamic || (provider.thinking_models || []).includes(modelId));
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
      byId('audio-api-style').value = id === 'qwen' ? 'dashscope' : 'openai_audio';
    }
    byId('provider-hint').textContent = provider.hint || '请使用该服务商的模型 API 地址和对应凭据。';
    byId('qwen-plan-hint').hidden = id !== 'qwen';
    renderConnectionOptions();
    renderProviders(); updateCapabilities(); updateThinking();
  }
  function isLegacyQwen(url) {
    try {
      const host=new URL(url).hostname;
      return ['dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com','dashscope-us.aliyuncs.com'].includes(host)||/^[a-z0-9][a-z0-9-]{0,63}\.(cn-beijing|ap-southeast-1|us-east-1)\.maas\.aliyuncs\.com$/.test(host);
    } catch (_) { return false; }
  }
  function isTokenPlan(url) {
    try { return new URL(url).hostname==='token-plan.maas.qianwenaiapi.com'; } catch (_) { return false; }
  }
  function renderConnectionOptions() {
    const options=(providerById(selectedProvider)||{}).connection_options||[];
    const select=byId('provider-option');select.replaceChildren();
    byId('provider-option-field').hidden=!options.length;
    options.forEach(item=>{const option=node('option',item.name);option.value=item.id;select.append(option);});
    const custom=node('option','保留 / 手动填写地址');custom.value='custom';select.append(custom);
    updateConnectionHint();
  }
  function updateConnectionHint() {
    const options=(providerById(selectedProvider)||{}).connection_options||[];
    const url=byId('model-url').value.trim().replace(/\/$/,'');
    const current=options.find(item=>item.base_url===url);
    byId('provider-option').value=current?current.id:'custom';
    byId('provider-option-hint').textContent=current?current.hint:selectedProvider==='qwen'?'保留当前手填地址，不会自动替换。旧百炼连接迁移到千问时，请明确选择计费入口并填写对应的新 Key。':'';
    byId('asr-plan-hint').hidden=!(byId('capability-asr').checked&&isTokenPlan(url)&&byId('audio-api-style').value==='dashscope');
    byId('model-key-format').hidden=selectedProvider!=='qwen';
    byId('model-key-format').textContent=isTokenPlan(url)?'Token Plan 专属 Key 通常以 sk-sp- 开头，请使用对应订阅的 Key。前缀仅供识别，应用不会仅凭前缀拒绝凭据。':isLegacyQwen(url)?'这是原有百炼地址，请使用对应地域或工作空间的百炼 Key；不要直接混用新千问平台的 Key。':'千问按量 API Key 通常以 sk-ws- 开头，早期 Key 可能以 sk- 开头。请以账户显示的入口为准；前缀不是兼容性的唯一依据。';
    const saved=profileById(byId('profile-id').value);
    let changed=false;
    try { changed=!!saved&&(saved.provider!==selectedProvider||new URL(saved.base_url).origin!==new URL(url).origin); } catch (_) { /* Invalid URL is handled by the form. */ }
    byId('model-key-label').textContent=changed&&saved.credential_present?'（地址或服务商已变更，请重新填写对应 Key 或移除旧 Key）':saved&&saved.credential_present?'（已保存，留空保留）':'（尚未保存）';
  }
  function selectedCapabilities() {
    return Object.keys(capabilityNames).filter(capability => byId('capability-' + capability).checked);
  }
  function updateCapabilities() {
    const capabilities = selectedCapabilities();
    byId('vision-model-field').hidden = !capabilities.includes('vision');
    byId('asr-model-field').hidden = !capabilities.includes('asr');
    byId('audio-api-style-field').hidden = !capabilities.includes('asr');
    byId('model-id').disabled = !capabilities.includes('text');
    const select = byId('test-capability');
    const current = select.value;
    select.replaceChildren();
    capabilities.forEach(capability => { const option = node('option', capabilityNames[capability]); option.value = capability; select.append(option); });
    if (capabilities.includes(current)) select.value = current;
    updateConnectionHint();
    updateProfileButtons();
  }
  function renderSecretSources() {
    byId('secret-template-path').textContent = config.secret_template_path ? '空模板：' + config.secret_template_path : '模板位置尚未获取';
    byId('secret-input-path').textContent = config.secret_input_path ? '填写文件：' + config.secret_input_path : '填写文件位置尚未获取';
  }
  function testDescription(capability) {
    return {text:'发送简短文字请求，可能产生 API 费用',vision:'发送合成图片，可能产生 API 费用；不代表真实画面理解质量',asr:'发送静音 WAV，可能产生 API 费用；不代表真实转写质量'}[capability] || '请先选择要测试的能力';
  }
  function markProfileDirty() {
    profileDirty = true;
    byId('model-draft-notice').hidden=false;
    byId('profile-save-state').textContent = '有未保存的修改';
    updateProfileButtons();
  }
  function updateProfileButtons() {
    if(profileSaving)return;
    const saved = !!byId('profile-id').value;
    const capability = byId('test-capability').value;
    const modelInput = {text:'model-id',vision:'vision-model-id',asr:'asr-model-id'}[capability];
    byId('test-profile').disabled = !saved || profileDirty || !modelInput || !byId(modelInput).value.trim();
    byId('list-models').disabled = !saved || profileDirty;
    byId('test-profile').title = profileDirty ? '请先保存修改' : testDescription(capability);
    byId('test-profile').textContent = '测试已保存' + (capabilityNames[capability] || '') + '能力';
    byId('import-template-key').disabled = !saved || profileDirty;
    byId('import-legacy-key').disabled = !saved || profileDirty || selectedProvider !== 'qwen' || !isLegacyQwen(byId('model-url').value) || !(config && config.legacy_secret_present);
    byId('secret-import-hint').textContent = !saved ? '请先保存并选择一个连接。成功写入系统凭据库并回读校验后，清空来源密钥字段；失败保留原值。' : profileDirty ? '请先保存或取消修改，再导入到当前连接。' : '导入目标：' + ((profileById(byId('profile-id').value) || {}).name || '当前连接') + '。成功写入系统凭据库并回读校验后，清空原文件密钥字段，保留其他内容；失败保留原值。旧 DashScope Key 仅可导入使用原百炼官方地址的连接，不能迁移为新千问凭据。';
  }
  async function saveProfileExclusively(action) {
    if(profileSaving)throw new Error('正在保存，请等待当前请求完成。');
    profileSaving=true;
    byId('profile-form').setAttribute('aria-busy','true');
    byId('profile-save-state').textContent='正在保存，请稍候…';
    try {
      return await withDisabledControls(document.querySelectorAll('#profile-form input, #profile-form select, #profile-form button, #provider-grid button, #cancel-edit, #page-model-editor [data-page]'),action);
    } finally {
      profileSaving=false;byId('profile-form').removeAttribute('aria-busy');
      byId('profile-save-state').textContent=profileDirty?'有未保存的修改':byId('profile-id').value?'已保存的配置保持不变':'尚未保存连接';
      updateProfileButtons();
    }
  }
  function newProfile(providerId) {
    byId('profile-form').reset(); byId('profile-id').value = '';
    byId('model-options').replaceChildren(); byId('clear-key-label').hidden = true;
    byId('model-key-label').textContent = '';
    byId('model-key').placeholder = '输入此服务商的 API Key；本机模型可留空';
    byId('editor-context').textContent='我的模型 / 添加连接';
    byId('editor-title').textContent = '添加模型连接'; byId('cancel-edit').hidden = false;
    byId('profile-save-state').textContent = '';
    profileDirty = false;
    selectProvider(providerId || selectedProvider || (config.providers[0] || {}).id, true);
    updateProfileButtons();
  }
  function editProfile(id) { navigate({view:'model-edit',profile:id}); }
  function populateProfile(id) {
    const profile = profileById(id); if (!profile) return;
    byId('profile-form').reset();byId('model-options').replaceChildren();
    byId('profile-id').value = profile.id;
    byId('profile-name').value = profile.name;
    byId('model-id').value = profile.model_id;
    Object.keys(capabilityNames).forEach(capability => { byId('capability-' + capability).checked = capabilitiesOf(profile).includes(capability); });
    byId('vision-model-id').value = modelFor(profile, 'vision');
    byId('asr-model-id').value = modelFor(profile, 'asr');
    byId('audio-api-style').value = profile.audio_api_style || 'dashscope';
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
    byId('editor-context').textContent='我的模型 / '+profile.name;
  }
  async function testProfile(profileId, capability = 'text') {
    const profile = profileById(profileId);
    if (!profile) throw new Error('请先保存模型连接。');
    if (!capabilitiesOf(profile).includes(capability) || !modelFor(profile, capability)) throw new Error('请先为此连接保存对应能力与型号。');
    const result = await request('/api/models/test', {profile_id:profileId,capability});
    if (result.job_id) {
      testingJobs.add(result.job_id);
      message('正在测试“' + profile.name + '”的' + capabilityNames[capability] + '能力。' + testDescription(capability) + '。结果可在后台任务中查看。');
      await selectJob(result.job_id);
    } else message('连接测试已提交。');
    await refresh();
  }
  async function importSecret(source) {
    const profileId = byId('profile-id').value;
    const profile = profileById(profileId);
    if (!profile || profileDirty) throw new Error('请先保存并选择目标连接。');
    if (source === 'legacy' && (profile.provider !== 'qwen' || !isLegacyQwen(profile.base_url))) throw new Error('旧 DashScope Key 只可导入使用原百炼官方地址的连接。');
    if (!confirm('将本机文件中的 Key 导入“' + profile.name + '”' + (profile.credential_present ? '并替换此连接当前保存的 Key' : '') + '？系统凭据库写入并回读校验成功后，会清空原文件的密钥字段并保留其他内容；失败时保留原值。')) return;
    await request('/api/models/import-secret', {profile_id:profileId,source});
    await loadModels(false); populateProfile(profileId);
    message('Key 已导入“' + profile.name + '”。原文件的密钥字段已清空，其他内容保留；请分别测试需要的能力。');
  }

  function clearResult() {
    finalText = '';
    byId('detail-text').textContent = ''; byId('detail-text').hidden = true;
    byId('detail-meta').replaceChildren();
    byId('detail-references').replaceChildren(); byId('detail-references').hidden = true;
    byId('detail-metrics').replaceChildren(); byId('detail-metrics').hidden = true;
    byId('detail-media').replaceChildren(); byId('detail-media').hidden = true;
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
  function renderMedia(media, saved) {
    if (!media || typeof media !== 'object') return;
    const frames = Array.isArray(media.frames) ? media.frames : [];
    const precision = Array.isArray(media.timeline_precision) ? media.timeline_precision : media.timeline_precision ? [media.timeline_precision] : [];
    const holder = byId('detail-media');
    holder.replaceChildren(node('h3','视频画面与时间定位'));
    const labels = {subtitle:'字幕时间',chunk:'分块转写时间（近似）',approximate:'近似时间'};
    const precisionText = [...new Set(precision.map(value => labels[value] || '时间精度未标注'))].join('、');
    holder.append(node('p', precisionText ? '讲解定位依据：' + precisionText + '。' : '讲解时间精度未标注；请结合原视频核对。', 'footnote'));
    if (precision.includes('chunk') || precision.includes('approximate')) holder.append(node('p','分块时间用于寻找附近讲解，不是逐句精确时间戳。','footnote'));
    if (media.sampling) {
      const sampling = typeof media.sampling === 'string' ? media.sampling : media.sampling.method || media.sampling.mode || '';
      const samplingLabels = {manual:'手动时间点',uniform:'有限均匀采样',uniform_nearby:'有限自动采样',automatic:'有限自动采样',auto:'有限自动采样'};
      holder.append(node('p', '画面选择：' + (samplingLabels[sampling] || '有限采样') + '，不保证覆盖视频的全部重点。', 'footnote'));
    }
    if (frames.length) {
      const list = node('ul');
      frames.forEach((frame, index) => {
        if (!frame || typeof frame !== 'object') return;
        const time = typeof frame.time === 'number' && Number.isFinite(frame.time) ? Number(frame.time.toFixed(2)) + ' 秒' : '时间未标注';
        const item = node('li');
        item.append(node('strong', (frame.id || '画面 ' + (index + 1)) + ' · ' + time));
        if (typeof frame.relative_path === 'string') item.append(node('code', frame.relative_path));
        list.append(item);
      });
      holder.append(list, node('p', (saved ? '附件路径相对于笔记库；可在 Obsidian 中打开笔记和画面。' : '以上为计划保存位置；宿主完成正文并保存后，可在 Obsidian 中查看笔记和画面。') + '画面解读结合前后约 30 秒讲解，请审核其中的层级、箭头与推断。','footnote'));
    } else holder.append(node('p','本次结果没有返回画面附件。','footnote'));
    holder.hidden = false;
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
      byId('detail-state').textContent = '待审核草稿';
      byId('detail-state').className = 'badge success';
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
    if (!text && ['model_test','test_model','test_connection'].includes(job.kind)) text = result.ok === false ? '连接测试未通过，请检查错误说明。' : (capabilityNames[result.capability] || '所选') + '能力接口测试已完成，已收到服务响应；不代表其他能力可用或真实内容质量。';
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
    renderMedia(result.media, result.status === 'staged');
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
  function frameTimes() {
    const value = byId('frame-times').value.trim();
    if (!value) return [];
    const parts = value.split(/[,，]/).map(part => part.trim());
    if (parts.length > 8) throw new Error('最多指定 8 个画面时间点。');
    if (parts.some(part => !/^\d+(?:\.\d+)?$/.test(part) || !Number.isFinite(Number(part)))) throw new Error('画面时间请填写非负秒数，用逗号分隔，例如 90, 125.5, 240。');
    return parts.map(Number);
  }
  function updateVideoMode() {
    const mode = document.querySelector('[name="video-mode"]:checked');
    byId('frame-times-field').hidden = !mode || mode.value !== 'illustrated';
  }
  function updateTaskForm() {
    const kind=byId('task-kind').value;
    byId('task-folder-field').hidden=kind!=='ingest';
    byId('task-input-field').hidden=!['ingest','query'].includes(kind);
    byId('task-input').required=['ingest','query'].includes(kind);
    byId('task-input-label').textContent=kind==='query'?'想向知识库提出的问题':'想整理的原文、想法或视频链接';
    byId('task-input').placeholder=kind==='query'?'例如：我的笔记中，RAG 检索质量有哪些优化方法？':'粘贴文字或视频链接，并说明希望理解和保存的内容。';
    byId('task-video-fields').hidden=kind!=='ingest';
    updateVideoMode();
    byId('task-note-field').hidden=kind!=='correlation';byId('task-note').required=kind==='correlation';
    byId('task-query-folder-field').hidden=kind!=='query';
    byId('task-index-fields').hidden=kind!=='index';byId('index-authorize').required=kind==='index';
    byId('submit-task').textContent={ingest:'开始整理',query:'开始提问',correlation:'发现关联',index:'建立 / 更新索引'}[kind];
    byId('task-submit-hint').textContent={ingest:'新笔记保存为待审核草稿，由你决定是否正式收录。',query:'问答只使用已授权且仍有效的索引资料。',correlation:'只分析已审核笔记的关联，不自动修改双链。',index:'只有你明确勾选授权后，才会建立本次范围的索引。'}[kind];
  }

  document.querySelectorAll('[data-page]').forEach(button=>button.addEventListener('click',()=>showPage(button.dataset.page)));
  document.querySelector('.brand').addEventListener('click',event=>{event.preventDefault();showPage('home');});
  ['open-settings','hero-settings'].forEach(id=>byId(id).addEventListener('click',()=>showPage('models')));
  ['edit-generation','video-settings'].forEach(id=>byId(id).addEventListener('click',()=>showPage('model-routing')));
  document.addEventListener('click',event=>{
    const link=event.target.closest('a[data-help]');if(!link||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    event.preventDefault();
    if(currentRoute.view!=='help')helpReturn={route:{...currentRoute},focusId:link.dataset.returnFocus||''};
    navigate({view:'help',topic:link.dataset.help||undefined});
  });
  byId('help-return').addEventListener('click',()=>navigate(helpReturn?helpReturn.route:{view:'models'},{targetId:helpReturn&&helpReturn.focusId}));
  byId('resume-profile').addEventListener('click',()=>navigate(editorIdentity==='new'?{view:'model-new'}:{view:'model-edit',profile:byId('profile-id').value}));
  byId('start-task').addEventListener('click',()=>showPage('tasks'));
  byId('theme-toggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
  byId('register').addEventListener('click',()=>action('/api/register',{},byId('register')));
  byId('refresh').addEventListener('click',()=>withButton(byId('refresh'),refresh));
  byId('prepare-semantic').addEventListener('click',()=>action('/api/prepare',{feature:'semantic'},byId('prepare-semantic')));
  byId('prepare-video').addEventListener('click',()=>action('/api/prepare',{feature:'video'},byId('prepare-video')));
  byId('routing-form').addEventListener('change',()=>{routingDirty=true;byId('routing-state').textContent='有未应用的修改';updateRoutingVisibility();});
  byId('routing-form').addEventListener('submit',event=>{
    event.preventDefault();withButton(byId('save-routing'),async()=>{
      const mode=document.querySelector('[name="generation-mode"]:checked');
      if (!mode) throw new Error('请先等待模型配置加载完成。');
      const defaultProfile=byId('default-profile').value || null;
      const taskProfiles={};['ingest','qa','correlation'].forEach(key=>{taskProfiles[key]=byId('profile-'+key).value || null;});
      const capabilityProfiles={};['vision','asr'].forEach(key=>{capabilityProfiles[key]=byId('profile-'+key).value || null;});
      if (mode.value==='independent' && !defaultProfile && Object.values(taskProfiles).some(value=>!value)) throw new Error('请选择默认模型连接，或为三种任务分别指定连接。');
      applyConfig(await request('/api/models/save',{generation_mode:mode.value,default_profile:defaultProfile,task_profiles:taskProfiles,capability_profiles:capabilityProfiles}),true);
      message('生成配置已保存并应用，只影响之后开始的新任务。');
    });
  });
  byId('new-profile').addEventListener('click',()=>{if(config)navigate({view:'model-new'},{targetId:'profile-name'});});
  byId('cancel-edit').addEventListener('click',()=>{if(profileSaving)return;if(profileDirty&&!confirm('取消会丢弃未保存的修改和输入的 Key。继续吗？'))return;profileDirty=false;editorIdentity='';byId('profile-form').reset();navigate({view:'models'});});
  const profileFormActions={markDirty:markProfileDirty,updateCapabilities,updateThinking};
  ['input','change'].forEach(type=>byId('profile-form').addEventListener(type,event=>handleProfileFormChange(event,profileFormActions)));
  byId('provider-option').addEventListener('change',()=>{
    const option=((providerById(selectedProvider)||{}).connection_options||[]).find(item=>item.id===byId('provider-option').value);
    if(option){
      if(byId('model-url').value!==option.base_url)byId('model-key').value='';
      byId('model-url').value=option.base_url;updateConnectionHint();
    } else byId('provider-option-hint').textContent='保留当前地址，你可以在下方手动填写。应用不会因选择此项而替换地址或 Key。';
    markProfileDirty();
  });
  byId('model-url').addEventListener('input',updateConnectionHint);
  byId('profile-form').addEventListener('submit',event=>{
    event.preventDefault();withButton(byId('save-profile'),async()=>{
      const result=await saveProfileExclusively(async()=>{
      if (!selectedProvider) throw new Error('请先选择模型服务商。');
      const existingId=byId('profile-id').value;
      const profile={name:byId('profile-name').value.trim(),provider:selectedProvider,base_url:byId('model-url').value.trim(),model_id:byId('model-id').value.trim(),timeout_seconds:Number(byId('model-timeout').value),max_output_tokens:Number(byId('model-max-tokens').value),thinking:byId('model-thinking').value};
      profile.capabilities = selectedCapabilities();
      if (!profile.capabilities.length) throw new Error('请至少选择一项连接能力。');
      profile.capability_models = {vision:byId('vision-model-id').value.trim(),asr:byId('asr-model-id').value.trim()};
      profile.audio_api_style = byId('audio-api-style').value;
      if (!profile.capabilities.includes('text')) profile.model_id = '';
      if (existingId) profile.id=existingId;
      if (byId('model-key').value) profile.api_key=byId('model-key').value;
      if (byId('clear-model-key').checked) profile.clear_key=true;
      if (profile.api_key && profile.clear_key) throw new Error('输入新 Key 与移除 Key 不能同时选择。');
      const before=new Set((config.profiles||[]).map(item=>item.id));
      const value=await request('/api/models/save',{profile});
        return {value,existingId,before};
      });
      byId('model-key').value='';profileDirty=false;editorIdentity='';applyConfig(result.value);
      const saved=result.existingId || ((config.profiles||[]).find(item=>!result.before.has(item.id))||{}).id;
      highlightedProfile=saved||'';renderProfiles();
      navigate({view:'models'},{targetId:saved?'model-card-'+saved:undefined});
      message('已保存到“我的模型”。你可以在下方卡片编辑、按能力测试，再到“配置用途”选择是否启用。');
    });
  });
  byId('test-capability').addEventListener('change',updateProfileButtons);
  byId('test-profile').addEventListener('click',()=>withButton(byId('test-profile'),()=>testProfile(byId('profile-id').value,byId('test-capability').value)));
  byId('import-template-key').addEventListener('click',()=>withButton(byId('import-template-key'),()=>importSecret('template')));
  byId('import-legacy-key').addEventListener('click',()=>withButton(byId('import-legacy-key'),()=>importSecret('legacy')));
  byId('list-models').addEventListener('click',()=>withButton(byId('list-models'),async()=>{
    const result=await request('/api/models/list',{profile_id:byId('profile-id').value});
    const list=byId('model-options');list.replaceChildren();
    (result.models||[]).forEach(value=>{const option=node('option');option.value=typeof value==='string'?value:value.id;list.append(option);});
    byId('profile-save-state').textContent='获取到 '+(result.models||[]).length+' 个模型；在模型 ID 输入框中选择，或直接输入。';
    byId('model-id').focus();
  }));
  byId('task-kind').addEventListener('change',updateTaskForm);
  document.querySelectorAll('[name="video-mode"]').forEach(input=>input.addEventListener('change',updateVideoMode));
  byId('task-form').addEventListener('submit',event=>{
    event.preventDefault();withButton(byId('submit-task'),async()=>{
      const kind=byId('task-kind').value;
      const data={kind,vault_path:byId('task-vault').value.trim()};
      if (kind==='ingest') {
        data.user_input=byId('task-input').value.trim();data.folder=byId('task-folder').value.trim();
        data.video_mode=document.querySelector('[name="video-mode"]:checked').value;
        if(data.video_mode==='illustrated') data.frame_times=frameTimes();
      }
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
  history.replaceState({kbRouteIndex:routeIndex},'',routeURL(currentRoute));
  renderRoute({focus:false});
  if(!token)message('请双击安装入口打开此页面，认证信息会在本机自动传递。',true);
  else {
    loadModels().catch(error=>message(errorText(error),true));
    refresh();setInterval(refresh,3000);
  }
})();
