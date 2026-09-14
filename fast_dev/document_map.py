"""Cached, evidence-backed folder inventory and question/answer relationships."""
from __future__ import annotations
import thinking_policy
from answer_authority import ROLE_PROMPT
import hashlib
import json
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import fitz

SCHEMA_VERSION = 1
CLASSIFICATION_VERSION = 'printed-roles-v2'

def title_key(title):
    import unicodedata
    title=unicodedata.normalize('NFKC',title)
    title=re.sub(r'参考答案与解析|参考答案及解析|参考答案|答案与解析|答案及解析|答案解析|答案|解析|副本','',title)
    return re.sub(r'[\s_\-—:：,，.。()（）]+','',title)

def link_documents(documents):
    """Never match different exams solely by question count."""
    active=[d for d in documents if not d.get('duplicate_of') and d.get('status')=='ready']
    for d in active:
        d['paper_id']='paper_'+d['sha256'][:16]
        d['related_document_ids']=[]
        d['relationship_status']='self_contained' if d['role']=='mixed' else 'unpaired'
    for q in active:
        if q['role']!='questions':continue
        matches=[s for s in active if s['role']=='solutions' and
                 title_key(s['title'])==title_key(q['title']) and title_key(q['title']) and
                 s.get('last_question_number')==q.get('last_question_number') and q.get('last_question_number')]
        if len(matches)==1:
            s=matches[0]
            competing=[d for d in active if d['role']=='questions' and title_key(d['title'])==title_key(q['title'])]
            if len(competing)==1:
                s['paper_id']=q['paper_id']
                for a,b in ((q,s),(s,q)):
                    a['related_document_ids']=[b['id']]
                    a['relationship_status']='matched'
                continue
        if matches:
            q['relationship_status']='needs_review'
    return documents

def validate_map(obj):
    if not isinstance(obj,dict) or obj.get('schema_version')!=SCHEMA_VERSION or not isinstance(obj.get('documents'),list):
        raise ValueError('文件关系清单格式错误')
    ids=[d['id'] for d in obj['documents']]
    if len(set(ids))!=len(ids):raise ValueError('文档 ID 重复')
    for d in obj['documents']:
        if d.get('status')!='ready':continue
        if d.get('role') not in ('questions','solutions','mixed','unknown'):raise ValueError('文档类型错误')
        if not d.get('paper_id'):raise ValueError('缺少 paper_id')
        if any(i not in ids for i in d.get('related_document_ids',[])):raise ValueError('关系引用未知文档')
        if d.get('duplicate_of') and d['duplicate_of'] not in ids:raise ValueError('副本引用未知文档')
        for segment in d.get('segments',[]):
            if not 1<=segment['start_page']<=segment['end_page']<=d['pages']:raise ValueError('页段超出文档')
    return obj

def build(paths, model=None, workers=2, progress=print):
    from agent import ROOT, Client, digest, dump, prepare, DEFAULT_MODEL
    model=model or DEFAULT_MODEL
    client=Client(model)
    started=time.monotonic()
    paths=sorted({Path(p).resolve() for p in paths})
    records=[]
    for p in paths:
        progress('文件指纹：'+p.name)
        try:
            h=digest(p)
            records.append({'id':hashlib.sha256(str(p).encode()).hexdigest()[:16], 'path':str(p),'name':p.name,'sha256':h})
        except Exception as exc:
            records.append({'id':hashlib.sha256(str(p).encode()).hexdigest()[:16],'path':str(p),'name':p.name,'status':'error','error':str(exc)})
    import image_policy
    cache_root=ROOT/'document_cache'/hashlib.sha256((model+client.base+str(SCHEMA_VERSION)+thinking_policy.VERSION+CLASSIFICATION_VERSION+image_policy.identity(client)).encode()).hexdigest()[:16]
    seen={}
    primary=[]
    for r in records:
        if r.get('status')=='error':continue
        if r['sha256'] in seen:r['duplicate_of']=seen[r['sha256']]['id']
        else:seen[r['sha256']]=r;primary.append(r)
    def inspect(r):
        p=Path(r['path']); work=cache_root/r['sha256']
        try:
            if p.suffix.lower()!='.pdf':
                units=prepare(p,work/'pages')
                n=len(units)
            else:
                with fitz.open(p) as doc:n=len(doc)
                units=prepare(p,work/'pages', sorted({1,min(2,n),max(1,n//2),max(1,n-2),max(1,n-1),n}),render_scale=1.8)
            r['pages']=n
            plan_file=work/'classification.json'
            if plan_file.exists():plan=json.loads(plan_file.read_text(encoding='utf-8'))
            else:
                prompt=ROLE_PROMPT+'\n'+'''检查文档的抽样页，建立文件关系清单，不提取全文或解题。
只依据可见内容输出 JSON：{"title":"完整试卷标题，保留机构/期次/序号", "role":"questions/solutions/mixed/unknown",
"last_question_number":40或null,"continuous_numbering":true或false,
"sample_pages":[{"page":1,"role":"questions/solutions/mixed/blank/unknown","evidence":"短证据"}],"notes":""}。
每一张输入图片都要有 sample_pages 记录，物理页使用顶部 SOURCE_PAGE。首页宣称题数可能错误，末题号只依据真实题号。
如果样本包含试题和答案解析则 role=mixed，不能因文件名没有答案就判为纯试题。
'''+'\n'.join(f'页{u["page"]}: '+u['text'] for u in units)
                plan=thinking_policy.call(client,prompt,[(f'物理页{u["page"]}',im) for u in units for im in u['images']],task='relationship')
                if plan.get('role') not in ('questions','solutions','mixed','unknown'):raise ValueError('分类格式错误')
                if not isinstance(plan.get('sample_pages'),list):raise ValueError('缺少抽样证据')
                expected={u['page'] for u in units}
                if {x.get('page') for x in plan['sample_pages']}!=expected:raise ValueError('抽样页码不匹配')
                dump(plan_file,plan)
            r.update(plan)
            r['status']='ready'
            r['segments']=[]
            # Bracket a question -> solution transition, then inspect the gap.
            kinds={s['page']:s['role'] for s in plan['sample_pages']}
            qpages=[p for p,k in kinds.items() if k=='questions']
            apages=[p for p,k in kinds.items() if k=='solutions']
            if r['role']=='mixed' and qpages and apages and max(qpages)<min(apages) and p.suffix.lower()=='.pdf':
                lo,hi=max(qpages),min(apages)
                checks=0
                while hi-lo>1 and checks<8:
                    mid=(lo+hi)//2
                    check_file=work/f'page_role_{mid}.json'
                    if check_file.exists():v=json.loads(check_file.read_text(encoding='utf-8'))
                    else:
                        page=prepare(p,work/'pages',[mid],render_scale=1.8)[0]
                        v=client.chat(ROLE_PROMPT+'\n判断此页是题目 questions、参考答案/解析 solutions、两者 mixed、空白 blank 或 unknown。输出 JSON {"role":"","evidence":"一句话证据"}，不解题。',page['images'])
                        if isinstance(v,list) and len(v)==1 and isinstance(v[0],dict):v=v[0]
                        if v.get('role') not in ('questions','solutions','mixed','blank','unknown'):raise ValueError('页类型错误')
                        dump(check_file,v)
                    kinds[mid]=v['role'];checks+=1
                    if v['role']=='solutions':hi=mid
                    elif v['role'] in ('questions','blank'):lo=mid
                    else:break
                if hi-lo==1:
                    r['segments']=[{'role':'questions','start_page':1,'end_page':hi-1},{'role':'solutions','start_page':hi,'end_page':n}]
                    r['segment_status']='boundary_checked'
                else:r['segment_status']='needs_review'
            elif r['role'] in ('questions','solutions'):
                r['segments']=[{'role':r['role'],'start_page':1,'end_page':n}]
                r['segment_status']='sampled'
            else:r['segment_status']='needs_review'
            r['page_evidence']=[{'page':p,'role':role} for p,role in sorted(kinds.items())]
            r['classification_cache']=str(plan_file)
            progress(f"清单：{p.name}，{n}页，{r['role']}")
        except Exception as exc:
            r.update(status='error',error=str(exc).replace(client.key,'[REDACTED]'))
        progress({'stage':'文件关系清单','file':str(p),'fraction':1})
        return r
    progress({'stage':'文件关系清单','total':len(primary)})
    with ThreadPoolExecutor(max_workers=max(1,min(4,int(workers)))) as pool:
        list(pool.map(inspect,primary))
    link_documents(records)
    by_id={r['id']:r for r in records}
    for r in records:
        if r.get('duplicate_of'):
            source=by_id[r['duplicate_of']]
            for k in ('pages','role','title','paper_id','status','segments','relationship_status','last_question_number'):
                if k in source:r[k]=source[k]
    result={'schema_version':SCHEMA_VERSION,'model':model,'documents':records,
            'review_notes':['页段来自抽样与边界检查，并非逐页分类；交错编排请复核。'],
            'stats':{'files':len(records),'unique_files':len(primary),'seconds':round(time.monotonic()-started,2),
                     'new_api_calls':len(client.usage),'usage':client.usage}}
    validate_map(result)
    map_id=hashlib.sha256(json.dumps([(r['id'],r.get('sha256')) for r in records]).encode()).hexdigest()[:16]
    output=ROOT/'maps'/map_id/'document_map.json'
    # Don't overwrite a user-corrected map when rebuilding.
    if output.exists() and json.loads(output.read_text(encoding='utf-8')).get('user_reviewed'):
        output=output.with_name('document_map_generated.json')
    dump(output,result)
    dump(output.parent/f'metrics_{time.time_ns()}.json',result['stats'])
    return output,result

def save_reviewed(path,text):
    from agent import dump
    original=validate_map(json.loads(Path(path).read_text(encoding='utf-8')))
    edited=validate_map(json.loads(text))
    before={d['id']:(d['path'],d.get('sha256')) for d in original['documents']}
    after={d['id']:(d['path'],d.get('sha256')) for d in edited['documents']}
    if before!=after:raise ValueError('复核只能修改关系/分类/页段，不能修改输入文件路径与指纹')
    edited['user_reviewed']=True
    out=Path(path).with_name('document_map_reviewed.json')
    dump(out,edited)
    return out,edited

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--workers',type=int,default=2)
    a=p.parse_args()
    output,result=build([f for f in Path(a.directory).iterdir() if f.suffix.lower() in ('.pdf','.docx','.txt','.md')],workers=a.workers)
    print(json.dumps({'output':str(output),'stats':result['stats']},ensure_ascii=False))
