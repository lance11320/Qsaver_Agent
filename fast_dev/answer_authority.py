"""Document roles determine answer authority; handwriting is never an answer key."""
import re
import unicodedata

ROLE_PROMPT = '''文档分类只看原始印刷内容。手写答案、圈选、勾叉、批改和边注是作答痕迹，不能据此分类为 solutions 或 mixed。
questions 是印刷题目卷；solutions 需要可见的印刷参考答案/解析；mixed 需要同一文件确有印刷题目及印刷答案/解析。
题目中的“以下答案/解析”等词或作答说明不构成答案卷证据。不确定则 unknown，并描述可见证据。'''

PROMPT = '''答案来源约束：忽略所有手写作答、圈选、勾叉、批改分数与笔迹，不把它们当作印刷标准答案。
题目卷只提取题干与选项，answer/explanation 留空；参考答案卷只提取印刷答案和解析。
逐项判断题答案必须按 A/B/C/D 等原顺序抄录 T/F 序列（如 TFTT），不能输出 ACD 等选择题字母集合。
不得把手写 ACD 推理转换成 TFTT。原文答案无法确认则留空并标记，不自行解题。
真正的单选/多选题仍抄录原文选项字母，不强制转换成 T/F。'''

def role(doc,page=None):
    plan=doc.get('plan',{})
    if page is not None:
        for seg in plan.get('segments',[]):
            if seg.get('start_page',0)<=page<=seg.get('end_page',0):return seg['role']
    return plan.get('role','unknown')

def authorized(item,documents):
    doc=next((d for d in documents if d.get('file')==item.get('source_file')),None)
    if doc is None:return True  # Legacy text-only records without a document map.
    pages=item.get('source_pages') or [None]
    return all(role(doc,p) in ('solutions','mixed','unknown') for p in pages)

def sanitize(items,documents):
    kept=[]
    for item in items:
        if not authorized(item,documents):
            if item['kind']=='solution':continue
            if item.get('answer'):
                item['rejected_question_page_answer']={'answer':item['answer'],'reason':'题目卷作答不是标准答案'}
            item['answer']='';item['explanation']='';item.pop('answer_source',None)
        kept.append(item)
    return kept

def tf_question(q):
    return q.get('answer_format')=='true_false' or bool(re.search(r'正误|逐[项一].*判断',q.get('stem','')))

def normalize(answer):
    value=unicodedata.normalize('NFKC',str(answer or '')).strip()
    compact=re.sub(r'[\s,，、;；/]+','',value).upper()
    if re.fullmatch('[TF]+',compact):return compact
    return value

def format_flags(q):
    q['answer']=normalize(q.get('answer'))
    if not q['answer'] or not tf_question(q):return []
    if not re.fullmatch('[TF]+',q['answer']):return ['判断题答案不是 T/F 序列']
    count=len(q.get('options') or [])
    if count and len(q['answer'])!=count:return ['判断题答案数量与选项不符']
    return []

def assign(q,solution):
    if q.get('answer') and normalize(q['answer'])!=normalize(solution.get('answer')):
        q.setdefault('answer_replacement_history',[]).append({'answer':q['answer'],'reason':'采用唯一关联的正式答案记录'})
    q['answer']=normalize(solution.get('answer'))
    q['explanation']=solution.get('explanation','')
    q['answer_source']={k:solution[k] for k in ('source_file','source_pages')}
    q['answer_source']['authority']='linked_printed_solution'

def recovery_sources(result,group,questions):
    linked=[d for d in result.get('documents',[]) if d.get('group')==group]
    formal=[d['file'] for d in linked if role(d) in ('solutions','mixed')]
    if formal:return formal
    # Once classified as question-only, never fall back to that file's handwriting.
    blocked={d['file'] for d in linked if role(d)=='questions'}
    return list(dict.fromkeys([d['file'] for d in linked if d['file'] not in blocked]+
                             [q.get('source_file','') for q in questions if q.get('source_file') not in blocked]))
