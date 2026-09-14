"""Deterministic cleaning tools: preview removals, archive them, then save."""
import copy
import hashlib
import re
import uuid
from pathlib import Path
import agent
import bank_versions
import copilot_tasks

RULES={'missing_answer':'移除缺答案题','duplicate_stem':'移除重复题干（保留首题）',
       'answer_conflict':'移除答案冲突题组','normalize_options':'规范选项格式'}

def key(text):
    return re.sub(r'\s+','',str(text or ''))

def missing_answers(questions):
    return {i for i,q in enumerate(questions) if not key(q.get('answer'))}

def answer_conflicts(questions):
    groups={};bad=set()
    for i,q in enumerate(questions):
        groups.setdefault(key(q['stem']),[]).append(i)
        if any('答案冲突' in f or '答案复核不一致' in f for f in q.get('review_flags',[])):bad.add(i)
    for ids in groups.values():
        if len({key(questions[i].get('answer')) for i in ids if key(questions[i].get('answer'))})>1:bad.update(ids)
    return bad

def duplicate_stems(questions, excluded=()):
    seen=set();bad=set()
    for i,q in enumerate(questions):
        if i in excluded:continue
        stem=key(q['stem'])
        if stem in seen:bad.add(i)
        seen.add(stem)
    return bad

def preview(path,rules=None):
    rules=list(RULES) if rules is None else rules
    if not isinstance(rules,list) or not rules or any(r not in RULES for r in rules):raise ValueError('清洗规则无效')
    expected=agent.digest(path)
    questions=copilot_tasks.load_questions(path);reasons={}
    if agent.digest(path)!=expected:raise ValueError('题库已变化，请重新预览')
    for rule,indices in [('missing_answer',missing_answers(questions)),('answer_conflict',answer_conflicts(questions))]:
        if rule in rules:
            for i in indices:reasons.setdefault(i,[]).append(rule)
    if 'duplicate_stem' in rules:
        for i in duplicate_stems(questions,reasons):reasons.setdefault(i,[]).append('duplicate_stem')
    cleaned=[];normalized=0
    for i,original in enumerate(questions):
        if i in reasons:continue
        q=copy.deepcopy(original)
        if 'normalize_options' in rules:
            agent.normalize_embedded_options(q)
            q['options']=agent.clean_options(q.get('options') or [])
            if q!=original:normalized+=1
        cleaned.append(q)
    return {'source':str(Path(path).resolve()),'expected':expected,'rules':rules,
            'before':len(questions),'after':len(cleaned),'removed':len(reasons),'normalized':normalized,
            'counts':{r:sum(r in v for v in reasons.values()) for r in rules},
            'questions':cleaned,'removed_questions':[{'index':i,'reasons':v,'question':questions[i]} for i,v in sorted(reasons.items())]}

def apply(path,rules,expected,destination=''):
    if agent.digest(path)!=expected:raise ValueError('题库已变化，请重新预览清洗计划')
    report=preview(path,rules)
    if report['expected']!=expected:raise ValueError('题库已变化，请重新预览清洗计划')
    out=agent.ROOT/'runs'/('cleaning_'+uuid.uuid4().hex[:12]);out.mkdir(parents=True)
    agent.dump(out/'cleaning_report.json',report)
    managed=Path(path).resolve()==(agent.ROOT/'questions.json').resolve()
    if managed:
        bank_versions.commit(report['questions'],'Agent 规则清洗',expected=expected)
        target=agent.ROOT/'questions.json'
    else:
        target=copilot_tasks.export_bundle(report['questions'],destination,path)
    return target,out/'cleaning_report.json',report
