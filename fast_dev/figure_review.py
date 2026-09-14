"""Human figure review, with page-coordinate rectangle selection and durable audit."""
import copy
import hashlib
import json
import re
import threading
import time
from pathlib import Path
import fitz
from PIL import Image, ImageDraw
import gradio as gr
import agent
from question_media import enrich, persist, validate_regions

LOCK = threading.RLock()
MEDIA_FLAGS = {'题图待视觉复核', '题图提取待复核'}

def suspected(q):
    return bool(q.get('has_figures') or q.get('figures') or q.get('figure_assets') or q.get('media_errors') or q.get('initial_figure_proposals') or re.search(r'如图|下图|图中|图示|图表|见图|右图|左图', q.get('stem','')))

def read(path):
    p=Path(path).resolve()
    if not p.is_relative_to(agent.ROOT.resolve()/'runs'): raise ValueError('请选择 runs 下的结果')
    return json.loads(p.read_text(encoding='utf-8'))

def identity(q):
    return hashlib.sha256(json.dumps([q.get('source_hash'),q.get('number'),q.get('section'),q.get('stem')],ensure_ascii=False).encode()).hexdigest()

def save_review(path,index,token,action,regions):
    with LOCK:
        target=Path(path).with_name('result_reviewed.json')
        data=read(target if target.exists() else path)
        q=data['questions'][int(index)]
        if identity(q)!=token: raise ValueError('题目已变化，请重新加载卡片')
        before=copy.deepcopy(q)
        if action not in ('confirm','replace','none'): raise ValueError('未知复核操作')
        if action=='none': regions=[]
        elif action=='confirm': regions=copy.deepcopy(q.get('figures',[]))
        if action!='none' and not regions: raise ValueError('尚无可确认的题图，请在原页上重新框选')
        if regions:
            with fitz.open(q['source_file']) as doc: validate_regions(regions,list(range(1,len(doc)+1)))
        q['figures']=[dict(r,shared_with=[],sharing_reviewed=True,crop_margin=0,assisted_crop=True) for r in regions]
        q['has_figures']=bool(regions)
        q['media_errors']=[]
        enrich([q],agent.ROOT)
        if q.get('media_errors'): raise ValueError('裁图失败：'+'；'.join(q['media_errors']))
        for a in q.get('figure_assets',[]): a['status']='reviewed'
        if regions:
            key=hashlib.sha256((identity(q)+json.dumps(q['figures'])).encode()).hexdigest()
            q.update(persist(q,agent.ROOT,key))
        else:
            q.update(image='',images=[],figure_sources=[],image_kind='none')
        q['review_flags']=[f for f in q.get('review_flags',[]) if f not in MEDIA_FLAGS]
        q.setdefault('figure_review_history',[]).append({'timestamp':time.time(),'action':action,'previous_figures':before.get('figures',[]),'previous_errors':before.get('media_errors',[]),'previous_flags':before.get('review_flags',[])})
        q['figure_review']={'status':'confirmed','action':action,'timestamp':time.time()}
        temp=target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(target)
        return str(target),data

def page_image(q,page):
    for p in q.get('page_images',[]):
        if Path(p).stem==f'{int(page):04d}' and Path(p).exists(): return Image.open(p).convert('RGB')
    with fitz.open(q['source_file']) as doc:
        pix=doc[int(page)-1].get_pixmap(matrix=fitz.Matrix(1.8,1.8))
        im=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
    out=Image.new('RGB',(im.width,im.height+64),'white');out.paste(im,(0,64))
    ImageDraw.Draw(out).text((12,20),f'SOURCE_PAGE={page}',fill='black')
    return out

def draw_page(q,page,regions,corner=None):
    im=page_image(q,page);d=ImageDraw.Draw(im)
    for r in q.get('question_regions',[]):
        if r.get('page')==int(page):
            b=r['bbox'];d.rectangle((b[0]*im.width/1000,b[1]*im.height/1000,b[2]*im.width/1000,b[3]*im.height/1000),outline='blue',width=3)
    for r in regions:
        if r['page']==int(page):
            b=r['bbox'];d.rectangle((b[0]*im.width/1000,b[1]*im.height/1000,b[2]*im.width/1000,b[3]*im.height/1000),outline='red',width=3)
    if corner: d.ellipse((corner[0]-5,corner[1]-5,corner[0]+5,corner[1]+5),fill='red')
    return im

def build_review(state,status,result_file,preview):
    with gr.Group():
        gr.Markdown('### 3. 逐题确认附图\n整批提取完成后自动加载。确认只解除题图标记，答案等问题仍需另行复核。蓝框为模型估计的题目区域；旧结果没有区域时展示完整来源页。')
        all_q=gr.Checkbox(label='显示所有题目（检查漏识别 / 修改已确认题）',value=False)
        choice=gr.Dropdown([],label='复核卡片')
        card=gr.Markdown('等待提取或加载结果。')
        gallery=gr.Gallery(label='当前候选附图',columns=2,height=300)
        page=gr.Dropdown([],label='原文物理页（可切换到相邻页补图）')
        gr.Markdown('重新框选：在原页依次点击矩形的两个对角，即可添加一个红框。可跨页添加多个框；保存时以所有红框替换本题题图。请保留图例、坐标轴、符号及完整面板。')
        source=gr.Image(label='原页框选',type='pil',interactive=False,format='png',height=700)
        boxes=gr.State([]);corner=gr.State(None);token=gr.State('')
        with gr.Row():
            clear=gr.Button('清空框选（开始重裁）');undo=gr.Button('撤销最后一框')
        with gr.Row():
            confirm=gr.Button('确认当前题图并下一题',variant='primary')
            replace=gr.Button('保存红框题图并下一题',variant='primary')
            none=gr.Button('确认本题无图')
            skip=gr.Button('暂跳过 / 下一题')
        def listing(path,show_all):
            if not path:return gr.update(choices=[],value=None)
            qs=read(path)['questions']
            choices=[(f"{Path(q['source_file']).name} · 第 {q['number']} 题 · "+('已确认' if q.get('figure_review',{}).get('status')=='confirmed' else '待复核'),str(i)) for i,q in enumerate(qs) if show_all or (suspected(q) and q.get('figure_review',{}).get('status')!='confirmed')]
            return gr.update(choices=choices,value=choices[0][1] if choices else None)
        state.change(listing,[state,all_q],[choice]);all_q.change(listing,[state,all_q],[choice])
        def select(path,index):
            if index is None:return '本轮没有待复核题图。',[],gr.update(choices=[],value=None),[],None,''
            q=read(path)['questions'][int(index)]
            if Path(q['source_file']).suffix.lower()!='.pdf':
                return '此题来源不是 PDF；请使用原有文字复核面板。',[],gr.update(choices=[],value=None),[],None,identity(q)
            with fitz.open(q['source_file']) as doc:pages=[str(i+1) for i in range(len(doc))]
            regs=copy.deepcopy(q.get('figures',[]))
            ims=[(str(agent.ROOT/a['image']),a.get('caption','')) for a in q.get('figure_assets',[]) if (agent.ROOT/a['image']).exists()]
            if q.get('figure_review') and q.get('image'):ims=[(str(agent.ROOT/q['image']),'已确认完整题图')]
            text=f"**第 {q['number']} 题** · {'已识别附图' if regs else '疑似带图 / 待检查'}\n\n"+q['stem']+'\n\n'+'\n\n'.join(q.get('options',[]))+'\n\n复核标记：'+'、'.join(q.get('review_flags',[]))
            selected=str((q.get('source_pages') or [1])[0])
            return text,ims,gr.update(choices=pages,value=selected),regs,None,identity(q)
        selection=choice.change(select,[state,choice],[card,gallery,page,boxes,corner,token])
        def render(path,index,p,regs,c):
            if index is None or not p:return None
            return draw_page(read(path)['questions'][int(index)],int(p),regs,c)
        def change_page(path,index,p,regs):return render(path,index,p,regs,None),None
        page.change(change_page,[state,choice,page,boxes],[source,corner])
        selection.then(change_page,[state,choice,page,boxes],[source,corner])
        def click(path,index,p,regs,c,evt:gr.SelectData):
            if index is None or not p:raise gr.Error('请先选择 PDF 题目')
            q=read(path)['questions'][int(index)];im=page_image(q,int(p));xy=list(evt.index[:2])
            if c is None:return regs,xy,draw_page(q,int(p),regs,xy)
            b=[min(c[0],xy[0])/im.width*1000,min(c[1],xy[1])/im.height*1000,max(c[0],xy[0])/im.width*1000,max(c[1],xy[1])/im.height*1000]
            r={'page':int(p),'bbox':b,'caption':'人工框选'}
            try:validate_regions([r],[int(p)])
            except ValueError as e:raise gr.Error(str(e))
            regs=regs+[r];return regs,None,draw_page(q,int(p),regs)
        source.select(click,[state,choice,page,boxes,corner],[boxes,corner,source])
        def reset(path,index,p,regs,remove):
            regs=regs[:-1] if remove else []
            return regs,None,render(path,index,p,regs,None)
        clear.click(lambda a,b,c,d:reset(a,b,c,d,False),[state,choice,page,boxes],[boxes,corner,source])
        undo.click(lambda a,b,c,d:reset(a,b,c,d,True),[state,choice,page,boxes],[boxes,corner,source])
        def commit(path,index,t,regs,action):
            if index is None:raise gr.Error('请选择题目')
            try:out,data=save_review(path,int(index),t,action,regs)
            except (ValueError,OSError) as e:raise gr.Error(str(e))
            return out,'题图复核已保存；其它复核标记保持。',out,data
        for button,action in ((confirm,'confirm'),(replace,'replace'),(none,'none')):
            button.click(lambda a,b,c,d,act=action:commit(a,b,c,d,act),[state,choice,token,boxes],[state,status,result_file,preview],concurrency_limit=1,concurrency_id='figure-review').then(listing,[state,all_q],[choice])
        def advance(path,index,show_all):
            update=listing(path,show_all);choices=update['choices'];ids=[v for _,v in choices]
            update['value']=ids[(ids.index(index)+1)%len(ids)] if index in ids else (ids[0] if ids else None)
            return update
        skip.click(advance,[state,choice,all_q],[choice])
