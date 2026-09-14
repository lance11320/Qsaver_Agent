import thinking_policy
"""Conversation UI service. Workflow actions are explicit; credentials never leave Python."""
import asyncio
import copy
import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor
import fitz
import agent
import document_map
import figure_review as review
import copilot_tasks
import teacher_exports
import bank_versions
import review_workflow as workflow
import project_storage
import bank_cleaning
import job_progress
from stem_numbering import display_stem
import shared_api

SESSIONS={}
LOCK=threading.RLock()
WORK_LOCK=threading.Lock()
_CACHE_TRIMMED=False
POOL=ThreadPoolExecutor(max_workers=4,thread_name_prefix='qsaver-chat')
MODELS=['qwen3.8-flash','qwen3.8-max','qwen3.7-plus','qwen3-vl-plus']

def file_url(path):
    p=Path(path).resolve()
    if not p.is_relative_to(agent.ROOT.resolve()):raise ValueError('文件不在开发工作区')
    return '/gradio_api/file='+quote(str(p).replace('\\','/'),safe='/:')

def profiles():
    cfg=agent.config();items=cfg.get('api_profiles',[])
    if cfg.get('api_key'):items=items+[dict(cfg,name='默认接口')]
    return items

def public_settings(s):
    current=shared_api.sync(s)
    return {'model':s['settings']['model'],'figure_model':s['settings']['figure_model'], 'workers':s['settings']['workers'], 'profile':s['settings'].get('profile','auto'), 'base_url':s['settings'].get('base_url',''), 'has_key':bool(current['api_key']),'models':MODELS,'profiles':[{'name':p.get('name',''),'base_url':p.get('base_url') or p.get('api_base_url',''),'has_key':bool(p.get('api_key'))} for p in profiles()]}

def save_project(s):
    data=copy.deepcopy(s)
    data['settings'].pop('api_key',None)
    data['updated']=time.time()
    agent.dump(agent.ROOT/'copilot_projects'/(s['id']+'.json'),data)

def project_list():
    items=[]
    for p in (agent.ROOT/'copilot_projects').glob('*.json'):
        try:
            d=json.loads(p.read_text(encoding='utf-8'))
            items.append({'id':d['id'],'title':d.get('title','新项目'),'updated':d.get('updated',0),'archived':d.get('archived',False)})
        except (ValueError,OSError,KeyError):continue
    return sorted(items,key=lambda d:d['updated'],reverse=True)

def message(s,text,role='assistant',kind='text',**extra):
    item={'id':uuid.uuid4().hex,'role':role,'text':str(text),'kind':kind,**extra}
    with LOCK:
        s['messages'].append(item)
        if role=='user' and s.get('title','新项目')=='新项目':s['title']=str(text)[:32]
        save_project(s)
    return item

def snapshot(s):
    with LOCK:
        return {'session':s['id'],'title':s.get('title','新项目'),'projects':project_list(),'messages':copy.deepcopy(s['messages']), 'busy':s['busy'],'progress':s.get('progress',''),'work_progress':s.get('work_progress',{}), 'tokens':dict(s['tokens']), 'settings':public_settings(s),'result':s.get('result',''), 'map':s.get('map',''), 'error':s.get('error','')}

def session(sid=None):
    with LOCK:
        if sid in SESSIONS:return SESSIONS[sid]
        if isinstance(sid,str) and re.fullmatch(r'[a-f0-9]{32}',sid):
            saved=agent.ROOT/'copilot_projects'/(sid+'.json')
            if saved.exists():
                s=json.loads(saved.read_text(encoding='utf-8'));s['busy']=False;s['progress']=''
                if s['settings'].get('profile')=='custom':s['settings']['profile']='auto'
                SESSIONS[sid]=s;return s
        sid=uuid.uuid4().hex
        s={'id':sid,'title':'新项目','messages':[],'busy':False,'tokens':{'input':0,'output':0,'total':0,'calls':0},'settings':{'model':agent.DEFAULT_MODEL,'figure_model':'qwen3.8-flash','workers':2,'profile':'auto'},'result':'','map':'','paths':[]}
        SESSIONS[sid]=s
        save_project(s)
        return s

def record_usage(s,u):
    with LOCK:
        t=s['tokens'];t['input']+=u.get('prompt_tokens',u.get('input_tokens',0)) or 0;t['output']+=u.get('completion_tokens',u.get('output_tokens',0)) or 0
        t['total']+=u.get('total_tokens', (u.get('prompt_tokens',0) or 0)+(u.get('completion_tokens',0) or 0)) or 0;t['calls']+=1

def options(s):
    current=shared_api.sync(s)
    return {'usage_callback':lambda u:record_usage(s,u),'base_url':current['base_url'],'api_key':current['api_key']}


def job(s,fn):
    if s['busy']:raise ValueError('当前任务正在运行')
    # Shared extraction caches are single-writer. The selected worker count still applies inside a job.
    settings=copy.deepcopy(options(s))
    if not WORK_LOCK.acquire(blocking=False):raise ValueError('另一份文档任务正在运行，请稍后重试')
    s['busy']=True;s['error']='';s['progress']='正在准备…';s['work_progress']={}
    def work():
        token=agent.CLIENT_OPTIONS.set(settings)
        try:fn()
        except Exception as exc:
            error=str(exc)
            for secret in [p.get('api_key') for p in profiles()]+[s['settings'].get('api_key')]:
                if secret:error=error.replace(secret,'[隐藏]')
            s['error']=error;message(s,'操作未完成：'+error,kind='error')
        finally:
            agent.CLIENT_OPTIONS.reset(token)
            try:
                with LOCK:s['busy']=False;s['progress']='';save_project(s)
            finally:WORK_LOCK.release()
    POOL.submit(work)

def collect(data):
    paths=[Path(p) for p in data.get('files',[])]
    directory=str(data.get('directory','')).strip().strip('"')
    if directory:
        folder=Path(directory)
        if not folder.is_dir():raise ValueError('目录不存在')
        paths += sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.pdf','.docx','.txt','.md','.json'))
    paths=list(dict.fromkeys(p.resolve() for p in paths))
    if not paths:raise ValueError('请附加文档，或在文件夹输入框填写路径')
    if any(not p.is_file() or p.suffix.lower() not in ('.pdf','.docx','.txt','.md','.json') for p in paths):raise ValueError('仅支持现有 PDF、DOCX、TXT、MD 文件')
    return [str(p) for p in paths]

def map_summary(path,data):
    return {'path':str(path),'url':file_url(path),'documents':[{'name':Path(d['path']).name,'role':d.get('role',''),'paper_id':d.get('paper_id',''),'status':d.get('status',''),'pages':d.get('pages',0)} for d in data['documents']], 'json':json.dumps(data,ensure_ascii=False,indent=2)}

def result_message(s,path,data):
    data=copy.deepcopy(data)
    data['origin_result']=str(path)
    path=agent.ROOT/'runs'/('project_'+s['id']+'_'+uuid.uuid4().hex[:8])/'result.json'
    agent.dump(path,data)
    q=data['questions'];n=sum(workflow.pending(x) for x in q)
    s['result']=str(path)
    message(s,f"已整理 {len(q)} 道题，{n} 道题等待审核。"+('仍有提取失败项，已通过的题目可以先入库。' if data.get('partial') else '检查题目后，可随时将已通过题目入库。'),kind='review',count=n,total=len(q),path=str(path),url=file_url(path))

def resume_answers(s):
    if s['busy'] or not s.get('result') or WORK_LOCK.locked() or not shared_api.active().get('api_key'):return
    p=result_path(s);r=review.read(p)
    needs=[q for q in r['questions'] if workflow.missing(q) and not workflow.discarded(q) and not q.get('answer_recovery')]
    if not needs or not any(Path(q.get('source_file','')).is_file() for q in needs):return
    def recover():
        out=workflow.recover_answers(p,agent.Client(s['settings']['model']),progress=lambda text:job_progress.update(s,text))
        message(s,'已接续项目，并集中重查缺失答案：'+json.dumps(out,ensure_ascii=False)+'。未找到的题目暂不入库，可在全部题目中舍弃或补充。',kind='receipt')
    job(s,recover)


def result_path(s):
    if not s.get('result'):raise ValueError('请先提取或加载结果')
    p=Path(s['result']);reviewed=p.with_name('result_reviewed.json')
    if reviewed.exists():p=reviewed
    s['result']=str(p)
    return p

def card(s,data):
    p=result_path(s);result=review.read(p);qs=result['questions'];all_q=data.get('all',False)
    ids=[i for i,q in enumerate(qs) if all_q or workflow.pending(q)]
    counts={'missing_answers':sum(workflow.missing(q) and not workflow.discarded(q) for q in qs),'discarded_count':sum(workflow.discarded(q) for q in qs)}
    if not ids:return {'empty':True,'count':0,'pending':0,**counts}
    requested=data.get('index')
    if requested is None:
        requested=next((i for i in ids if qs[i].get('figure_review',{}).get('status')!='confirmed'),ids[0])
    i=int(requested)
    if i not in ids:i=ids[0]
    q=qs[i];pdf=Path(q['source_file']).suffix.lower()=='.pdf' and Path(q['source_file']).is_file()
    total_pages=0
    if pdf:
        with fitz.open(q['source_file']) as doc:total_pages=len(doc)
    images=[]
    if q.get('figure_review',{}).get('status')=='confirmed' and q.get('image'):
        images=[file_url(agent.ROOT/q['image'])]
    elif q.get('figure_assistance'):
        images=[file_url(a['preview']) for a in q['figure_assistance'] if a.get('preview') and Path(a['preview']).exists()]
    if not images:images=[file_url(agent.ROOT/a['image']) for a in q.get('figure_assets',[]) if (agent.ROOT/a['image']).exists()]
    answer_evidence=[file_url(e['raw_crop']) for e in q.get('answer_zoom_review',{}).get('evidence',[]) if e.get('raw_crop') and Path(e['raw_crop']).is_file()]
    checks=q.get('text_review',{}).get('checks',[])
    counts.update(text_checks=[{k:c.get(k) for k in ('field','status','before','after','proposal','reason','error')} for c in checks],
                  text_evidence=list(dict.fromkeys(file_url(p) for c in checks for p in c.get('raw_crops',[]) if Path(p).is_file())))
    return {'answer_evidence':answer_evidence,**counts,'index':i,'ids':ids,'position':ids.index(i)+1,'count':len(ids),'pending':sum(workflow.pending(qs[j]) for j in ids), 'answer':q.get('answer',''), 'discarded':workflow.discarded(q), 'token':review.identity(q),'number':q['number'],'stem':display_stem(q),'options':q.get('options') or [],'flags':q.get('review_flags',[]),'images':images,'regions':q.get('figures',[]),'question_regions':q.get('question_regions',[]),'page':(q.get('figures') or [{'page':(q.get('source_pages') or [1])[0]}])[0]['page'],'pages':total_pages,'file':Path(q['source_file']).name,'confirmed':q.get('figure_review',{}).get('status')=='confirmed','pdf':pdf,'text_values':{k:q.get(k,'') for k in ('stem','options','answer','explanation')}}

def page(s,data):
    qs=review.read(result_path(s))['questions'];q=qs[int(data['index'])]
    if review.identity(q)!=data['token']:raise ValueError('题目发生变化，请重新打开卡片')
    n=int(data['page'])
    with fitz.open(q['source_file']) as doc:
        if not 1<=n<=len(doc):raise ValueError('页码越界')
    out=agent.ROOT/'review_ui'/str(q['source_hash'])/f'{n:04d}.png';out.parent.mkdir(parents=True,exist_ok=True)
    if not out.exists():review.page_image(q,n).save(out)
    return {'url':file_url(out)}

def selection_cards(questions,source_json=None):
    cards=[]
    for q in questions:
        urls=[]
        for path in teacher_exports.image_paths(q,source_json):
            if not path.resolve().is_relative_to(agent.ROOT.resolve()):
                import hashlib
                target=agent.ROOT/'review_ui'/'selection_images'/(hashlib.sha256(path.read_bytes()).hexdigest()+path.suffix)
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():__import__('shutil').copy2(path,target)
                path=target
            urls.append(file_url(path))
        cards.append({'stem':display_stem(q),'options':q.get('options') or [],'answer':q.get('answer',''),'review':q.get('selection_review'),'images':urls})
    return cards

def dispatch(data):
    global _CACHE_TRIMMED
    s=session(data.get('session'));action=data.get('action','init')
    if action=='init' and not _CACHE_TRIMMED and not any(v['busy'] for v in SESSIONS.values()):
        project_storage.trim_previews();_CACHE_TRIMMED=True
    if action=='project_manage':
        target=data.get('project')
        if not isinstance(target,str) or not re.fullmatch(r'[a-f0-9]{32}',target):raise ValueError('项目编号无效')
        path=(agent.ROOT/'copilot_projects'/(target+'.json')).resolve()
        if not path.is_relative_to((agent.ROOT/'copilot_projects').resolve()) or not path.is_file():raise ValueError('项目不存在')
        target_s=session(target)
        if target_s['busy']:raise ValueError('项目正在运行，请完成后再管理')
        decision=data.get('decision')
        if decision=='delete':
            if data.get('confirmation')!=target:raise ValueError('请确认彻底删除此项目')
            with LOCK:
                path.unlink();SESSIONS.pop(target,None)
            return snapshot(session() if target==s['id'] else s)
        if decision not in ('archive','restore'):raise ValueError('项目操作无效')
        target_s['archived']=decision=='archive';save_project(target_s)
        return snapshot(s)
    if action=='versions':
        if not bank_versions.versions():
            with bank_versions.locked():bank_versions.snapshot('初始版本')
        return {'versions':bank_versions.versions(),'current':bank_versions.bank_hash(),'bank':str(agent.ROOT/'questions.json')}
    if action=='rollback':
        if s['busy']:raise ValueError('请等待当前任务完成')
        if data.get('confirmation')!=data.get('version'):raise ValueError('请确认回滚目标版本')
        result=bank_versions.rollback(data['version'],data['expected'])
        message(s,'题库已回滚。回滚前状态已自动保存，可以再次恢复。新版本：'+result['id'],kind='done')
        return snapshot(s)
    if action=='selection_review':
        if s['busy']:raise ValueError('请等待当前任务完成')
        path=s.get('selection_result')
        if data.get('path')!=path:raise ValueError('选题结果已切换，请加载当前结果')
        result=json.loads(Path(path).read_text(encoding='utf-8'));i=int(data['index'])
        q=result['questions'][i]
        if 'selection_review' not in q:raise ValueError('这不是待审核的语义选题')
        if data.get('decision') not in ('accepted','rejected'):raise ValueError('审核操作无效')
        q['selection_review'].update(status=data['decision'],reviewed_at=time.time());agent.dump(path,result)
        return {'questions':selection_cards(result['questions'],s.get('selection_source')),'path':path}
    if action=='selection_cards':
        if data.get('path')!=s.get('selection_result'):raise ValueError('请加载当前选题结果')
        result=json.loads(Path(s['selection_result']).read_text(encoding='utf-8'))
        return {'questions':selection_cards(result['questions'],s.get('selection_source')),'path':s['selection_result']}
    if action=='project_new':return snapshot(session())
    if action=='project_open':
        s=session(data['project']);resume_answers(s);return snapshot(s)
    if action=='init':
        resume_answers(s);return snapshot(s)
    if action=='poll':return snapshot(s)
    if action=='settings_get':return public_settings(s)
    if action=='settings':
        if s['busy']:raise ValueError('运行期间不能更换接口')
        v=data['settings'];profile=v.get('profile','auto')
        if profile not in ['auto','custom']+[p.get('name') for p in profiles()]:raise ValueError('接口名称无效')
        settings={'model':str(v.get('model') or agent.DEFAULT_MODEL),'figure_model':str(v.get('figure_model') or 'qwen3.8-flash'),'workers':max(1,min(4,int(v.get('workers',2)))),'profile':profile}
        if profile=='custom':
            base=str(v.get('base_url','')).strip().rstrip('/');parsed=urlparse(base)
            if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username:raise ValueError('请输入有效的 HTTP(S) API 地址')
            key=str(v.get('api_key','')).strip() or (shared_api.active()['api_key'] if base==shared_api.active()['base_url'] else '')
            if not key:raise ValueError('请填写 API Key')
            settings.update(base_url=base,api_key=key)
        chosen=settings if profile=='custom' else (shared_api.active() if profile=='auto' else next(p for p in profiles() if p.get('name')==profile))
        base=chosen.get('base_url') or chosen.get('effective_base_url') or shared_api.REGIONS.get(chosen.get('region'),shared_api.REGIONS['China / Beijing'])
        key=chosen.get('api_key','')
        if not key:raise ValueError('请填写 API Key 或选择已配置的接口')
        shared_api.save(settings['model'],base,key)
        settings.pop('api_key',None);settings['profile']='auto';s['settings']=settings;save_project(s);return snapshot(s)
    if action=='history':
        found=sorted((agent.ROOT/'runs').glob('*/result*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
        return {'items':[{'path':str(p),'label':p.parent.name+' / '+p.name} for p in found if not p.parent.name.startswith(('ui_','project_'))][:60]}
    if action=='load':
        if s['busy']:raise ValueError('请等待当前任务完成')
        p=Path(data['path']).resolve();r=review.read(p)
        result_message(s,p,r);resume_answers(s);return snapshot(s)
    if action=='card':return card(s,data)
    if action=='page':return page(s,data)
    if action=='text_review':
        if s['busy']:raise ValueError('请等待当前任务完成')
        with review.LOCK:
            p=result_path(s);q=review.read(p)['questions'][int(data['index'])]
            if review.identity(q)!=data['token']:raise ValueError('题目发生变化，请重新打开卡片')
            edited={k:data['edited'][k] for k in ('stem','options','answer','explanation')}
            out,_=agent.review_question(p,int(data['index']),edited);s['result']=str(out)
        message(s,f"第 {q['number']} 题文字复核已保存。",kind='receipt')
        return {'state':snapshot(s),'card':card(s,dict(index=data['index'],all=data.get('all',False)))}
    if action in ('review','question_decision'):
        if s['busy']:raise ValueError('请等待当前任务完成')
        index=int(data['index'])
        with review.LOCK:
            path=result_path(s);before=review.read(path);q=before['questions'][index]
            if review.identity(q)!=data['token']:raise ValueError('题目发生变化，请重新打开卡片')
            if action=='review':
                p,r=review.save_review(path,index,data['token'],data['decision'],data.get('regions',[]))
                label='已确认无图。' if data['decision']=='none' else '题图已确认。'
            else:
                decision=data['decision']
                if decision not in ('discarded','accepted','pending'):raise ValueError('未知题目审核操作')
                if decision=='accepted':
                    if workflow.missing(q):raise ValueError('本题缺少答案，请先集中重查、补充答案或舍弃')
                    if review.suspected(q) and q.get('figure_review',{}).get('status')!='confirmed':raise ValueError('请先确认题图或本题无图')
                    if '<uncertain>' in json.dumps({k:q.get(k) for k in ('stem','options','answer','explanation')}):raise ValueError('请先修正不确定的文字')
                q.setdefault('question_review_history',[]).append({'timestamp':time.time(),'previous':q.get('question_review'), 'flags':q.get('review_flags',[])})
                q['question_review']={'status':decision,'timestamp':time.time()}
                if decision=='accepted':q['review_flags']=[]
                p=str(path.with_name('result_reviewed.json'));r=before;agent.dump(p,r)
                label={'discarded':'已舍弃，不会入库。','accepted':'整题审核通过。','pending':'已恢复待审核。'}[decision]
            s['result']=p
            # Use stable original indices; the saved item may have left the pending queue.
            ids=[i for i,q in enumerate(r['questions']) if workflow.pending(q)]
            next_i=next((i for i in ids if i>index),ids[0] if ids else None)
            s['review_cursor']=next_i
            message(s,f"第 {r['questions'][index]['number']} 题："+label,kind='receipt')
        return {'state':snapshot(s),'card':card(s,dict(index=next_i,all=False))}
    if action=='cleanup':
        if any(v['busy'] for v in SESSIONS.values()):raise ValueError('请等待运行中的任务完成')
        outcome=project_storage.trim_previews()
        message(s,'已清理可重建预览缓存：'+json.dumps(outcome,ensure_ascii=False)+'。项目审核结果、来源、附图和题库版本均保留。',kind='receipt')
        return snapshot(s)
    if action=='recover_answers':
        if s['busy']:raise ValueError('请等待当前任务完成')
        def recover():
            outcome=workflow.recover_answers(result_path(s),agent.Client(s['settings']['model']),
                progress=lambda text:job_progress.update(s,text),force=True)
            message(s,'缺失答案重查完成：'+json.dumps(outcome,ensure_ascii=False)+'。仍缺答案的题目保留在全部题目中，可舍弃或以后补充。',kind='receipt')
        job(s,recover);return snapshot(s)
    if action=='execute_plan':
        if s['busy']:raise ValueError('请等待当前任务完成')
        plan=s.get('plan')
        if not plan or data.get('plan_id')!=plan.get('id'):raise ValueError('请选择当前任务计划')
        if plan.get('executed'):raise ValueError('该计划已执行，请提出新的需求')
        def execute():
            plan['executed']=True
            try:
                if plan['operation']=='clean':
                    out,report,r=bank_cleaning.apply(plan['input_paths'][0],plan['clean_rules'],plan['clean_preview']['expected'],plan.get('output_directory',''))
                    download=out
                    if not out.resolve().is_relative_to(agent.ROOT.resolve()):
                        download=agent.ROOT/'exports'/'downloads'/(uuid.uuid4().hex+'_questions.json');download.parent.mkdir(parents=True,exist_ok=True);__import__('shutil').copy2(out,download)
                    message(s,f"清洗完成：{r['before']} → {r['after']} 题，移除 {r['removed']} 题。删除记录保存在 {report}",kind='exported',format='json',output_path=str(out),url=file_url(download),report_url=file_url(report))
                elif plan['operation']=='select':
                    mode=data.get('selection_mode',plan.get('selection_mode','keyword'))
                    if mode not in ('keyword','semantic'):raise ValueError('选题方式无效')
                    if mode=='semantic':selected,reports=teacher_exports.semantic_select(plan['input_paths'][0],plan,agent.Client(s['settings']['model']),progress=lambda text:job_progress.update(s,text))
                    else:selected,reports=copilot_tasks.select(plan['input_paths'][0],plan)
                    internal=agent.ROOT/'runs'/('selection_'+uuid.uuid4().hex[:12])/'result.json'
                    agent.dump(internal,{'questions':selected,'partial':False,'selection_report':reports})
                    s['selection_source']=plan['input_paths'][0];s['selection_result']=str(internal)
                    message(s,f'已按条件选出 {len(selected)} 道题。未满足的配额会明确列出，不会补入不匹配题目。',kind='selection',reports=reports,questions=selection_cards(selected,plan['input_paths'][0]),semantic=mode=='semantic',path=str(internal))
                else:
                    paths=[]
                    for path in plan['input_paths']:
                        if Path(path).is_dir():paths.extend(p for p in collect({'directory':path}) if Path(p).suffix.lower()!='.json')
                        else:paths.append(path)
                    s['paths']=paths;s['output_directory']=plan.get('output_directory','')
                    out,r=document_map.build(paths,s['settings']['model'],s['settings']['workers'],progress=lambda text:job_progress.update(s,text));s['map']=str(out)
                    message(s,'文件关系已建立，请确认后开始提取。',kind='map',mapping=map_summary(out,r))
                save_project(s)
            except Exception:
                plan['executed']=False;raise
        job(s,execute);return snapshot(s)
    if action=='export':
        if s['busy']:raise ValueError('请等待当前任务完成')
        which=data.get('kind','result')
        source=s.get('selection_result') if which=='selection' else str(result_path(s))
        if not source:raise ValueError('暂无选题结果')
        expected=data.get('path')
        if expected and (Path(expected).resolve()!=Path(source).resolve() if which=='selection' else Path(expected).resolve().parent!=Path(source).resolve().parent):raise ValueError('该结果已不是当前任务，请使用最新结果导出')
        questions=json.loads(Path(source).read_text(encoding='utf-8'))['questions']
        if which=='selection':
            if any(q.get('selection_review',{}).get('status')=='pending' for q in questions):raise ValueError('请先逐题审核全部语义选题候选，再导出')
            questions=[q for q in questions if q.get('selection_review',{}).get('status')!='rejected']
        if not questions:raise ValueError('没有可导出的题目')
        export_format=data.get('format','docx')
        if export_format not in ('docx','json'):raise ValueError('导出格式无效')
        destination=(s.get('plan') or {}).get('output_directory') or s.get('output_directory','')
        def exporting():
            out=(teacher_exports.export_docx if export_format=='docx' else copilot_tasks.export_bundle)(questions,destination,s.get('selection_source') if which=='selection' else None)
            info={'output_path':str(out),'format':export_format}
            if out.is_relative_to(agent.ROOT):info['url']=file_url(out)
            else:
                download=agent.ROOT/'exports'/'downloads'/(uuid.uuid4().hex+'_'+out.name);download.parent.mkdir(parents=True,exist_ok=True);__import__('shutil').copy2(out,download);info['url']=file_url(download)
            message(s,('Word 练习文档' if export_format=='docx' else '题库 JSON 和附图')+'已保存至：'+str(out),kind='exported',**info)
        job(s,exporting);return snapshot(s)
    if action=='ingest':
        if s['busy']:raise ValueError('请等待当前任务完成')
        message(s,'确认将已通过检查的题目去重入库。',role='user')
        def ingest():
            outcome=agent.ingest(result_path(s),allow_partial=True);s['last_ingest']=dict(outcome,timestamp=time.time());message(s,'入库结果：'+json.dumps(outcome,ensure_ascii=False),kind='done')
        job(s,ingest);return snapshot(s)
    if action=='extract':
        if s['busy']:raise ValueError('请等待当前任务完成')
        if data.get('map_path') and str(data['map_path'])!=s['map']:raise ValueError('此清单已不是当前任务，请使用最新清单')
        if not s['map']:raise ValueError('请先建立文件关系清单')
        if data.get('map_json'):
            out,_=document_map.save_reviewed(s['map'],data['map_json']);s['map']=str(out)
        message(s,'文件关系已确认，开始提取。',role='user')
        def extract():
            out,r=agent.run(s['paths'],s['settings']['model'],2,workers=s['settings']['workers'],figure_model=s['settings']['figure_model'],document_map=s['map'],progress=lambda text:job_progress.update(s,text))
            workflow.recover_answers(out,agent.Client(s['settings']['model']),progress=lambda text:job_progress.update(s,text))
            r=json.loads(Path(out).read_text(encoding='utf-8'))
            result_message(s,out,r)
        job(s,extract);return snapshot(s)
    if action=='message':
        if s['busy']:raise ValueError('当前任务正在运行')
        text=str(data.get('text','')).strip()
        if s.get('result') and not data.get('files') and not re.search(r'清洗|去重|去除|删除',text) and re.search(r'入库|继续审核|接续|继续复核|重查.*答案|再找.*答案',text):
            message(s,text,role='user')
            if re.search(r'重查.*答案|再找.*答案',text):return dispatch({'session':s['id'],'action':'recover_answers'})
            if '入库' in text:
                if re.search(r'不要|不入库|暂不|取消',text):
                    message(s,'已保留审核进度，暂不入库。');return snapshot(s)
                return dispatch({'session':s['id'],'action':'ingest'})
            p=result_path(s);r=review.read(p)
            message(s,'已恢复已保存的审核结果，可继续审核或先将通过的题目入库。',kind='review',count=sum(workflow.pending(q) for q in r['questions']),total=len(r['questions']),path=str(p),url=file_url(p))
            return snapshot(s)
        if re.search(r'回滚|恢复.*版本|版本历史',text):
            message(s,text,role='user');message(s,'请选择需要恢复的题库版本。确认后才会回滚，当前状态会自动保存。',kind='versions');return snapshot(s)
        if not data.get('directory') and text:
            candidates=re.findall(r'"([A-Za-z]:[\\/][^"]+)"',text)+[text.strip('"')]
            for candidate in candidates:
                try:
                    if Path(candidate).is_dir():data=dict(data,directory=candidate);break
                except OSError:pass
        if not text and not data.get('files') and not data.get('directory'):raise ValueError('请填写任务或附加文档')
        paths=collect(data) if data.get('files') or data.get('directory') else []
        if data.get('files'):paths=project_storage.retain_uploads(paths,s['id'])
        message(s,text or '整理这些文档中的题目。',role='user',attachments=[Path(p).name for p in paths])
        if paths and not any(Path(p).suffix.lower()=='.json' for p in paths) and not re.search('保存|产出|输出|选题|筛选',text):
            s['paths']=paths;s['map']='';s['result']=''
            def mapping():
                out,r=document_map.build(paths,s['settings']['model'],s['settings']['workers'],progress=lambda text:job_progress.update(s,text));s['map']=str(out)
                message(s,'文件关系清单已建立。请检查题目、答案和题组的对应关系，确认后开始整批提取。',kind='map',mapping=map_summary(out,r))
            job(s,mapping)
        else:
            def respond():
                known=paths or ([s['result']] if s.get('result') else ([s['selection_source']] if s.get('selection_source') else s.get('paths',[])))
                if not known and (agent.ROOT/'questions.json').is_file():known=[str(agent.ROOT/'questions.json')]
                prompt='你是题库 Co-pilot 的任务规划器。把用户指令拆解为可执行计划，绝不声称已执行。返回 JSON：operation 为 clean（题库清洗）、extract（整理 PDF/文档）、select（根据题库 JSON 选题）或 reply（普通问答/需补充信息）；reply 为简洁中文说明；input_paths 必须逐字来自用户输入或附件；output_directory 为用户指定输出目录或 JSON 路径，没指定则空字符串。选择任务用 groups:[{count:数量,query:{op:"AND或OR",keywords:[关键词],clauses:[递归子条件]},exclude_keywords:[]}] 表达逻辑与分组配额。各5题分成两组；不要只把整段指令作为一个关键词；不能编造路径；路径未明确就 reply 询问。清洗用 clean_rules 数组选择 missing_answer（缺答案）、duplicate_stem（重复题干）、answer_conflict（答案冲突）、normalize_options（选项格式），只选择用户要求的规则，泛指清洗则全选。默认选题20题。项目当前来源可复用。用户数据：'+json.dumps({'instruction':text,'attached_or_current_paths':known,'previous_plan':s.get('plan')},ensure_ascii=False)
                raw=thinking_policy.call(agent.Client(s['settings']['model']),prompt,task='plan')
                plan=copilot_tasks.grounded_plan(raw,text,known)
                if plan.get('operation')=='reply' or not plan.get('operation'):
                    message(s,plan.get('reply','请明确来源路径、整理或选题需求。'));return
                if plan['operation']=='clean':
                    details=bank_cleaning.preview(plan['input_paths'][0],plan.get('clean_rules'))
                    plan['clean_rules']=details['rules'];plan['clean_preview']={k:v for k,v in details.items() if k not in ('questions','removed_questions')}
                plan['id']=uuid.uuid4().hex;plan['instruction']=text;s['plan']=plan
                s['title']=({'select':'选题 · ','clean':'清洗 · '}.get(plan['operation'],'整理 · '))+Path(plan['input_paths'][0]).stem[:24]
                message(s,plan.get('reply') or '我已拆解任务，请确认来源、条件和输出位置。',kind='plan',plan=plan)
            job(s,respond)
        return snapshot(s)
    raise ValueError('不支持的操作')

async def rpc(data):
    try:return await asyncio.to_thread(dispatch,data)
    except Exception as exc:
        text=str(exc)
        for p in profiles():
            if p.get('api_key'):text=text.replace(p['api_key'],'[隐藏]')
        return {'error':text}
