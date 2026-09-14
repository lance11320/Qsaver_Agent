import copy,json
import pytest
import text_review as tr
import agent,thinking_policy

def q():return {'number':'1','source_file':'a.pdf','source_pages':[1],'stem':'判断正误','options':['GTP 水解放发包被解体'],'answer':'F','review_flags':[]}

def test_default_reviewer_reuses_effective_api_with_separate_usage(monkeypatch):
    monkeypatch.setattr(agent,'config',lambda:{'api_profiles':[]})
    class Client:
        model='qwen3.8-flash';base='https://example.test/v1';key='test-only';usage=[{'old':True}]
    source=Client();reviewer=tr.reviewer(source)
    assert reviewer.model=='qwen3.8-max' and source.model=='qwen3.8-flash'
    assert reviewer is not source and reviewer.key==source.key and reviewer.base==source.base
    assert reviewer.usage==[] and source.usage==[{'old':True}]
    token=thinking_policy.TASK.set('text_review')
    try:assert thinking_policy.parameters(reviewer.model)=={'enable_thinking':True,'thinking_budget':8192}
    finally:thinking_policy.TASK.reset(token)

def test_only_text_fields_are_writable():
    row=q()
    for field in ('answer','options[-1]','options[1]','source_file'):
        with pytest.raises(ValueError):tr.field_value(row,field)

def test_safe_patch_rejects_wrong_option_deletion_and_unrelated_changes():
    assert tr.safe_patch('D.Fig1f 中 O304 处理组无显著差异','Fig1d 中未处理组显著低于对照','O304','options[3]','57') is None
    assert tr.safe_patch('角质形成细胞','角形成细胞','角质','stem','14') is None
    assert tr.safe_patch('GTP 水解放发包被解体','GTP 水解触发包被解体','放发','options[0]','12')=='GTP 水解触发包被解体'
    assert tr.safe_patch('GTP 水解放发包被解体','GTP 水解触发包被解体','GTP','options[0]','12') is None
    assert tr.compare('H⁺ 与Ⅱ')==tr.compare('H+与II')

def test_deepseek_high_only_on_text_task():
    token=thinking_policy.TASK.set('text_review')
    try:assert thinking_policy.parameters('deepseek-flash')=={'thinking':{'type':'enabled'},'reasoning_effort':'high'}
    finally:thinking_policy.TASK.reset(token)
    assert thinking_policy.parameters('deepseek-flash')=={}

def test_missing_batch_results_are_not_accepted(monkeypatch,tmp_path):
    monkeypatch.setattr(tr,'request',lambda *a,**kw:{'items':[]})
    assert tr.check_batch(object(),[('q0',q())],tmp_path).unresolved=={'q0'}

def test_answers_not_sent_to_text_reviewer(monkeypatch,tmp_path):
    row=q();row['answer']='SECRET_ANSWER_MARKER'
    def request(client,prompt,images,*a,**kw):
        assert 'SECRET_ANSWER_MARKER' not in prompt and images==[]
        assert kw['task']=='text_review'
        import re
        ident=re.search(r'批次编号：([^\n]+)',prompt)[1]
        return {'batch_id':ident,'status':'completed','reviewed_ids':['q0'],'findings':[]}
    monkeypatch.setattr(tr,'request',request)
    tr.check_batch(object(),[('q0',row)],tmp_path)

@pytest.mark.parametrize('status',['corrected','unresolved','unchanged'])
def test_only_verified_corrections_are_applied(monkeypatch,tmp_path,status):
    class Client:model='deepseek-flash';usage=[]
    monkeypatch.setattr(tr,'reviewer',lambda *a:Client())
    monkeypatch.setattr(tr,'check_batch',lambda *a:{'q0':[{'field':'options[0]','quote':'放发','reason':'疑似错字'}]})
    monkeypatch.setattr(tr,'zoom_field',lambda *a:{'field':'options[0]','status':status,'after':'GTP 水解触发包被解体'})
    row=q();summary,_=tr.run([row],object(),tmp_path,lambda _:None)
    assert row['answer']=='F'
    assert ('触发' in row['options'][0]) is (status=='corrected')
    assert (tr.FLAG in row['review_flags']) is (status=='unresolved')

def test_invalid_quote_is_not_applied(monkeypatch,tmp_path):
    class Client:model='deepseek-flash';usage=[]
    monkeypatch.setattr(tr,'reviewer',lambda *a:Client())

    monkeypatch.setattr(tr,'check_batch',lambda *a:{'q0':[{'field':'answer','quote':'F'}]})
    monkeypatch.setattr(tr,'zoom_field',lambda *a:{'field':'options[0]','status':'unchanged'})
    row=q();tr.run([row],object(),tmp_path,lambda _:None)
    assert row['answer']=='F' and tr.FLAG in row['review_flags']
