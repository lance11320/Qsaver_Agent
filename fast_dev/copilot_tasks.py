"""Grounded Co-pilot plans, deterministic selection, portable JSON bundles."""
import copy
import json
import re
import shutil
import time
import uuid
from pathlib import Path
import agent
from stem_numbering import normalize


def validate_query(node,depth=0):
    if depth>8 or not isinstance(node,dict):raise ValueError('选题条件层级或格式错误')
    op=node.get('op','OR').upper()
    if op not in ('AND','OR'):raise ValueError('只支持 AND / OR 逻辑')
    keywords=node.get('keywords',[]);clauses=node.get('clauses',[])
    if not isinstance(keywords,list) or any(not isinstance(k,str) or not k.strip() for k in keywords):raise ValueError('关键词不能为空')
    if not isinstance(clauses,list):raise ValueError('条件子项必须是数组')
    if not keywords and not clauses:raise ValueError('选题条件不能为空；请选择具体条件')
    return {'op':op,'keywords':keywords,'clauses':[validate_query(c,depth+1) for c in clauses]}


def matches(node,text):
    values=[k.casefold() in text for k in node['keywords']]+[matches(c,text) for c in node['clauses']]
    return all(values) if node['op']=='AND' else any(values)


def load_questions(path):
    path=Path(path)
    if path.suffix.lower()!='.json' or not path.is_file():raise ValueError('请选择现有题库 JSON 文件')
    if path.stat().st_size>50*1024*1024:raise ValueError('题库 JSON 超过 50 MB，请分批加载')
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    questions=data if isinstance(data,list) else data.get('questions')
    if not isinstance(questions,list) or any(not isinstance(q,dict) or not isinstance(q.get('stem'),str) for q in questions):raise ValueError('题库应为含 stem 字段的数组，或含 questions 数组的对象')
    return questions


def select(path,plan):
    questions=load_questions(path);groups=plan.get('groups') or [{'count':plan.get('count',20),'query':plan.get('query')}]
    if len(groups)>30:raise ValueError('一次最多 30 组选题条件')
    selected=[];used=set();reports=[]
    for group in groups:
        query=validate_query(group['query']);count=int(group.get('count',20))
        if not 1<=count<=500:raise ValueError('每组选题数量必须为 1–500')
        excluded=group.get('exclude_keywords',plan.get('exclude_keywords',[]))
        if not isinstance(excluded,list) or any(not isinstance(x,str) for x in excluded):raise ValueError('排除词必须为字符串数组')
        hits=[]
        for i,q in enumerate(questions):
            corpus=json.dumps({k:q.get(k) for k in ('stem','options','category_tags','remark')},ensure_ascii=False).casefold()
            if i not in used and matches(query,corpus) and not any(k.casefold() in corpus for k in excluded):hits.append(i)
        chosen=hits[:count];used.update(chosen);selected.extend(normalize(copy.deepcopy(questions[i])) for i in chosen)
        reports.append({'requested':count,'matched':len(hits),'selected':len(chosen),'shortfall':max(0,count-len(chosen)),'query':query})
    return selected,reports


def grounded_plan(raw,text,known_paths):
    if not isinstance(raw,dict):raise ValueError('模型未返回有效任务计划')
    action=raw.get('operation','reply')
    if action not in ('extract','select','clean','reply'):raise ValueError('未知任务类型')
    if action=='reply':return raw
    sources=raw.get('input_paths') or known_paths
    if not isinstance(sources,list) or not sources:raise ValueError('请提供来源文件夹或题库 JSON 路径')
    allowed={str(Path(p).resolve()).casefold() for p in known_paths}
    def grounded(p):
        normalized=str(p).replace('\\','/').casefold()
        return normalized in text.replace('\\','/').casefold() or str(Path(p).resolve()).casefold() in allowed
    if any(not isinstance(p,str) or not grounded(p) for p in sources):raise ValueError('模型给出的来源路径不在你的指令或附件中，请明确路径')
    if any(not Path(p).exists() for p in sources):raise ValueError('来源路径不存在，请检查盘符或文件名')
    output=str(raw.get('output_directory') or '').strip()
    if output and output.replace('\\','/').casefold() not in text.replace('\\','/').casefold():raise ValueError('输出位置未出现在你的指令中，请明确保存位置')
    raw=dict(raw,input_paths=sources,output_directory=output)
    if action=='clean':
        if len(sources)!=1:raise ValueError('一次清洗一份题库 JSON')
        load_questions(sources[0])
    if action=='select':
        if len(sources)!=1:raise ValueError('选题目前一次使用一份题库 JSON')
        load_questions(sources[0])
        if raw.get('selection_mode','keyword')!='semantic':
            for group in raw.get('groups') or [raw]:validate_query(group.get('query'))
    return raw


def export_bundle(questions,destination,source_json=None):
    base=Path(destination).expanduser() if destination else agent.ROOT/'exports'
    if base.suffix.lower()=='.json':
        parent=base.parent;filename=base.name
    else:parent=base;filename='questions.json'
    folder=parent/('qsaver_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]);folder.mkdir(parents=True,exist_ok=False)
    result=copy.deepcopy(questions);copies={}
    def resolve(ref):
        p=Path(str(ref).replace('\\','/'))
        candidates=[p] if p.is_absolute() else ([Path(source_json).parent/p] if source_json else [])+[agent.ROOT/p]
        found=next((x.resolve() for x in candidates if x.is_file()),None)
        if found is None:raise ValueError('题图引用不存在：'+str(ref))
        if found not in copies:
            import hashlib
            name=hashlib.sha256(found.read_bytes()).hexdigest()[:24]+found.suffix.lower();out=folder/'images'/name;out.parent.mkdir(exist_ok=True);shutil.copy2(found,out);copies[found]='images/'+name
        return copies[found]
    for q in result:
        if q.get('figure_assets') and not q.get('image'):
            from question_media import persist
            refs=persist(q,agent.ROOT,uuid.uuid4().hex);q.update(refs)
        if q.get('image'):q['image']=resolve(q['image'])
        if q.get('images'):q['images']=[resolve(x) for x in q['images']]
    out=folder/filename;agent.dump(out,result)
    return out
