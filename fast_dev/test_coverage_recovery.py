import agent,coverage_recovery

def item(number='1'):
    return dict(kind='question',number=number,section='',stem='测试',options=['甲','乙'],answer='',explanation='',
                source_file='paper.pdf',source_hash='a'*64,group='one',source_pages=[1],complete=True)

def setup(monkeypatch,last):
    monkeypatch.setattr(agent,'prepare',lambda *a,**kw:[{'page':1,'text':'原文','images':[]}])
    return [{'file':'paper.pdf','total_pages':1,'group':'one','plan':{'role':'questions','continuous_numbering':True,'last_question_number':last}}]

def test_missing_number_can_recover_from_bare_array(tmp_path,monkeypatch):
    docs=setup(monkeypatch,2)
    class Client:
        def chat(self,*a):return [item('2')]
    rows,report=coverage_recovery.repair([item()],docs,Client(),tmp_path,lambda _:None)
    assert [q['number'] for q in rows]==['1','2'] and report[0]['recovered']

def test_duplicate_replaced_only_by_complete_matching_record(tmp_path,monkeypatch):
    docs=setup(monkeypatch,1)
    class Client:
        def chat(self,*a):return {'items':[item()]}
    rows,report=coverage_recovery.repair([item(),item()],docs,Client(),tmp_path,lambda _:None)
    assert len(rows)==1 and report[0]['recovered']

def test_wrong_number_keeps_original_candidates(tmp_path,monkeypatch):
    docs=setup(monkeypatch,1)
    class Client:
        def chat(self,*a):return {'items':[item('2')]}
    rows,report=coverage_recovery.repair([item(),item()],docs,Client(),tmp_path,lambda _:None)
    assert len(rows)==2 and not report[0]['recovered']
