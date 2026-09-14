import json
import time
import pytest
import agent
import chat_service as svc

@pytest.fixture
def fresh(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    agent.dump(tmp_path/'qsaver_backend_config.json',{'api_profiles':[{'name':'test','api_key':'test-secret','base_url':'https://example.com/v1'}]})
    return svc.session()

def test_settings_shared_without_exposing_secret(fresh):
    s=fresh
    r=svc.dispatch({'session':s['id'],'action':'settings','settings':{'profile':'custom','api_key':'private-test-key','base_url':'https://example.org/v1','model':'qwen3.7-plus','workers':4}})
    assert 'private-test-key' not in json.dumps(r)
    assert 'test-secret' not in json.dumps(r)
    assert svc.options(s)['api_key']=='private-test-key'
    assert svc.snapshot(svc.session())['settings']['model']=='qwen3.7-plus'

def test_live_usage_totals(fresh):
    svc.record_usage(fresh,{'prompt_tokens':110,'completion_tokens':40,'total_tokens':150})
    svc.record_usage(fresh,{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30})
    assert svc.snapshot(fresh)['tokens']=={'input':130,'output':50,'total':180,'calls':2}

def test_job_failure_releases_and_redacts(fresh):
    def fail():raise ValueError('failure test-secret')
    svc.job(fresh,fail)
    for _ in range(100):
        if not fresh['busy']:break
        time.sleep(.01)
    assert not fresh['busy']
    assert 'test-secret' not in json.dumps(svc.snapshot(fresh))
    assert svc.WORK_LOCK.acquire(blocking=False)
    svc.WORK_LOCK.release()

def test_map_requires_confirmation(fresh,tmp_path,monkeypatch):
    f=tmp_path/'questions.txt';f.write_text('题目',encoding='utf-8')
    m=tmp_path/'maps'/'map.json';m.parent.mkdir();m.write_text('{}')
    called=[]
    monkeypatch.setattr(svc.document_map,'build',lambda *a,**k:(m,{'documents':[{'path':str(f),'status':'ready'}]}))
    monkeypatch.setattr(agent,'run',lambda *a,**k:called.append('extract'))
    svc.dispatch({'session':fresh['id'],'action':'message','text':'整理题目','files':[str(f)]})
    for _ in range(100):
        if not fresh['busy']:break
        time.sleep(.01)
    assert fresh['messages'][-1]['kind']=='map'
    assert not called
    assert fresh['map']==str(m)

def test_card_navigation_load_no_usage(fresh,tmp_path):
    from test_figure_review import setup_result
    # A text-only fixture is enough to validate queue navigation and no model usage.
    run=tmp_path/'runs'/'sample';run.mkdir(parents=True)
    q={'source_file':str(tmp_path/'q.txt'),'source_hash':'abc','number':'1','stem':'如图','answer':'A','options':[],'source_pages':[1],'figures':[],'review_flags':['题图待视觉复核']}
    path=run/'result.json';path.write_text(json.dumps({'questions':[q,dict(q,number='2')],'partial':False}),encoding='utf-8')
    svc.dispatch({'session':fresh['id'],'action':'load','path':str(path)})
    c=svc.dispatch({'session':fresh['id'],'action':'card','index':1})
    assert c['position']==2 and c['count']==2
    assert svc.snapshot(fresh)['tokens']['total']==0
    with pytest.raises(ValueError):svc.dispatch({'session':fresh['id'],'action':'load','path':str(tmp_path/'outside.json')})

def test_context_options_do_not_escape(fresh):
    token=agent.CLIENT_OPTIONS.set({'base_url':'https://example.org/v1','api_key':'session-key'})
    try:
        client=agent.Client();assert client.key=='session-key' and client.base=='https://example.org/v1'
    finally:agent.CLIENT_OPTIONS.reset(token)
    assert agent.CLIENT_OPTIONS.get() is None


def test_workbench_saved_config_is_used_without_restart(fresh):
    agent.dump(agent.ROOT/'qsaver_backend_config.json',{'api_model_name':'qwen3.8-max','api_base_url':'https://example.org/v1','api_key':'changed-key'})
    v=svc.dispatch({'session':fresh['id'],'action':'settings_get'})
    assert v['has_key'] and v['model']=='qwen3.8-max'
    assert svc.options(fresh)['api_key']=='changed-key'
    assert 'changed-key' not in json.dumps(v)


def test_missing_active_key_does_not_fall_back_to_stale_profile(fresh):
    agent.dump(agent.ROOT/'qsaver_backend_config.json',{'api_model_name':'qwen3.8-flash','api_key':'','api_profiles':[{'name':'old','api_key':'stale'}]})
    assert not svc.dispatch({'session':fresh['id'],'action':'settings_get'})['has_key']


def test_agent_settings_persist_in_shared_config_not_project(fresh):
    svc.dispatch({'session':fresh['id'],'action':'settings','settings':{'profile':'custom','api_key':'shared-test-key','base_url':'https://example.org/v1','model':'qwen3.8-max'}})
    cfg=agent.config();assert cfg['api_key']=='shared-test-key' and cfg['api_model_name']=='qwen3.8-max'
    assert 'shared-test-key' not in (agent.ROOT/'copilot_projects'/(fresh['id']+'.json')).read_text(encoding='utf-8')
