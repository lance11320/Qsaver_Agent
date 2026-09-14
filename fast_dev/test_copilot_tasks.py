import json
from pathlib import Path
import pytest
import agent
import chat_service as svc
from copilot_tasks import grounded_plan,select,export_bundle

def test_select_logic_quota_and_original(tmp_path):
    q=[{'stem':'遗传学 动物 A','options':[]},{'stem':'遗传学 植物 B','options':[]},{'stem':'分子生物学 C','options':[]}]
    p=tmp_path/'bank.json';p.write_text(json.dumps(q),encoding='utf-8')
    chosen,report=select(p,{'groups':[{'count':2,'query':{'op':'OR','keywords':['遗传学']},'exclude_keywords':['植物']},{'count':1,'query':{'op':'AND','keywords':['分子','生物学']}}]})
    assert [x['stem'] for x in chosen]==['遗传学 动物 A','分子生物学 C']
    assert report[0]['shortfall']==1
    assert json.loads(p.read_text())==q

def test_grounding_rejects_invented_destination(tmp_path):
    p=tmp_path/'bank.json';p.write_text('[{"stem":"abc"}]')
    raw={'operation':'select','input_paths':[str(p)],'output_directory':str(tmp_path/'secret'),'query':{'op':'OR','keywords':['abc']}}
    with pytest.raises(ValueError,match='输出位置'):grounded_plan(raw,'根据附件选题',[str(p)])

def test_export_portable_images_no_overwrite(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    from PIL import Image
    (tmp_path/'images').mkdir();Image.new('RGB',(20,20),'white').save(tmp_path/'images'/'test.png')
    q=[{'stem':'题目','image':'images/test.png','images':['images/test.png']}]
    a=export_bundle(q,tmp_path/'out');b=export_bundle(q,tmp_path/'out')
    assert a!=b
    exported=json.loads(a.read_text(encoding='utf-8'))
    assert (a.parent/exported[0]['image']).exists()
    assert exported[0]['image']==exported[0]['images'][0]
    assert q[0]['image']=='images/test.png'

def test_project_survives_restart_without_key(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    s=svc.session();s['settings'].update(profile='custom',api_key='never-write-me');svc.message(s,'我的遗传学项目',role='user')
    saved=tmp_path/'copilot_projects'/(s['id']+'.json')
    assert 'never-write-me' not in saved.read_text(encoding='utf-8')
    del svc.SESSIONS[s['id']]
    restored=svc.session(s['id']);assert restored['title']=='我的遗传学项目'
    assert restored['settings']['profile']=='auto'


def test_projects_keep_review_results_separate(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    a=svc.session();b=svc.session()
    original=tmp_path/'runs'/'raw'/'result.json';original.parent.mkdir(parents=True)
    data={'questions':[{'stem':'同一份题目','number':'1'}],'partial':False}
    original.write_text(json.dumps(data),encoding='utf-8')
    svc.result_message(a,original,data);svc.result_message(b,original,data)
    assert a['result']!=b['result']
    assert json.loads(original.read_text(encoding='utf-8'))==data
