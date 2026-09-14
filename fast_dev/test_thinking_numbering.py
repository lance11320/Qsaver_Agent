import json
import pytest
import agent
import thinking_policy as policy
from stem_numbering import clean_stem,display_stem

@pytest.mark.parametrize('text,number,expected',[
    ('26.判断正误','26','判断正误'),
    ('第 3 题：观察图片','3','观察图片'),
    ('【22-23 为题组】22. 材料','22','材料'),
    ('【题组 22-23】材料\n23.请判断','23','材料\n请判断'),
    ('3-磷酸甘油醛脱氢酶','3','3-磷酸甘油醛脱氢酶'),
    ('1 分子亚油酸','1','1 分子亚油酸'),
    ('3.5%的溶液','3','3.5%的溶液'),
    ('2024年研究','24','2024年研究'),
    ('实验步骤\n1.加入试剂','1','实验步骤\n1.加入试剂'),
    ('27.原题号不一致','26','27.原题号不一致'),
])
def test_only_question_labels_removed(text,number,expected):
    assert clean_stem(text,number)==expected

def test_ingest_identity_ignores_source_number():
    a={'stem':'3.测试题','number':'3','options':['甲']}
    b={'stem':'测试题','options':['甲']}
    assert agent.fingerprint(a)==agent.fingerprint(b)

def test_thinking_payload_and_task_scope(monkeypatch):
    monkeypatch.setattr(agent,'config',lambda:{'api_key':'test-key'})
    requests=[]
    class Response:
        status_code=200
        def json(self):return {'choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':10}}
    class Transport:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,headers,json):requests.append(json);return Response()
    monkeypatch.setattr(agent.httpx,'Client',Transport)
    client=agent.Client('qwen3.8-flash')
    for task in ['plan','relationship','cross_page','semantic_select','figure_review','extract_retry','transcribe']:
        policy.call(client,'JSON',task=task)
        assert requests[-1]['enable_thinking']==bool(policy.BUDGETS[task])
        assert requests[-1].get('thinking_budget',0)==policy.BUDGETS[task]
    assert policy.TASK.get()=='transcribe'
    assert client.usage[0]['thinking_enabled']
    assert policy.parameters('other-model')=={}

def test_policy_restores_context_after_error():
    class Broken:
        def chat(self,*a):raise RuntimeError('failure')
    with pytest.raises(RuntimeError):policy.call(Broken(),'x',task='plan')
    assert policy.TASK.get()=='transcribe'
