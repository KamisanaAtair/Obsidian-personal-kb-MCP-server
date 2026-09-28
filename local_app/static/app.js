(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  let token = location.hash.slice(1);
  if (token) {
    sessionStorage.setItem('personal-kb-ui', token);
    history.replaceState(null, '', location.pathname);
  } else token = sessionStorage.getItem('personal-kb-ui') || '';
  let stopped = false;
  let busy = false;
  function message(text, error = false) {
    const target = byId(error ? 'error' : 'notice');
    target.textContent = text; target.hidden = !text;
    byId(error ? 'notice' : 'error').hidden = true;
  }
  async function request(path, data) {
    const response = await fetch(path, {method: data === undefined ? 'GET' : 'POST',
      headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
      body: data === undefined ? undefined : JSON.stringify(data), cache: 'no-store'});
    const value = await response.json();
    if (!response.ok) throw new Error(response.status === 401 ? '请通过安装入口重新打开此页面。' : (value.error || '操作未完成，请重试。'));
    return value;
  }
  const jobNames = {prepare_semantic:'准备语义检索',prepare_video:'准备视频组件',index_vault:'建立或同步索引',query:'知识库查询',correlation:'关联分析',video_prepare:'视频转写'};
  const statusNames = {queued:'排队中',pending:'排队中',running:'进行中',completed:'已完成',succeeded:'已完成',failed:'失败，可重试',interrupted:'已中断，可恢复',cancelled:'已停止'};
  function node(tag,text,className) {const element=document.createElement(tag);element.textContent=text;if(className)element.className=className;return element;}
  function displayJobs(jobs) {
    const holder=byId('jobs');holder.replaceChildren();
    if (!jobs.length) {holder.append(node('p','暂无任务。','muted'));return;}
    jobs.slice(0,12).forEach(job=>{
      const item=node('div','','job');const title=node('div','','job-title');
      title.append(node('span',jobNames[job.kind] || '知识库任务'),node('span',statusNames[job.status]||job.status,'badge'));item.append(title);
      const progress=job.progress||{};
      if(progress.message || progress.file) item.append(node('p',progress.message || ('正在处理：'+progress.file)));
      if(progress.total > 0 && Number.isFinite(progress.downloaded)) {const meter=document.createElement('progress');meter.max=progress.total;meter.value=progress.downloaded;meter.setAttribute('aria-label','下载进度');item.append(meter,node('p',Math.floor(progress.downloaded/progress.total*100)+'%'));}
      if(job.error) item.append(node('p',typeof job.error==='string'?job.error:(job.error.message||'任务未完成。')));
      if(['failed','interrupted','cancelled'].includes(job.status)) {const button=node('button','继续 / 重试');button.type='button';button.addEventListener('click',()=>action('/api/retry',{job_id:job.job_id}));item.append(button);}
      holder.append(item);
    });
  }
  async function refresh() {
    if(stopped || busy) return;
    try {
      const state=await request('/api/status');
      byId('basic-state').textContent=state.basic_ready?'已就绪':'准备中';byId('basic-state').className=state.basic_ready?'ready':'';
      const registered=!!state.registration.saved, connected=!!state.mcp.last_activity;
      byId('registration-state').textContent=registered?'已保存':'尚未保存';
      byId('handshake-state').textContent=connected?'已收到 '+(state.mcp.client||'客户端')+' 握手':'等待连接';
      byId('connection-state').textContent=connected?'客户端已连接':registered?'等待原生信任':'基础功能可用';
      byId('trust-hint').hidden=!registered||connected;
      byId('register').textContent=registered?'检查并修复连接配置':'安装并接入 WorkBuddy';
      if(connected){byId('headline').textContent='可以开始整理笔记了';byId('intro').textContent='在 WorkBuddy 的 Prompt 中指定库和分类目录。检索和视频的状态分别显示在下方。';}
      const semantic=state.features.semantic, video=state.features.video;
      byId('semantic-state').textContent=semantic.ready?'已就绪':semantic.phase==='failed'?'准备失败，可重试':semantic.phase==='preparing'?'后台准备中':'尚未准备';
      byId('video-state').textContent=video.ready?(video.key_saved?'组件已就绪，Key 已保存':'组件已就绪；音频识别需要 Key'):video.phase==='failed'?'准备失败，可重试':video.phase==='preparing'?'后台准备中':'未启用';
      byId('prepare-semantic').disabled=!!semantic.ready||semantic.phase==='preparing';
      byId('prepare-video').disabled=!!video.ready||video.phase==='preparing';
      byId('key-state').textContent=video.key_saved?'Key 已保存在本机，尚未验证有效性':'尚未设置';
      byId('config-location').textContent='连接配置位置：'+state.workbuddy_config;
      displayJobs(state.jobs||[]);
    } catch(error) {message(error.message==='Failed to fetch'?'无法连接本机服务。请重新打开安装入口。':error.message,true);}
  }
  async function action(path,data) {
    busy=true;
    try {const result=await request(path,data);message(result.trust || (result.job_id?'任务已加入后台队列，可以继续使用基础功能。':'已完成。'));return result;}
    catch(error){message(error.message,true);}
    finally{busy=false;await refresh();}
  }
  byId('register').addEventListener('click',()=>action('/api/register',{}));
  byId('refresh').addEventListener('click',refresh);
  byId('prepare-semantic').addEventListener('click',()=>action('/api/prepare',{feature:'semantic'}));
  byId('prepare-video').addEventListener('click',()=>action('/api/prepare',{feature:'video'}));
  byId('key-form').addEventListener('submit',async event=>{event.preventDefault();const value=byId('api-key').value;byId('api-key').value='';await action('/api/key',{key:value});});
  byId('stop').addEventListener('click',async()=>{if(!confirm('停止本机服务？未完成的任务可在下次启动后恢复。'))return;try{await request('/api/shutdown',{});stopped=true;message('服务正在停止。需要使用时，请重新双击安装入口。');}catch(error){message(error.message,true);}});
  if(!token)message('请双击安装入口打开此页面，认证信息会在本机自动传递。',true);
  else {refresh();setInterval(refresh,3000);}
})();
