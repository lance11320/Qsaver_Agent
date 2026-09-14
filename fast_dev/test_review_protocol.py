import json,re
import pytest
import text_review as tr

def envelope(ids,findings=None):
    return {'batch_id':'b','status':'completed','reviewed_ids':ids,'findings':findings or []}

def test_explicit_clean_batch():
    done,found=tr.parse_review(envelope(['a','b']),'b',{'a','b'})
    assert done=={'a','b'} and found=={}

@pytest.mark.parametrize('obj',[
    None,{},[],{'findings':[]},
    dict(envelope(['a']),batch_id='wrong'),
    dict(envelope(['a']),status='success'),
    dict(envelope(['a']),findings=None),
    envelope(['a','a']),envelope(['other']),
    envelope(['a'],[{'id':'other','risks':[]}]),
    envelope(['a'],[{'id':'a','risks':'bad'}]),
])
def test_invalid_response_is_not_clean(obj):
    with pytest.raises(ValueError):tr.parse_review(obj,'b',{'a'})

def batch():
    return [(i,{'number':str(n),'stem':'题干'+i,'options':['选项']}) for n,i in enumerate(['a','b'],1)]

def test_retry_only_missing_and_preserve_findings(monkeypatch,tmp_path):
    calls=[];risk={'field':'stem','quote':'题干a','reason':'疑点'}
    def request(client,prompt,*args,**kwargs):
        ident=re.search(r'批次编号：([^\n]+)',prompt)[1]
        payload=json.loads(prompt.split('\n文本：')[1]);calls.append([q['id'] for q in payload])
        return {'batch_id':ident,'status':'completed','reviewed_ids':['a'] if len(calls)==1 else ['b'],
                'findings':[{'id':'a','risks':[risk]}] if len(calls)==1 else []}
    monkeypatch.setattr(tr,'request',request)
    result=tr.check_batch(object(),batch(),tmp_path)
    assert calls==[['a','b'],['b']] and not result.unresolved
    assert result['a']==[risk] and result['b']==[]

def test_failed_retry_keeps_good_results_and_marks_missing(monkeypatch,tmp_path):
    count=0
    def request(client,prompt,*args,**kwargs):
        nonlocal count
        count+=1
        if count==2:raise TimeoutError()
        ident=re.search(r'批次编号：([^\n]+)',prompt)[1]
        return dict(envelope(['a'],[{'id':'a','risks':[{'field':'stem','quote':'题干a'}]}]),batch_id=ident)
    monkeypatch.setattr(tr,'request',request)
    result=tr.check_batch(object(),batch(),tmp_path)
    assert count==2 and result.unresolved=={'b'} and result['a']

def test_empty_reviewed_ids_never_marks_batch_clean(monkeypatch,tmp_path):
    calls=[]
    def request(client,prompt,*args,**kwargs):
        calls.append(1);ident=re.search(r'批次编号：([^\n]+)',prompt)[1]
        return dict(envelope([]),batch_id=ident)
    monkeypatch.setattr(tr,'request',request)
    result=tr.check_batch(object(),batch(),tmp_path)
    assert len(calls)==2 and result.unresolved=={'a','b'}
