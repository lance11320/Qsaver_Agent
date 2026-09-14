import json
import os
import time
from pathlib import Path
import pytest
import agent
import chat_service as svc
import figure_review as review
import review_workflow as flow
import project_storage as storage


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    source=tmp_path/'source.txt';source.write_text('1. A\n2. B',encoding='utf-8')
    qs=[{'number':str(i+1),'stem':'测试题'+str(i),'answer':'A','options':[],
         'source_file':str(source),'source_hash':'abc','source_pages':[1],
         'group':'paper','has_figures':True,'figures':[],
         'review_flags':['题图提取待复核']} for i in range(2)]
    path=tmp_path/'runs'/'test'/'result.json'
    agent.dump(path,{'run_id':'test','questions':qs,'partial':True,
                     'documents':[{'file':str(source),'group':'paper'}]})
    s=svc.session();s['result']=str(path);svc.save_project(s)
    return s,path,qs


def test_none_removes_current_and_advances_then_empty(setup):
    s,p,qs=setup
    for i in range(2):
        r=svc.dispatch({'session':s['id'],'action':'review','index':i,
                        'token':review.identity(qs[i]),'decision':'none'})
        if i==0:assert r['card']['index']==1
        else:assert r['card']['empty']
    result=review.read(svc.result_path(s))
    assert all(q['figure_review']['action']=='none' for q in result['questions'])


def test_partial_ingest_skips_discarded_and_unanswered(setup):
    s,p,qs=setup
    for q in qs:q.update(has_figures=False,review_flags=[])
    extra=dict(qs[0],stem='缺答案',answer='')
    qs[1]['question_review']={'status':'discarded'}
    agent.dump(p,{'run_id':'x','partial':True,'questions':qs+[extra]})
    r=agent.ingest(p,allow_partial=True)
    assert r['added']==1 and r['discarded']==1 and r['missing_answer']==1
    assert agent.ingest(p,allow_partial=True)['added']==0


def test_discard_and_restore_persist_across_session_reload(setup):
    s,p,qs=setup
    svc.dispatch({'session':s['id'],'action':'question_decision','index':0,
                  'token':review.identity(qs[0]),'decision':'discarded'})
    svc.SESSIONS.pop(s['id'])
    restored=svc.session(s['id'])
    assert flow.discarded(review.read(svc.result_path(restored))['questions'][0])
    assert svc.card(restored,{})['index']==1
    svc.dispatch({'session':s['id'],'action':'question_decision','index':0,
                  'token':review.identity(qs[0]),'decision':'pending'})
    assert not flow.discarded(review.read(svc.result_path(restored))['questions'][0])


def test_missing_answer_not_offered_as_normal_review(setup):
    s,p,qs=setup;qs[0]['answer']='';agent.dump(p,{'questions':qs})
    assert svc.card(s,{})['index']==1
    assert svc.card(s,{'all':True,'index':0})['index']==0
    with pytest.raises(ValueError,match='缺少答案'):
        svc.dispatch({'session':s['id'],'action':'question_decision','index':0,
                      'token':review.identity(qs[0]),'decision':'accepted'})


def test_recovery_requires_independent_agreement_and_checkpoints(setup):
    s,p,qs=setup;data=review.read(p);data['questions'][0]['answer']=''
    data['questions'][0]['review_flags']=['原文未提供答案'];agent.dump(p,data)
    class Reader:
        calls=0
        def chat(self,prompt,images=()):
            self.calls+=1
            if '独立核对' in prompt:return {'matches':True,'answer':'A'}
            return {'answers':[{'id':0,'answer':'A','page':1,'quote':'1. A'}]}
    client=Reader();r=flow.recover_answers(p,client)
    assert r['recovered']==1 and client.calls==2
    assert review.read(p)['questions'][0]['answer_source']['quote']=='1. A'
    flow.recover_answers(p,client);assert client.calls==2


def test_recovery_disagreement_does_not_invent_answer(setup):
    s,p,qs=setup;data=review.read(p);data['questions'][0]['answer']='';agent.dump(p,data)
    class Reader:
        def chat(self,prompt,images=()):
            if '独立核对' in prompt:return {'matches':True,'answer':'B'}
            return {'answers':[{'id':0,'answer':'A','page':1,'quote':'1. A'}]}
    assert flow.recover_answers(p,Reader())['recovered']==0
    assert not review.read(p)['questions'][0]['answer']


def test_cache_cleanup_keeps_reviews_and_durable_uploads(setup):
    s,p,qs=setup
    copies=storage.retain_uploads([qs[0]['source_file']],s['id'])
    cache=agent.ROOT/'review_ui'/'x.png';cache.parent.mkdir();cache.write_bytes(b'preview')
    os.utime(cache,(0,0));r=storage.trim_previews(max_bytes=0)
    assert r['files']==1 and not cache.exists()
    assert p.exists() and Path(copies[0]).exists()


def test_natural_ingest_bypasses_selection_planner(setup,monkeypatch):
    s,p,qs=setup;called=[]
    monkeypatch.setattr(svc,'job',lambda session,fn:fn())
    monkeypatch.setattr(agent,'ingest',lambda path,allow_partial:called.append(allow_partial) or {'added':1})
    svc.dispatch({'session':s['id'],'action':'message','text':'上述有未通过检查的，已经通过的可以入库'})
    assert called==[True]
