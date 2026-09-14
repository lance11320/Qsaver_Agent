import json
import pytest
import agent
import bank_cleaning as clean
import bank_versions
import job_progress
import copilot_tasks

@pytest.fixture
def bank(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    p=tmp_path/'questions.json'
    agent.dump(p,[{'stem':'缺答案','answer':''},{'stem':'重复','answer':'A','options':['A.甲']},
                  {'stem':'重 复','answer':'A'},{'stem':'冲突','answer':'A'},
                  {'stem':'冲突','answer':'B'},{'stem':'独立题','answer':'B'}])
    return p

def test_clean_rules_and_archived_removals(bank):
    r=clean.preview(bank)
    assert r['before']==6 and r['after']==2 and r['removed']==4
    target,report,result=clean.apply(bank,r['rules'],r['expected'])
    assert json.loads(target.read_text(encoding='utf-8'))[0]['options']==['甲']
    assert len(json.loads(report.read_text(encoding='utf-8'))['removed_questions'])==4
    assert len(bank_versions.versions())==2

def test_only_requested_rules_and_stale_preview(bank):
    r=clean.preview(bank,['missing_answer']);assert r['after']==5
    agent.dump(bank,[])
    with pytest.raises(ValueError,match='变化'):clean.apply(bank,r['rules'],r['expected'])

def test_external_bank_is_not_overwritten(bank):
    p=bank.with_name('external.json');p.write_bytes(bank.read_bytes());original=p.read_bytes()
    r=clean.preview(p);out,_,_=clean.apply(p,r['rules'],r['expected'])
    assert out!=p and p.read_bytes()==original

def test_clean_plan_needs_no_selection_query(bank):
    r=copilot_tasks.grounded_plan({'operation':'clean','input_paths':[str(bank)]},'清洗题库',[str(bank)])
    assert r['operation']=='clean'

def test_eta_is_stage_based_and_resets(monkeypatch):
    clock=[100.];monkeypatch.setattr(job_progress.time,'time',lambda:clock[0])
    s={};job_progress.update(s,{'stage':'正文','total':4})
    assert s['work_progress']['eta_seconds'] is None
    clock[0]=110.;job_progress.update(s,{'stage':'正文','file':'a','fraction':1})
    assert s['work_progress']['remaining_files']==3 and s['work_progress']['eta_seconds']==30
    job_progress.update(s,{'stage':'题图','total':0})
    assert s['work_progress']['eta_seconds'] is None


def test_gene_letter_case_is_not_deduplicated(bank):
    agent.dump(bank,[{'stem':'A 基因','answer':'A'},{'stem':'a 基因','answer':'A'}])
    assert clean.preview(bank)['removed']==0


def test_execute_clean_plan_calls_tool(bank,monkeypatch):
    import chat_service as svc
    s=svc.session();r=clean.preview(bank)
    s['plan']={'id':'clean-test','operation':'clean','input_paths':[str(bank)],'clean_rules':r['rules'],'clean_preview':r}
    monkeypatch.setattr(svc,'job',lambda session,fn:fn())
    state=svc.dispatch({'session':s['id'],'action':'execute_plan','plan_id':'clean-test'})
    assert state['messages'][-1]['kind']=='exported'
    assert len(json.loads(bank.read_text(encoding='utf-8')))==2
