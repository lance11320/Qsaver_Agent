const $=s=>element.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let sid=sessionStorage.getItem('qsaver-chat-session'),state=null,files=[],seen=new Set(),deckHost=null,currentCard=null,drafts=new Map(),allQuestions=false,polling=false,deckRequest=0,showArchived=false,uploading=0,apiPromptShown=false;
const notice=text=>{$('#notice').textContent=text;$('#notice').hidden=!text;};
async function api(action,fields={}){if(action==='message'&&state){const settings=await server.rpc({session:sid,action:'settings_get'});if(!settings.has_key){state.settings=settings;openSettings();throw Error('请先配置 API Key，再发送任务。');}}const r=await server.rpc({session:sid,action,...fields});if(r.error&&!r.session)throw Error(r.error);return r;}
async function safe(fn){try{notice('');return await fn();}catch(e){notice(e.message||String(e));}}
function nearBottom(){let c=$('#conversation');return c.scrollHeight-c.scrollTop-c.clientHeight<150;}
function bottom(){const c=$('#conversation');requestAnimationFrame(()=>c.scrollTo({top:c.scrollHeight,behavior:'smooth'}));}
function formatTokens(n){return n>=1000000?(n/1000000).toFixed(2)+'m':n>=1000?(n/1000).toFixed(1)+'k':String(n);}
function apply(s){
 if(sid&&sid!==s.session){seen=new Set();$('#messages').replaceChildren();deckHost=null;currentCard=null;drafts.clear();}
 const wasBusy=state?.busy;state=s;sid=s.session;sessionStorage.setItem('qsaver-chat-session',sid);
 $('#project-title').textContent=s.title||'题库Co-pilot';
 renderProjects(s);
 const near=nearBottom();$('#welcome').hidden=s.messages.length>0;
 for(const m of s.messages){if(seen.has(m.id))continue;seen.add(m.id);renderMessage(m);}
 const reviews=[...element.querySelectorAll('.bubble.review')];reviews.slice(0,-1).forEach(n=>{n.querySelectorAll('button').forEach(b=>{b.disabled=true;b.dataset.used='true';});n.querySelector('.deck-host')?.replaceChildren();});
 $('#progress').hidden=!s.busy;const wp=s.work_progress||{};const eta=wp.eta_seconds==null?'估算中':wp.eta_seconds<60?'约 '+wp.eta_seconds+' 秒':'约 '+Math.ceil(wp.eta_seconds/60)+' 分钟';$('#progress-text').textContent=(s.progress||'正在处理…')+(wp.total?' · 本阶段剩余 '+wp.remaining_files+' / '+wp.total+' 文件 · ETA '+eta:' · ETA 估算中');
 $('#send-btn').disabled=s.busy||uploading>0;$('#settings-save').disabled=s.busy;$('#history-btn').disabled=s.busy;
 element.querySelectorAll('[data-work-action]').forEach(b=>b.disabled=s.busy||b.dataset.used==='true'||b.dataset.reviewPending==='true'||(b.dataset.map&&b.dataset.map!==s.map));
 $('#model-label').textContent=s.settings.model;
 $('#token-meter').textContent=formatTokens(s.tokens.total)+' tokens';
 $('#token-meter').title=`本次对话实际 API 用量\n输入 ${s.tokens.input.toLocaleString()} · 输出 ${s.tokens.output.toLocaleString()}\n共 ${s.tokens.calls} 次调用。历史结果与缓存读取不计入。`;
 if(near)bottom();
 if(s.busy&&!polling)poll();
 if(!s.settings.has_key&&!apiPromptShown&&element.getClientRects().length){apiPromptShown=true;openSettings();}
 if(wasBusy&&!s.busy&&deckHost)safe(()=>openDeck(deckHost));
}
async function poll(){polling=true;try{while(state?.busy){await new Promise(r=>setTimeout(r,1200));const s=await api('poll');apply(s);}}catch(e){notice('状态更新失败：'+e.message);}finally{polling=false;}}
function renderMessage(m){
 const node=document.createElement('article');node.className='bubble '+m.role+' '+m.kind;node.dataset.message=m.id;
 if(m.role==='user')node.innerHTML='<div class="bubble-body">'+esc(m.text)+(m.attachments?.length?'<div class="bubble-attachments">'+m.attachments.map(esc).join(' · ')+'</div>':'')+'</div>';
 else if(m.kind==='receipt'){
 let group=$('#messages').lastElementChild;
 if(!group?.classList.contains('receipt-group')){group=document.createElement('details');group.className='receipt-group';group.innerHTML='<summary></summary><div></div>';$('#messages').append(group);}
 const item=document.createElement('div');item.textContent='✓ '+m.text;group.querySelector('div').append(item);
 const count=group.querySelector('div').children.length;group.querySelector('summary').textContent=count+' 条处理记录 · '+m.text;return;
 }
 else node.innerHTML='<div class="assistant-label">✦ QSAVER</div><div class="bubble-text">'+esc(m.text)+'</div>';
 $('#messages').append(node);
 if(m.kind==='plan'){
 const panel=document.createElement('div');panel.className='plan-card';panel.innerHTML='<strong>'+esc(m.plan.operation==='clean'?'题库清洗计划':m.plan.operation==='select'?'选题计划':'文档整理计划')+'</strong><pre>'+esc(JSON.stringify({来源:m.plan.input_paths,输出:m.plan.output_directory||'当前项目 / exports',条件:m.plan.groups||null,清洗预览:m.plan.clean_preview||undefined},null,2))+'</pre><button class="primary" data-work-action>确认，执行计划</button>';if(m.plan.operation==='select'){const select=document.createElement('select');select.className='selection-mode';select.setAttribute('aria-label','选题方式');select.innerHTML='<option value="semantic">语义理解 · 全题库阅读，逐题审核</option><option value="keyword">关键词规则 · 快速筛选</option>';panel.insertBefore(select,panel.querySelector('button'));}
 panel.querySelector('button').onclick=()=>safe(async()=>{const r=await api('execute_plan',{plan_id:m.plan.id,selection_mode:panel.querySelector('select')?.value||'keyword'});panel.querySelector('button').dataset.used='true';apply(r);});node.append(panel);
 }
 if(m.kind==='selection'){
 const panel=document.createElement('div');panel.className='plan-card';panel.innerHTML='<details><summary>查看筛选统计</summary><pre>'+esc(JSON.stringify(m.reports,null,2))+'</pre></details>';
 if(m.semantic){const host=document.createElement('div');panel.append(host);safe(async()=>{const r=await api('selection_cards',{path:m.path});semanticDeck(host,r.questions,m.path);});}
 else{const list=document.createElement('ol');list.className='selection-preview';list.innerHTML=m.questions.map(q=>'<li>'+esc(q.stem)+'</li>').join('');panel.append(list);}
 panel.append(exportControl('selection',m.path));node.append(panel);
 }
 if(m.kind==='versions'){const host=document.createElement('div');node.append(host);safe(()=>versionsPanel(host));}
 if(m.kind==='exported'&&m.url){const link=document.createElement('a');link.className='download-link';link.href=m.url;link.textContent=m.format==='docx'?'下载 Word 文档 ↗':'下载题库 JSON ↗';link.download=m.format==='docx'?'练习题.docx':'questions.json';node.append(link);if(m.report_url){const report=document.createElement('a');report.href=m.report_url;report.textContent='查看清洗删除记录 ↗';node.append(report);}}
 if(m.kind==='map'){
  const map=document.createElement('div');map.className='map-card';map.innerHTML='<div class="map-table-wrap"><table class="map-table"><thead><tr><th>文件</th><th>类型</th><th>对应题组</th></tr></thead><tbody>'+m.mapping.documents.map(d=>'<tr><td>'+esc(d.name)+'</td><td>'+esc(({question:'题目',solution:'答案',mixed:'题目 + 答案',unknown:'待确认'})[d.role]||d.role)+'</td><td>'+esc(d.paper_id)+'<small> '+esc(d.status==='ready'?'':'待检查')+'</small></td></tr>').join('')+'</tbody></table></div><details><summary>调整文件关系与页段</summary><textarea class="map-json" aria-label="文件关系清单 JSON"></textarea></details><div class="action-row"><button class="primary" data-work-action>确认关系，开始提取</button><a download href="'+esc(m.mapping.url)+'">下载清单 ↗</a></div>';
  map.querySelector('textarea').value=m.mapping.json;map.querySelector('button').dataset.map=m.mapping.path;
  map.querySelector('button').onclick=()=>safe(async()=>{const s=await api('extract',{map_path:m.mapping.path,map_json:map.querySelector('textarea').value});map.querySelector('button').dataset.used='true';apply(s);});node.append(map);
 }
 if(m.kind==='review'){
  const actions=document.createElement('div');actions.className='action-row';actions.innerHTML='<button class="primary">继续逐题审核</button><button data-work-action>确认入库已通过题目</button><a download href="'+esc(m.url)+'">下载完整结果 ↗</a>';
  const host=document.createElement('div');host.className='deck-host';actions.append(exportControl('result',m.path));node.append(actions,host);
  actions.children[0].onclick=()=>safe(()=>openDeck(host));
  actions.children[1].onclick=()=>safe(async()=>apply(await api('ingest')));
  const retry=document.createElement('button');retry.textContent='集中重查缺失答案';retry.dataset.workAction='true';retry.onclick=()=>safe(async()=>apply(await api('recover_answers')));actions.append(retry);
  const clean=document.createElement('button');clean.textContent='清理预览缓存';clean.onclick=()=>safe(async()=>apply(await api('cleanup')));actions.append(clean);
  if(m.count>0) safe(()=>openDeck(host));
 }
}
async function openDeck(host,index=null){
 if(deckHost&&deckHost!==host)deckHost.replaceChildren();deckHost=host;const request=++deckRequest;
 const c=await api('card',{index,all:allQuestions});if(deckHost===host&&request===deckRequest)renderCard(c);
}
function renderTextAudit(c){
 if(!c.text_checks?.length)return '';
 const rows=c.text_checks.map(x=>{const m=/options\[(\d+)\]/.exec(x.field||'');const label=m?'选项 '+String.fromCharCode(65+Number(m[1])):'题干';return '<p><strong>'+esc(label)+' · '+esc({corrected:'已按原图修正',unchanged:'原文复读一致',unresolved:'需要确认'}[x.status]||'待检查')+'</strong></p>'+(x.before?'<p>原识别：'+esc(x.before)+'</p>':'')+((x.after||x.proposal)?'<p>局部复读：'+esc(x.after||x.proposal)+'</p>':'');}).join('');
 return '<details><summary>正文局部复核记录与原图</summary>'+rows+'<div class="candidate-images">'+(c.text_evidence||[]).map(url=>'<img src="'+esc(url)+'" alt="正文局部复读证据">').join('')+'</div></details>';
}
function renderCard(c){
 currentCard=c;if(!deckHost)return;
 if(c.empty){deckHost.innerHTML='<div class="empty-image">当前队列已完成。已通过题目可入库。缺答案 '+(c.missing_answers||0)+' 题，已舍弃 '+(c.discarded_count||0)+' 题，可在全部题目中查看。<button id="show-all-empty">查看全部题目</button></div>';deckHost.querySelector('button').onclick=()=>safe(async()=>{allQuestions=true;await openDeck(deckHost);});return;}
 const draft=drafts.get(c.index);let regions=structuredClone(draft?.regions||c.regions),dirty=!!draft?.dirty;
 const imageHTML=c.images.length?c.images.map(url=>'<img src="'+esc(url)+'" alt="第 '+esc(c.number)+' 题候选附图">').join(''):'<div class="empty-image">尚未获得独立题图。请打开来源页补充框选，或确认本题无图。</div>';
 deckHost.innerHTML='<div class="review-deck"><section class="review-card"><header class="review-top"><div><strong>第 '+esc(c.number)+' 题 '+(c.confirmed?'✓ 已确认':'')+'</strong><small>'+esc(c.file)+'</small></div><div class="review-nav"><button id="card-prev" aria-label="上一张题图">‹</button><span>'+c.position+' / '+c.count+'</span><button id="card-next" aria-label="下一张题图">›</button></div></header><div class="review-body"><div class="question-stem">'+esc(c.stem)+'</div><div class="question-options">'+c.options.map(esc).join('\n')+'</div><p class="answer-summary">答案：'+esc(c.answer||'暂未找到，等待重查或补充；不会入库')+(c.discarded?' · 已舍弃':'')+'</p><div class="candidate-images">'+imageHTML+'</div><div class="review-flags">'+esc(c.flags.join(' · '))+'</div>'+(c.answer_evidence?.length?'<details><summary>查看答案行放大证据</summary><div class="candidate-images">'+c.answer_evidence.map(url=>'<img src="'+esc(url)+'" alt="印刷答案行放大图">').join('')+'</div></details>':'')+renderTextAudit(c)+'<details><summary>核对题干、答案与解析</summary><textarea class="text-json" aria-label="题目文字复核 JSON"></textarea><button id="text-save">保存文字复核</button></details><div id="crop-editor" hidden><p class="crop-help">在原页拖出矩形框选题图。蓝框是整题的大致区域，红框是要保存的附图。可放大、跨页添加多个框；注意保留图例、坐标轴和所有面板。</p><div class="crop-toolbar"><label>来源页 <select id="crop-page">'+Array.from({length:c.pages},(_,i)=>'<option value="'+(i+1)+'">'+(i+1)+' / '+c.pages+'</option>').join('')+'</select></label><button id="crop-clear">清空，重新框选</button><button id="crop-undo">撤销一框</button><label>缩放<input id="crop-zoom" type="range" min="100" max="220" step="20" value="100"></label><span id="crop-count"></span></div><div class="canvas-scroll"><canvas id="crop-canvas" aria-label="拖动框选题图" tabindex="0"></canvas></div><div class="crop-thumbs" id="crop-thumbs"></div></div></div><footer class="review-bottom"><button id="crop-open">重新框选</button><button id="card-none">本题无图</button><button id="card-discard">'+(c.discarded?'恢复此题':'舍弃此题')+'</button><button id="card-accept">整题审核通过</button><button id="card-confirm" class="primary">'+(dirty?'保存裁图并下一张':'确认题图并下一张')+'</button></footer></section></div><div class="review-counter"><span>还剩 '+c.pending+' 题待确认 · 缺答案 '+(c.missing_answers||0)+' 题 · 已舍弃 '+(c.discarded_count||0)+' 题</span><label><input id="card-all" type="checkbox" '+(allQuestions?'checked':'')+'>显示全部题目</label></div>';
 const q=s=>deckHost.querySelector(s);
 for(const [selector,decision] of [['#card-discard',c.discarded?'pending':'discarded'],['#card-accept','accepted']])q(selector).onclick=()=>safe(async()=>{const r=await api('question_decision',{index:c.index,token:c.token,decision});drafts.delete(c.index);allQuestions=false;apply(r.state);renderCard(r.card);});
 q('.text-json').value=JSON.stringify(c.text_values,null,2);
 q('#text-save').onclick=()=>safe(async()=>{const r=await api('text_review',{index:c.index,token:c.token,edited:JSON.parse(q('.text-json').value),all:allQuestions});apply(r.state);renderCard(r.card);});
 let page=c.page,sourceImage=null,start=null,temp=null,requestId=0;
 q('#card-all').onchange=()=>safe(async()=>{allQuestions=q('#card-all').checked;await openDeck(deckHost);});
 const keepDraft=()=>{drafts.set(c.index,{regions:structuredClone(regions),dirty});q('#card-confirm').textContent=dirty?'保存裁图并下一张':'确认题图并下一张';q('#card-confirm').disabled=dirty?!regions.length:!c.images.length;};keepDraft();
 async function move(delta){const next=c.ids[(c.position-1+delta+c.count)%c.count];await openDeck(deckHost,next);}
 q('#card-prev').onclick=()=>safe(()=>move(-1));q('#card-next').onclick=()=>safe(()=>move(1));
 q('#card-confirm').onclick=()=>safe(async()=>{
   q('#card-confirm').disabled=true;
   try{const r=await api('review',{index:c.index,token:c.token,decision:dirty?'replace':'confirm',regions,all:allQuestions});drafts.delete(c.index);allQuestions=false;apply(r.state);renderCard(r.card);}finally{if(currentCard?.index===c.index&&deckHost.querySelector('#card-confirm'))keepDraft();}
 });
 q('#card-none').onclick=()=>safe(async()=>{const r=await api('review',{index:c.index,token:c.token,decision:'none',all:allQuestions});drafts.delete(c.index);allQuestions=false;apply(r.state);renderCard(r.card);});
 if(!c.pdf){q('#crop-open').disabled=true;q('#card-confirm').disabled=true;}
 const canvas=q('#crop-canvas'),ctx=canvas.getContext('2d');
 function draw(){if(!sourceImage)return;canvas.width=sourceImage.naturalWidth;canvas.height=sourceImage.naturalHeight;ctx.drawImage(sourceImage,0,0);ctx.lineWidth=Math.max(2,canvas.width/450);
  for(const r of [...c.question_regions.map(r=>({...r,color:'#5d8cd0'})),...regions.map(r=>({...r,color:'#d56e60'})),...(temp?[{page,bbox:temp,color:'#d56e60'}]:[])]){if(Number(r.page)!==Number(page))continue;const [x,y,x2,y2]=r.bbox;ctx.strokeStyle=r.color;ctx.strokeRect(x/1000*canvas.width,y/1000*canvas.height,(x2-x)/1000*canvas.width,(y2-y)/1000*canvas.height);}
  q('#crop-count').textContent=regions.length+' 个框'+(dirty?' · 未保存':'');
 }
 function thumbs(){q('#crop-thumbs').replaceChildren();if(!sourceImage)return;for(const r of regions.filter(r=>Number(r.page)===Number(page))){const [x,y,x2,y2]=r.bbox;const out=document.createElement('canvas');out.width=Math.max(1,Math.round((x2-x)/1000*sourceImage.naturalWidth));out.height=Math.max(1,Math.round((y2-y)/1000*sourceImage.naturalHeight));out.getContext('2d').drawImage(sourceImage,x/1000*sourceImage.naturalWidth,y/1000*sourceImage.naturalHeight,out.width,out.height,0,0,out.width,out.height);const im=new Image();im.alt='当前页新裁图预览';im.src=out.toDataURL('image/png');q('#crop-thumbs').append(im);}}
 async function loadPage(){const rid=++requestId;sourceImage=null;ctx.clearRect(0,0,canvas.width,canvas.height);q('#crop-count').textContent='正在加载来源页…';const r=await api('page',{index:c.index,token:c.token,page});const im=new Image();im.onload=()=>{if(rid!==requestId||currentCard?.index!==c.index||currentCard?.token!==c.token)return;sourceImage=im;draw();thumbs();};im.onerror=()=>notice('来源页加载失败');im.src=r.url;}
 q('#crop-page').value=String(page);q('#crop-page').onchange=()=>safe(async()=>{page=Number(q('#crop-page').value);start=null;temp=null;await loadPage();});
 q('#crop-open').onclick=()=>safe(async()=>{q('#crop-editor').hidden=!q('#crop-editor').hidden;if(!q('#crop-editor').hidden){await loadPage();q('#crop-editor').scrollIntoView({behavior:'smooth',block:'nearest'});}});
 q('#crop-clear').onclick=()=>{regions=[];dirty=true;keepDraft();draw();thumbs();};q('#crop-undo').onclick=()=>{regions.pop();dirty=true;keepDraft();draw();thumbs();};q('#crop-zoom').oninput=()=>canvas.style.width=q('#crop-zoom').value+'%';
 const point=e=>{const b=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1000,(e.clientX-b.left)/b.width*1000)),Math.max(0,Math.min(1000,(e.clientY-b.top)/b.height*1000))];};
 canvas.onpointerdown=e=>{if(!sourceImage||e.button>0)return;start=point(e);canvas.setPointerCapture(e.pointerId);};
 canvas.onpointermove=e=>{if(!start)return;const end=point(e);temp=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];draw();};
 canvas.onpointerup=e=>{if(!start)return;const end=point(e);const b=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];start=null;temp=null;if(b[2]-b[0]>=15&&b[3]-b[1]>=15){regions.push({page:Number(page),bbox:b,caption:'人工框选'});dirty=true;keepDraft();notice('');}else notice('裁框太小，请拖出完整题图区域。');draw();thumbs();};
 canvas.onpointercancel=()=>{start=null;temp=null;draw();};
 if(dirty){q('#crop-editor').hidden=false;safe(loadPage);}
}
function attached(){const host=$('#attached');host.hidden=!files.length;host.innerHTML=files.map((f,i)=>'<span class="attachment">▤ '+esc(f.name)+' <button data-remove="'+i+'" aria-label="移除 '+esc(f.name)+'">×</button></span>').join('');host.querySelectorAll('button').forEach(b=>b.onclick=()=>{files.splice(Number(b.dataset.remove),1);attached();});}
$('#attach-btn').onclick=()=>$('#file-input').click();
async function addFiles(incoming){
 uploading++;$('#send-btn').disabled=true;
 try{for(const file of incoming){if(!/\.(pdf|docx|txt|md|json)$/i.test(file.name)){notice('不支持 '+file.name+'，请添加 PDF、DOCX、TXT、MD 或 JSON 文件。');continue;}
 const key=file.name+':'+file.size+':'+file.lastModified;if(files.some(f=>f.key===key))continue;
 const result=await upload(file);files.push({name:file.name,path:result.path,key});attached();}}
 finally{uploading--;$('#send-btn').disabled=state?.busy||uploading>0;}
}
$('#file-input').onchange=()=>safe(async()=>{await addFiles([...$('#file-input').files]);$('#file-input').value='';});
let dragDepth=0;
const app=$('.chat-app');
app.addEventListener('dragenter',e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();dragDepth++;$('.drop-overlay').hidden=false;}});
app.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
app.addEventListener('dragleave',e=>{if(--dragDepth<=0){dragDepth=0;$('.drop-overlay').hidden=true;}});
app.addEventListener('drop',e=>{e.preventDefault();dragDepth=0;$('.drop-overlay').hidden=true;const incoming=[...e.dataTransfer.files];if(!incoming.length){notice('请拖入文件；目录请使用文件夹按钮。');return;}safe(()=>addFiles(incoming));});
$('#folder-btn').onclick=()=>{$('#folder-row').hidden=!$('#folder-row').hidden;if(!$('#folder-row').hidden)$('#folder-input').focus();};$('#folder-close').onclick=()=>{$('#folder-input').value='';$('#folder-row').hidden=true;};
async function send(){if(uploading){notice('文件仍在上传，请稍候。');return;}const text=$('#chat-input').value.trim();const directory=$('#folder-input').value.trim();if(!text&&!files.length&&!directory)return;$('#send-btn').disabled=true;try{const s=await api('message',{text,directory,files:files.map(f=>f.path)});$('#chat-input').value='';$('#folder-input').value='';$('#folder-row').hidden=true;files=[];attached();apply(s);bottom();}finally{$('#send-btn').disabled=state?.busy;}}
$('#send-btn').onclick=()=>safe(send);$('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!state?.busy)safe(send);}};
$('[data-suggest]').onclick=()=>{$('#chat-input').value=$('[data-suggest]').dataset.suggest;$('#folder-row').hidden=false;$('#folder-input').focus();};
async function history(){const r=await api('history');$('#history-list').replaceChildren();for(const h of r.items){const b=document.createElement('button');b.textContent=h.label;b.onclick=()=>safe(async()=>{const s=await api('load',{path:h.path});$('#history-dialog').close();apply(s);bottom();});$('#history-list').append(b);}if(!r.items.length)$('#history-list').textContent='暂无完整提取结果';$('#history-dialog').showModal();}
$('#history-btn').onclick=()=>safe(history);$('#select-suggest').onclick=()=>{$('#chat-input').value='请从我上传的题库 JSON 中选择 10 道遗传学题，排除植物相关内容。';$('#chat-input').focus();};$('#history-close').onclick=()=>$('#history-dialog').close();
function fillSettings(){const v=state.settings;$('#profile-select').innerHTML='<option value="auto">自动选择已保存接口</option>'+v.profiles.map(p=>'<option value="'+esc(p.name)+'">'+esc(p.name)+(p.has_key?' · 已配置':' · 缺少密钥')+'</option>').join('')+'<option value="custom">自定义接口…</option>';$('#profile-select').value=v.profile;$('#custom-api').hidden=v.profile!=='custom';$('#api-base').value=v.base_url||'';$('#api-key').value='';$('#model-input').value=v.model;$('#figure-model-input').value=v.figure_model;$('#workers-input').value=String(v.workers);$('#model-options').innerHTML=v.models.map(m=>'<option value="'+esc(m)+'">').join('');}
function openSettings(){fillSettings();const dialog=$('#settings');dialog.hidden=false;if(!state.settings.has_key){$('#profile-select').value='custom';$('#custom-api').hidden=false;$('#api-key').placeholder='请先填写 API Key';}if(!dialog.open)dialog.showModal();$('#model-btn').setAttribute('aria-expanded','true');}
function closeSettings(){$('#settings').close();$('#settings').hidden=true;$('#model-btn').setAttribute('aria-expanded','false');}
async function refreshSettings(){if(!state||state.busy)return;state.settings=await api('settings_get');$('#model-label').textContent=state.settings.model;if(!state.settings.has_key&&!apiPromptShown&&element.getClientRects().length){apiPromptShown=true;openSettings();}}
$('#model-btn').onclick=()=>safe(async()=>{await refreshSettings();openSettings();});$('#settings-close').onclick=closeSettings;$('#settings').addEventListener('cancel',()=>{$('#settings').hidden=true;});$('#profile-select').onchange=()=>$('#custom-api').hidden=$('#profile-select').value!=='custom';
const settingsRefresh=setInterval(()=>{if(!element.isConnected){clearInterval(settingsRefresh);return;}if(element.getClientRects().length&&!$('#settings').open)safe(refreshSettings);},4000);
$('#settings-save').onclick=()=>safe(async()=>{const s=await api('settings',{settings:{profile:$('#profile-select').value,model:$('#model-input').value,figure_model:$('#figure-model-input').value,workers:$('#workers-input').value,base_url:$('#api-base').value,api_key:$('#api-key').value}});$('#api-key').value='';closeSettings();apply(s);});
$('#versions-btn').onclick=()=>safe(async()=>{const node=document.createElement('article');node.className='bubble assistant';$('#welcome').hidden=true;$('#messages').append(node);await versionsPanel(node);bottom();});
$('#show-archived').onchange=()=>{showArchived=$('#show-archived').checked;renderProjects(state);};
$('#project-new').onclick=()=>safe(async()=>apply(await api('project_new')));
$('#project-toggle').onclick=()=>{const app=$('.chat-app');if(innerWidth>1300)app.classList.toggle('projects-hidden');else{app.classList.remove('projects-hidden');app.classList.toggle('projects-open');}};
safe(async()=>apply(await api('init')));

function exportControl(kind,path){
 const wrap=document.createElement('div');wrap.className='export-control';
 wrap.innerHTML='<button class="primary" data-work-action data-export-go>导出 Word 文档</button><select aria-label="导出格式"><option value="docx">Word 文档 .docx</option><option value="json">题库数据 .json</option></select>';
 const select=wrap.querySelector('select'),button=wrap.querySelector('button');
 select.onchange=()=>button.textContent=select.value==='docx'?'导出 Word 文档':'导出题库 JSON';
 button.onclick=()=>safe(async()=>apply(await api('export',{kind,path,format:select.value})));
 return wrap;
}
function semanticDeck(host,questions,path,index=0){
 const pending=questions.filter(q=>q.review?.status==='pending').length;
 const exports=host.closest('.plan-card')?.querySelectorAll('[data-export-go]')||[];
 exports.forEach(b=>{b.dataset.reviewPending=String(pending>0||!questions.some(q=>q.review?.status==='accepted'));b.disabled=b.dataset.reviewPending==='true';});
 if(!questions.length){host.innerHTML='<p>没有语义候选题，可以修改需求后再试。</p>';return;}
 const q=questions[index];
 host.innerHTML='<div class="review-deck"><section class="review-card"><div class="review-top"><strong>语义选题审核 '+(index+1)+' / '+questions.length+'</strong><div class="review-nav"><button data-prev aria-label="上一道候选题">‹</button><button data-next aria-label="下一道候选题">›</button></div></div><div class="review-body"><div class="review-flags">原题库第 '+(q.review.source_index+1)+' 题 · '+esc({pending:'待审核',accepted:'已保留',rejected:'已排除'}[q.review.status])+'</div><p class="recommendation">推荐理由：'+esc(q.review.reason)+'</p><div class="question-stem">'+esc(q.stem)+'</div><div class="question-options">'+q.options.map(esc).join('\n')+'</div><div class="candidate-images">'+q.images.map(url=>'<img src="'+esc(url)+'" alt="候选题附图">').join('')+'</div><details><summary>参考答案</summary>'+esc(q.answer)+'</details></div><footer class="review-bottom"><button data-reject>不符合，排除</button><button class="primary" data-accept>符合，保留并下一题</button></footer></section></div><p class="review-counter">还剩 '+pending+' 题待审核；全部审核后才能导出。</p>';
 host.querySelector('[data-prev]').onclick=()=>semanticDeck(host,questions,path,(index-1+questions.length)%questions.length);
 host.querySelector('[data-next]').onclick=()=>semanticDeck(host,questions,path,(index+1)%questions.length);
 for(const [selector,decision] of [['[data-accept]','accepted'],['[data-reject]','rejected']])host.querySelector(selector).onclick=()=>safe(async()=>{
 host.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{const r=await api('selection_review',{path,index,decision});const order=[...r.questions.keys()].slice(index+1).concat([...r.questions.keys()].slice(0,index+1));const next=order.find(i=>r.questions[i].review.status==='pending');semanticDeck(host,r.questions,path,next??index);}
 catch(e){semanticDeck(host,questions,path,index);throw e;}
 });
}
function renderProjects(s){
 const list=$('#project-list');list.innerHTML=(s.projects||[]).filter(p=>showArchived||!p.archived).map(p=>'<div class="project-item"><button class="project-name '+(p.id===sid?'active':'')+'" data-project="'+esc(p.id)+'" title="'+esc(p.title)+'">'+esc(p.title)+'</button><details class="project-menu"><summary aria-label="项目菜单">⋯</summary><div><button data-manage="'+esc(p.id)+'" data-decision="'+(p.archived?'restore':'archive')+'">'+(p.archived?'取消归档':'归档项目')+'</button><button data-delete="'+esc(p.id)+'">彻底删除</button></div></details></div>').join('');
 list.querySelectorAll('[data-project]').forEach(b=>b.onclick=()=>safe(async()=>apply(await api('project_open',{project:b.dataset.project}))));
 list.querySelectorAll('[data-manage]').forEach(b=>b.onclick=()=>safe(async()=>apply(await api('project_manage',{project:b.dataset.manage,decision:b.dataset.decision}))));
 list.querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>{const project=s.projects.find(p=>p.id===b.dataset.delete);const dialog=$('#project-dialog');dialog.innerHTML='<h3>彻底删除项目</h3><p>删除“'+esc(project.title)+'”的对话与项目记录，此操作不可撤销。已导出的文件、题库及题库版本不会删除。</p><div class="action-row"><button data-cancel>取消</button><button class="danger" data-confirm-delete>确认彻底删除</button></div>';dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();dialog.querySelector('[data-confirm-delete]').onclick=()=>safe(async()=>{apply(await api('project_manage',{project:project.id,decision:'delete',confirmation:project.id}));dialog.close();});dialog.showModal();});
}
async function versionsPanel(host){
 const r=await api('versions');host.className='plan-card';host.innerHTML='<h3>题库版本与回滚</h3><p>管理题库：'+esc(r.bank)+'。选择历史版本后确认恢复；导入的外部 JSON 不会改变。</p><select aria-label="题库历史版本">'+r.versions.map(v=>'<option value="'+esc(v.id)+'">'+esc(new Date(v.created*1000).toLocaleString()+' · '+v.label+' · '+v.count+'题')+'</option>').join('')+'</select><p class="version-confirm" hidden></p><button>预览回滚</button>';
 const select=host.querySelector('select'),button=host.querySelector('button'),note=host.querySelector('p.version-confirm');let chosen=null;const previous=r.versions.find(v=>v.sha256!==r.current);if(previous)select.value=previous.id;
 select.onchange=()=>{chosen=null;note.hidden=true;button.textContent='预览回滚';};
 button.onclick=()=>safe(async()=>{if(!chosen){chosen=select.value;const v=r.versions.find(v=>v.id===chosen);note.textContent='将把当前题库恢复为 '+v.count+' 道题，版本 '+v.id+'。当前状态会先保存为新版本。';note.hidden=false;button.textContent='确认回滚到此版本';return;}
 button.disabled=true;try{apply(await api('rollback',{version:chosen,expected:r.current,confirmation:chosen}));await versionsPanel(host);}finally{button.disabled=false;}});
}
