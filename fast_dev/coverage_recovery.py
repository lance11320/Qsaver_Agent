"""Bounded rereading of missing or duplicate numbers in continuous-numbered papers."""
import json
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

def repair(items,docs,client,work,progress=print):
    import agent,thinking_policy
    tasks=[]
    for doc in docs:
        plan=doc.get('plan',{});last=plan.get('last_question_number')
        if plan.get('continuous_numbering') is not True or type(last) is not int or not 0<last<=2000:continue
        role=plan.get('role');kind={'questions':'question','solutions':'solution'}.get(role)
        if not kind:continue
        rows=[q for q in items if q.get('kind')==kind and q['source_file']==doc['file']]
        counts=Counter(str(q['number']).strip().rstrip('.、') for q in rows)
        targets=[str(n) for n in range(1,last+1) if counts[str(n)]!=1]
        if not rows or len(targets)>20:continue
        for number in targets:
            matching=[q for q in rows if str(q['number']).strip().rstrip('.、')==number]
            near=matching or sorted(rows,key=lambda q:abs(int(q['number'])-int(number)) if str(q['number']).isdigit() else 99999)[:2]
            pages=[p for q in near for p in q.get('source_pages',[])]
            if not pages:continue
            if not matching:
                lower=[q for q in rows if str(q['number']).isdigit() and int(q['number'])<int(number)]
                upper=[q for q in rows if str(q['number']).isdigit() and int(q['number'])>int(number)]
                if lower and upper:
                    lo=max(lower,key=lambda q:int(q['number']));hi=min(upper,key=lambda q:int(q['number']))
                    pages=[max(lo['source_pages']),min(hi['source_pages'])]
            pages=list(range(max(1,min(pages)),min(doc['total_pages'],max(pages))+1))
            if len(pages)>6:continue
            tasks.append((doc,rows[0]['source_hash'],kind,number,pages))
    def execute(task):
        doc,sha,kind,number,pages=task
        folder=Path(work)/'coverage_v2'/sha[:12]
        cache=folder/f'{kind}_{number}.json'
        try:
            units=agent.prepare(doc['file'],Path(work)/sha[:16]/'pages',pages)
            prompt=agent.prompt_for(units,pages)+'\n文件角色：'+json.dumps(doc['plan'],ensure_ascii=False)+f'\n本次只补提取 kind={kind}、number={number} 的唯一完整记录。按原图印刷题号定位，未找到不得编造。完整包含跨页题干、所有选项和共享材料；不把续页单独当成新题。输出 '+ '{"items": [对应记录]} 格式。'
            if cache.exists():obj=json.loads(cache.read_text(encoding='utf-8'))
            else:
                obj=thinking_policy.call(client,prompt,[(f'物理页 {u["page"]}',im) for u in units for im in u['images']],task='cross_page')
                agent.dump(folder/f'raw_{kind}_{number}.json',obj)
            obj=agent.extraction_object(obj);agent.validate(obj,pages,pages)
            found=[q for q in obj['items'] if q.get('kind')==kind and str(q.get('number')).strip().rstrip('.、')==number]
            if len(found)!=1 or len(obj['items'])!=1 or not found[0].get('complete'):raise ValueError('Recovery did not return one complete requested item')
            q=found[0];q.update(number=number,source_file=doc['file'],source_hash=sha,group=doc['group'])
            q['page_images']=[im for u in units if u['page'] in q['source_pages'] for im in u['images']]
            q['coverage_recovery']={'method':'targeted_source_reread','requested_pages':pages}
            agent.dump(cache,obj)
            return task,q,None
        except Exception as e:return task,None,type(e).__name__
    report=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for (doc,sha,kind,number,pages),q,error in pool.map(execute,tasks):
            record={'file':doc['file'],'kind':kind,'number':number,'recovered':q is not None,'error':error};report.append(record)
            if q:
                items=[old for old in items if not (old['source_file']==doc['file'] and old['kind']==kind and str(old['number']).strip().rstrip('.、')==number)]
                items.append(q)
            progress(f'覆盖补提取：{Path(doc["file"]).name} 第 {number} 题 '+('完成' if q else '待复核'))
    agent.dump(Path(work)/'coverage_v2/report.json',report)
    return items,report
