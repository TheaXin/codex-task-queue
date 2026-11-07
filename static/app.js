'use strict';
const $ = id => document.getElementById(id);
const labels = {draft:'灵感',queued:'待执行', waiting_quota:'等待额度恢复', sending:'正在投递', running:'执行中', delivered:'执行完成', reviewed:'已核对', review:'需要核对', cancelled:'已取消', completed:'已完成', failed:'执行失败'};
let threads = [], selected = '', sending = false, online = false;
const draftKey = 'codex-queue-draft-v1';
let draft = {};
try { draft = JSON.parse(sessionStorage.getItem(draftKey) || '{}') || {}; } catch {}
selected = draft.thread_id || '';
let editingDraft = draft.editingDraft || null;
$('mode').value = draft.mode || 'queue';
$('prompt').value = draft.prompt || '';
$('when').value = draft.when || 'now';
$('schedule').value = draft.schedule || '';
function persist() {
  const values = {editingDraft, mode:$('mode').value, thread_id:selected,prompt:$('prompt').value,when:$('when').value,schedule:$('schedule').value};
  if (Object.entries(values).some(([key,value]) => draft[key] !== value)) draft = values;
  try { sessionStorage.setItem(draftKey,JSON.stringify(draft)); } catch {}
}
function update() {
  const note = $('mode').value === 'draft';
  $('mode-queue').setAttribute('aria-pressed', String(!note));
  $('mode-draft').setAttribute('aria-pressed', String(note));
  $('target-fields').hidden = note;
  $('timing-fields').hidden = note;
  $('thread').required = !note;
  $('submit').textContent = note ? '保存灵感' : '加入队列';
  $('schedule').hidden = note || $('when').value !== 'later';
  $('schedule').required = !$('schedule').hidden;
  const thread = threads.find(t => t.id === selected);
  $('identity').textContent = thread ? [thread.cwd, thread.id].filter(Boolean).join('\n') : '';
  $('submit').disabled = sending || !online || (!note && !thread) || !$('prompt').value.trim();
}
function renderOptions() {
  const search = $('search').value.toLowerCase();
  const options = threads.filter(t => t.id === selected || [t.title,t.cwd,t.id].join(' ').toLowerCase().includes(search));
  $('thread').replaceChildren(new Option('请选择已有会话',''),...options.map(t=>new Option((t.title || '未命名会话')+' · '+t.id.slice(-8),t.id)));
  $('thread').value = selected;
  update();
}
function element(tag,text,cls) {
  const el = document.createElement(tag);
  el.textContent = text;
  if(cls) el.className = cls;
  return el;
}
async function api(url,data) {
  const response = await fetch(url,data ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)} : {cache:'no-store'});
  const result = await response.json();
  if(!response.ok) throw Error(result.error || '服务暂时不可用');
  return result;
}
let currentJobs = [];
let activeFilter = 'all';
let selectedJob = null;
let detailKey;
const pendingActions = new Set();
const statusGroups = {
  draft: ['draft'],
  waiting: ['queued', 'waiting_quota'],
  running: ['sending', 'running'],
  attention: ['review', 'failed'],
  history: ['delivered', 'completed', 'reviewed', 'cancelled']
};

function badgeFor(job) {
  const badge = element('span', labels[job.status] || job.status, 'badge');
  badge.dataset.status = job.status;
  return badge;
}

function dueTime(job, compact = false) {
  if (job.status === 'draft') return '—';
  const date = new Date(job.due * 1000);
  return date.toLocaleString('zh-CN', compact ?
    {month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit'} : {});
}

function showCompose(open) {
  $('compose').hidden = !open;
  $('compose').closest('.workspace').classList.toggle('is-composing', open);
  $('detail').hidden = open;
  $('new-task').setAttribute('aria-expanded', String(open));
  $('new-task').textContent = open ? '收起表单' : '＋ 新建任务';
  if (open) {
    $('compose').scrollIntoView({block:'nearest', inline:'nearest'});
    $('mode-' + $('mode').value).focus({preventScroll:true});
  }
}

function renderDetail(job) {
  const panel = $('detail');
  const name = job && (threads.find(thread => thread.id === job.thread_id)?.title || '已有会话');
  const key = JSON.stringify([job, name, job && pendingActions.has(job.id)]);
  if (key === detailKey) return;
  detailKey = key;
  panel.replaceChildren();
  if (!job) {
    panel.append(element('p', '选择一项任务查看详情。', 'empty'));
    return;
  }
  panel.append(element('h2', job.prompt.split('\n')[0] || job.prompt), badgeFor(job));
  const fields = element('dl', '', 'task-meta');
  for (const [key, value] of [
    ['目标会话', name], ['最早执行', dueTime(job)], ['会话 ID', job.thread_id], ['任务 ID', job.id]
  ]) {
    fields.append(element('dt', key), element('dd', value));
  }
  if (job.status !== 'draft') panel.append(fields);
  panel.append(element('h3', '任务内容'), element('p', job.prompt, 'task-body'));
  if (job.detail) panel.append(element('p', job.detail, 'task-note'));
  if (job.status === 'draft') {
    const edit = element('button', '编辑灵感', 'quiet-button');
    edit.onclick = () => {
      editingDraft = job.id;
      draft = {};
      selected = '';
      $('mode').value = 'draft';
      $('prompt').value = job.prompt;
      renderOptions();
      persist();
      showCompose(true);
    };
    panel.append(edit);
  }
  if (['queued', 'waiting_quota', 'review'].includes(job.status)) {
    const review = job.status === 'review';
    const button = element('button', review ? '已检查会话，解除阻塞' : '取消任务', 'quiet-button');
    button.disabled = pendingActions.has(job.id);
    button.onclick = async () => {
      pendingActions.add(job.id);
      button.disabled = true;
      try {
        await api(review ? '/api/ack' : '/api/cancel', {id:job.id});
        await refresh();
      } catch (error) {
        $('message').textContent = error.message;
      } finally {
        pendingActions.delete(job.id);
        renderJobs(currentJobs);
      }
    };
    panel.append(button);
  }
}

function renderJobs(jobs) {
  currentJobs = jobs;
  document.querySelectorAll('[data-filter]').forEach(button => {
    const filter = button.dataset.filter;
    button.setAttribute('aria-pressed', String(filter === activeFilter));
    button.querySelector('span').textContent = filter === 'all' ? jobs.length :
      jobs.filter(job => statusGroups[filter].includes(job.status)).length;
  });
  const visible = jobs.filter(job => activeFilter === 'all' || statusGroups[activeFilter].includes(job.status));
  const focusedRow = document.activeElement?.dataset.job;
  const detail = visible.find(job => job.id === selectedJob) || visible[0];
  selectedJob = detail?.id || null;
  $('tasks').replaceChildren();
  if (!visible.length) {
    $('tasks').append(element('p', jobs.length ? '此筛选下暂无任务。' : '暂无任务，点击「新建任务」开始。', 'empty'));
  }
  for (const job of visible) {
    const row = element('button', '', 'task-row');
    row.type = 'button';
    row.dataset.job = job.id;
    row.setAttribute('aria-pressed', String(job.id === selectedJob));
    row.append(element('span', job.prompt.split('\n')[0] || job.prompt, 'task-title'),
      element('span', dueTime(job, true), 'task-time'), badgeFor(job));
    row.onclick = () => {
      selectedJob = job.id;
      showCompose(false);
      renderJobs(currentJobs);
      if (matchMedia('(max-width: 800px)').matches) $('detail').scrollIntoView({block:'nearest'});
    };
    $('tasks').append(row);
    if (job.id === focusedRow) row.focus({preventScroll:true});
  }
  renderDetail(detail);
}
$('new-task').onclick = () => showCompose($('compose').hidden);
$('close-compose').onclick = () => {
  showCompose(false);
  $('new-task').focus();
};
document.querySelectorAll('[data-filter]').forEach(button => {
  button.onclick = () => {
    activeFilter = button.dataset.filter;
    renderJobs(currentJobs);
  };
});
let refreshInFlight = null;
function refresh() {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const state = await api('/api/state');
      const threadsChanged = JSON.stringify(threads) !== JSON.stringify(state.threads);
      threads = state.threads;
      online = true;
      if (threadsChanged) renderOptions();
      else update();
      renderJobs(state.jobs);
      $('quota').textContent = state.quota || '额度状态待确认';
      $('connection').textContent = '本机已连接';
    } catch (e) {
      online = false;
      update();
      $('connection').textContent = '连接中断';
      $('quota').textContent = '暂时无法连接本机队列，恢复后将自动刷新。';
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}
$('thread').onchange=()=>{selected=$('thread').value;persist();update();};
$('search').oninput=renderOptions;
for (const mode of ['queue','draft']) {
  $('mode-' + mode).onclick = () => {
    $('mode').value = mode;
    persist();
    update();
  };
}
for(const id of ['prompt','when','schedule']) $(id).oninput=()=>{persist();update();};
$('refresh').onclick = async () => {
  const button = $('refresh');
  button.disabled = true;
  button.textContent = '刷新中…';
  try {
    await refresh();
    button.textContent = online ? '已刷新' : '刷新失败';
  } finally {
    setTimeout(() => {
      button.textContent = '↻';
      button.disabled = false;
    }, 1200);
  }
};
$('form').onsubmit=async event=>{
  event.preventDefault();
  if($('submit').disabled) return;
  persist();
  const note = $('mode').value === 'draft';
  if(!draft.id) {
    draft.id=editingDraft || crypto.randomUUID();
    draft.due=$('when').value==='later' ? Math.floor(new Date($('schedule').value).getTime()/1000) : Math.floor(Date.now()/1000);
    persist();
  }
  sending=true; update();
  const controls=['mode-queue','mode-draft','thread','search','prompt','when','schedule','new-task','close-compose'];
  controls.forEach(id=>$(id).disabled=true);
  try {
    const id = draft.id;
    if (note) await api('/api/drafts', {id, prompt:draft.prompt});
    else await api('/api/jobs', {id, thread_id:selected, prompt:draft.prompt, due:draft.due});
    $('prompt').value=''; editingDraft=null; draft={}; $('mode').value='queue'; persist();
    $('message').textContent=note ? '灵感已保存。' : '任务已加入队列。';
    activeFilter = note ? 'draft' : 'all'; selectedJob = id; showCompose(false); $('new-task').focus();
  } catch(e){$('message').textContent='未能确认入队。'+e.message+'；原样重试会使用同一个任务编号。';}
  finally{controls.forEach(id=>$(id).disabled=false);sending=false;update();await refresh();}
};
update();refresh();setInterval(()=>{if(!document.hidden)refresh();},10000);
