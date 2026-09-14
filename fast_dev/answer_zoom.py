"""Independent, number-checked high-resolution answer-line transcription."""
import hashlib
import json
import re
from pathlib import Path
import fitz
import image_policy
from PIL import Image,ImageOps

VERSION='answer-line-zoom-v3'
FLAG='答案局部放大未通过复核'

def cached(client,prompt,images,folder):
    import agent
    h=hashlib.sha256((VERSION+getattr(client,'model','')+getattr(client,'base','')+image_policy.identity(client)+prompt).encode())
    for _,p in images:h.update(Path(p).read_bytes())
    path=folder/'responses'/(h.hexdigest()[:24]+'.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    result=client.chat(prompt,images);agent.dump(path,result);return result

def crop_line(doc,page,bbox,folder,ident):
    """Re-render from the source PDF, with generous margins; never resize a page thumbnail."""
    if not isinstance(bbox,list) or len(bbox)!=4 or any(type(v) not in (int,float) for v in bbox):raise ValueError('无效答案行坐标')
    x0,y0,x1,y1=bbox
    if not (0<=x0<x1<=1000 and 0<=y0<y1<=1000 and y1-y0<=120):raise ValueError('答案区域越界或不是一行')
    rect=doc[page-1].rect
    clip=fitz.Rect(max(0,x0*rect.width/1000-20),y0*rect.height/1000-24,max(x1*rect.width/1000+30,x0*rect.width/1000+240),y1*rect.height/1000+24)&rect
    raw=folder/(ident+'_raw.png');contrast=folder/(ident+'_contrast.png')
    pix=doc[page-1].get_pixmap(matrix=fitz.Matrix(4,4),clip=clip,alpha=False);pix.save(raw)
    with Image.open(raw) as im:
        # Preserve gray edges and short strokes; no threshold, erosion or generative enhancement.
        ImageOps.autocontrast(ImageOps.grayscale(im),cutoff=0).save(contrast)
    return raw,contrast

def read_crops(client,images,folder):
    prompt=('逐字符抄录每张局部图中明确印刷的题号和 T/F 答案。图内可以包含解析和相邻题目，正常阅读上下文定位即可。'
            '解析中明确写出的答案序列也可以抄录，但不能自行解题、将解析含义推导成 T/F 或按语义纠正印刷答案。'
            '仔细区分 T 的顶横和居中竖线、F 的左竖与中部短横。看不清的字符写 ?。'
            'id 来自图片标签，number 必须来自图内印刷题号，不能把 id 当题号。'
            '返回 JSON {"readings":[{"id":"标签id","number":"印刷题号","characters":["T","F","?"],"complete":true}]}。'
            '同图有多条答案行时，分别输出同一 id 与各自印刷 number，不能合并。缺题号、该行截断或无法确认完整该行时 complete=false。')
    out={}
    def collect(r):
        rows=r if isinstance(r,list) else ([r] if 'id' in r else r.get('readings',[]))
        for a in rows:
            if isinstance(a,dict):out.setdefault(a.get('id'),[]).append(a)
    for start in range(0,len(images),6):
        batch=images[start:start+6]
        r=cached(client,prompt,batch,folder)
        collect(r)
        # Some endpoints return only the first image's object, despite a batch schema.
        # Retry omitted images once, individually; an explicit unreadable row stays unreadable.
        for ident,path in batch:
            if ident not in out:collect(cached(client,prompt,[(ident,path)],folder))
    return out

def value(reading,number,count):
    if isinstance(reading,list):
        matches=[a for a in reading if str(a.get('number','')).strip().rstrip('.、')==str(number).strip().rstrip('.、')]
        if len(matches)!=1:return None
        reading=matches[0]
    if not isinstance(reading,dict) or reading.get('complete') is not True:return None
    if str(reading.get('number','')).strip().rstrip('.、')!=str(number).strip().rstrip('.、'):return None
    chars=reading.get('characters')
    if not isinstance(chars,list) or not chars or any(c not in ('T','F') for c in chars):return None
    if count and len(chars)!=count:return None
    return ''.join(chars)

def page_answers(file,page,requested,client,work):
    import agent
    request_key=hashlib.sha256(json.dumps(requested,sort_keys=True).encode()).hexdigest()[:12]
    model_key=hashlib.sha256((getattr(client,'model','')+getattr(client,'base','')).encode()).hexdigest()[:12]
    folder=Path(work)/'answer_zoom'/VERSION/model_key/agent.digest(file)[:20]/str(page)/request_key;folder.mkdir(parents=True,exist_ok=True)
    with fitz.open(file) as doc:
        whole=folder/'locator_page.png'
        if not whole.exists():doc[page-1].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(whole)
        prompt=('定位这张答案卷页面中以下题号的印刷答案行，不要抄录或推理答案。'
                '返回 JSON {"lines":[{"number":"题号","bbox":[左,上,右,下]}]}。'
                'bbox 是整张图片 0..1000 归一化坐标，完整包含印刷题号、答案字样和全部 T/F 字符即可；允许带入相邻解析文字，不必精确贴边。'
                '本页没有完整答案行的题号不返回。待找题号：'+json.dumps(sorted(requested)))
        located=cached(client,prompt,[('答案原页',str(whole))],folder)
        raw=[];enhanced=[];ids={};duplicates=set()
        for line in (located if isinstance(located,list) else located.get('lines',[])):
            number=str(line.get('number','')).strip().rstrip('.、')
            if number not in requested:continue
            if number in ids:duplicates.add(number);continue
            ident='crop_'+str(len(ids))
            try:a,b=crop_line(doc,page,line.get('bbox'),folder,ident)
            except ValueError:continue
            ids[number]=(ident,a,b,line['bbox']);raw.append((ident,str(a)));enhanced.append((ident,str(b)))
    # Separate requests; neither sees a previous answer or the other reading.
    first=read_crops(client,raw,folder);second=read_crops(client,enhanced,folder)
    results={}
    for number,(ident,a,b,bbox) in ids.items():
        v1=value(first.get(ident),number,requested[number]);v2=value(second.get(ident),number,requested[number])
        results[number]={'confirmed':bool(v1 and v1==v2 and number not in duplicates),
                         'readings':[v1,v2],'answer':v1 if v1 and v1==v2 else '',
                         'raw_crop':str(a),'contrast_crop':str(b),'bbox':bbox,'source_page':page}
    pending={n:c for n,c in requested.items() if not results.get(n,{}).get('confirmed')}
    if pending:
        fallback=read_bands(file,page,pending,client,folder)
        for number,e in fallback.items():
            previous=results.get(number)
            if previous:
                e['previous_readings']=previous['readings']
                if any(v and v!=e['answer'] for v in previous['readings']):e['confirmed']=False
                e['readings']=sorted({v for v in e['readings']+previous['readings'] if v})
            results[number]=e
    return results

def read_bands(file,page,requested,client,folder):
    """Bounded second pass: overlapping source-rendered bands need no model coordinates."""
    raw=[];enhanced=[];paths={}
    with fitz.open(file) as doc:
        rect=doc[page-1].rect
        for i in range(5):
            ident=f'band_{i}';a=folder/(ident+'_raw.png');b=folder/(ident+'_contrast.png')
            clip=fitz.Rect(0,max(0,i*.2-.04)*rect.height,rect.width,min(1,(i+1)*.2+.04)*rect.height)
            doc[page-1].get_pixmap(matrix=fitz.Matrix(3,3),clip=clip,alpha=False).save(a)
            with Image.open(a) as im:ImageOps.autocontrast(ImageOps.grayscale(im),cutoff=0).save(b)
            paths[ident]=(a,b);raw.append((ident,str(a)));enhanced.append((ident,str(b)))
    first=read_crops(client,raw,folder);second=read_crops(client,enhanced,folder);out={}
    for number,count in requested.items():
        pairs=[(ident,value(first.get(ident),number,count),value(second.get(ident),number,count)) for ident in paths]
        seen={v for _,a,b in pairs for v in (a,b) if v}
        matched=[(ident,a,b) for ident,a,b in pairs if a and a==b]
        if not matched:continue
        ident,a,b=matched[0];p1,p2=paths[ident]
        out[number]={'confirmed':len(seen)==1,'readings':sorted(seen),'answer':a,
                     'raw_crop':str(p1),'contrast_crop':str(p2),'source_page':page,'method':'overlapping_bands'}
    return out

def verify(questions,client,work):
    import answer_authority
    tasks={};targets=[]
    for q in questions:
        source=q.get('answer_source') or {};file=source.get('source_file','')
        if not (answer_authority.tf_question(q) or re.fullmatch('[TF]+',q.get('answer',''))):continue
        if Path(file).suffix.lower()!='.pdf':continue
        targets.append(q)
        for page in source.get('source_pages',[]):tasks.setdefault((file,page),{})[str(q['number'])]=len(q.get('options') or [])
    results={};errors={}
    from concurrent.futures import ThreadPoolExecutor
    def run(task):
        (file,page),requested=task
        try:return (file,page),page_answers(file,page,requested,client,work),None
        except Exception as exc:return (file,page),{},type(exc).__name__
    with ThreadPoolExecutor(max_workers=max(1,min(2,getattr(client,'workers',2)))) as pool:
        for key,result,error in pool.map(run,tasks.items()):results[key]=result;errors[key]=error
    for q in targets:
        source=q['answer_source'];evidence=[results.get((source['source_file'],p),{}).get(str(q['number'])) for p in source['source_pages']]
        evidence=[e for e in evidence if e]
        values={e['answer'] for e in evidence if e['confirmed']}
        faults=[errors.get((source['source_file'],p)) for p in source['source_pages'] if errors.get((source['source_file'],p))]
        confirmed=len(values)==1 and not faults
        if any(any(v and v not in values for v in e['readings']) for e in evidence):confirmed=False
        q['answer_zoom_review']={'version':VERSION,'confirmed':confirmed,'evidence':evidence,'errors':faults}
        if confirmed:
            answer=next(iter(values))
            if q.get('answer')!=answer:
                q.setdefault('answer_replacement_history',[]).append({'answer':q.get('answer'),'reason':'两种局部图独立逐字抄录一致'})
                q['answer']=answer
            q['review_flags']=[f for f in q.get('review_flags',[]) if f not in (FLAG,'答案复核不一致','答案未通过独立复核','判断题答案不是 T/F 序列','判断题答案数量与选项不符')]
        elif FLAG not in q.setdefault('review_flags',[]):q['review_flags'].append(FLAG)
    return {'checked':len(targets),'confirmed':sum(q['answer_zoom_review']['confirmed'] for q in targets)}
