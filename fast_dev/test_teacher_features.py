import json
import zipfile
from pathlib import Path
import pytest
import agent
import bank_versions as versions
import chat_service as svc
from teacher_exports import export_docx,semantic_select

@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(agent,'ROOT',tmp_path)
    return tmp_path

def test_versions_restore_bank_and_image(workspace):
    from PIL import Image
    (workspace/'images').mkdir();image=workspace/'images'/'a.png'
    Image.new('RGB',(20,20),'red').save(image);original=image.read_bytes()
    v1=versions.commit([{'stem':'旧题','image':'images/a.png'}],'初稿')
    Image.new('RGB',(20,20),'blue').save(image)
    versions.commit([{'stem':'新题'}],'修改')
    versions.rollback(v1['id'],versions.bank_hash())
    assert json.loads((workspace/'questions.json').read_text(encoding='utf-8'))[0]['stem']=='旧题'
    assert image.read_bytes()==original
    assert any(v['label']=='回滚前自动保存' for v in versions.versions())

def test_rollback_rejects_changed_bank(workspace):
    v=versions.commit([{'stem':'a'}]);expected=versions.bank_hash();versions.commit([{'stem':'b'}])
    with pytest.raises(ValueError,match='变化'):versions.rollback(v['id'],expected)
    assert json.loads((workspace/'questions.json').read_text(encoding='utf-8'))[0]['stem']=='b'

def test_docx_has_questions_answers_and_embedded_images(workspace):
    from PIL import Image
    (workspace/'images').mkdir();Image.new('RGB',(200,100),'white').save(workspace/'images'/'figure.png')
    out=export_docx([{'stem':'实验题目','options':['A. 选项一','B. 选项二'],'answer':'A','image':'images/figure.png'}])
    with zipfile.ZipFile(out) as z:
        xml=z.read('word/document.xml').decode();assert '实验题目' in xml and '参考答案与解析' in xml
        assert 'A. A.' not in xml
        assert any(n.startswith('word/media/') for n in z.namelist())

def test_semantic_reads_every_question_without_tags(workspace):
    source=workspace/'bank.json';source.write_text(json.dumps([{'stem':f'光合作用实验 {i}','options':[]} for i in range(25)]),encoding='utf-8')
    class Reader:
        def __init__(self):self.ids=[]
        def chat(self,prompt,images):
            rows=json.loads(prompt.split('题库批次：')[1]);self.ids += [r['id'] for r in rows]
            return {'candidates':[{'id':rows[0]['id'],'score':.9,'reason':'实验检验能量转化'}]}
    client=Reader();selected,report=semantic_select(source,{'count':2,'instruction':'能量转化实验题'},client)
    assert client.ids==list(range(25));assert len(selected)==2
    assert all(q['selection_review']['status']=='pending' for q in selected)

def test_semantic_export_requires_review(workspace):
    p=workspace/'runs'/'s'/'result.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'questions':[{'stem':'a','selection_review':{'status':'pending'}}]}))
    s=svc.session();s['selection_result']=str(p)
    with pytest.raises(ValueError,match='审核'):svc.dispatch({'session':s['id'],'action':'export','kind':'selection'})

def test_archive_restore_delete_preserve_bank(workspace):
    (workspace/'questions.json').write_text('[]')
    s=svc.session();sid=s['id']
    svc.dispatch({'session':sid,'action':'project_manage','project':sid,'decision':'archive'})
    assert next(p for p in svc.project_list() if p['id']==sid)['archived']
    svc.dispatch({'session':sid,'action':'project_manage','project':sid,'decision':'restore'})
    with pytest.raises(ValueError,match='确认'):svc.dispatch({'session':sid,'action':'project_manage','project':sid,'decision':'delete'})
    svc.dispatch({'session':sid,'action':'project_manage','project':sid,'decision':'delete','confirmation':sid})
    assert not (workspace/'copilot_projects'/(sid+'.json')).exists()
    assert (workspace/'questions.json').read_text()=='[]'


def test_stale_workbench_write_is_rejected(workspace):
    versions.commit([{'stem':'first'}]);versions.read_bank();old=versions.READ_VERSION.get()
    versions.commit([{'stem':'concurrent'}])
    with pytest.raises(ValueError,match='修改'):versions.commit([{'stem':'stale'}],expected=old)
    assert versions.read_bank()[0]['stem']=='concurrent'

def test_semantic_group_quotas(workspace):
    p=workspace/'groups.json';p.write_text(json.dumps([{'stem':'a'},{'stem':'b'},{'stem':'c'}]))
    class Reader:
        def chat(self,prompt,images):return {'candidates':[{'id':0,'score':1,'groups':[0],'reason':'第一组'},{'id':1,'score':.9,'groups':[0],'reason':'第一组'},{'id':2,'score':.8,'groups':[1],'reason':'第二组'}]}
    selected,reports=semantic_select(p,{'groups':[{'count':1},{'count':1}],'instruction':'两组各一题'},Reader())
    assert [q['stem'] for q in selected]==['a','c']
    assert [r['shortfall'] for r in reports]==[0,0]

def test_non_image_reference_is_not_sent(workspace):
    from teacher_exports import image_paths
    secret=workspace/'config.json';secret.write_text('{}')
    with pytest.raises(ValueError,match='图片格式'):image_paths({'image':str(secret)})
