import json
import pytest
from PIL import Image
from question_media import persist,validate_regions,locate_figures
from document_map import link_documents,validate_map,save_reviewed

def record(id,role,title='试卷一',count=40):
    return dict(id=id,sha256=id*32,status='ready',role=role,title=title,last_question_number=count,path=id+'.pdf',pages=10)

def test_matching_requires_title_and_unique_answer():
    q=record('q','questions');a=record('a','solutions','试卷一答案');b=record('b','solutions','试卷二答案')
    link_documents([q,a,b])
    assert q['paper_id']==a['paper_id']!=b['paper_id']
    c=record('c','solutions','试卷一参考答案')
    link_documents([q,a,c])
    assert q['relationship_status']=='needs_review'
    assert q['paper_id']!=a['paper_id']

def test_review_cannot_change_source(tmp_path):
    data={'schema_version':1,'documents':link_documents([record('q','mixed')])}
    p=tmp_path/'map.json';p.write_text(json.dumps(data),encoding='utf-8')
    data['documents'][0]['path']='different.pdf'
    with pytest.raises(ValueError):save_reviewed(p,json.dumps(data))
    data['documents'][0]['segments']=[{'start_page':1,'end_page':11}]
    with pytest.raises(ValueError):validate_map(data)

def test_no_page_screenshot_as_figure(tmp_path):
    p=tmp_path/'page.png';Image.new('RGB',(100,100)).save(p)
    media=persist({'source_file':'x.pdf','page_images':[str(p)]},tmp_path,'key')
    assert media['image']=='' and media['images']==[] and media['source_images']
    assert locate_figures([],tmp_path,tmp_path)==[]

def test_missing_figure_blocks_save(tmp_path):
    with pytest.raises(ValueError):persist({'figure_assets':[{'image':'images/missing.png'}]},tmp_path,'key')

def test_panels_preserve_relative_layout(tmp_path):
    (tmp_path/'images').mkdir()
    for name,color in [('a','red'),('b','blue')]:Image.new('RGB',(30,30),color).save(tmp_path/'images'/f'{name}.png')
    assets=[dict(image='images/a.png',page=1,clip_points=[0,0,10,10]),dict(image='images/b.png',page=1,clip_points=[20,10,30,20])]
    result=persist({'figure_assets':assets},tmp_path,'layout')
    with Image.open(tmp_path/result['image']) as im:
        assert im.size==(90,60)
        assert im.getpixel((1,1))==(255,0,0)
        assert im.getpixel((61,31))==(0,0,255)
        assert im.getpixel((40,20))==(255,255,255)

def test_invalid_figure_region():
    with pytest.raises(ValueError):validate_regions([{'page':1,'bbox':[900,0,1100,200]}],[1])
    with pytest.raises(ValueError):validate_regions([{'page':2,'bbox':[0,0,200,200]}],[1])

def test_token_plan_selected_despite_saved_model_label(monkeypatch):
    import agent
    monkeypatch.setattr(agent,'config',lambda:{'api_key':'ordinary','api_profiles':[{'name':'plan','base_url':'https://token-plan.example/v1','model_name':'unrelated','api_key':'plan-key'}]})
    for env in ('DASHSCOPE_API_KEY','QSAVER_API_KEY','QSAVER_API_BASE_URL','QSAVER_API_PROFILE'):monkeypatch.delenv(env,raising=False)
    assert agent.Client('qwen3.8-max').key=='plan-key'
    assert agent.Client('qwen3-vl-plus').key=='ordinary'
    assert agent.Client('qwen3.7-plus').key=='plan-key'

def test_locator_cache_tracks_prompt_and_model(tmp_path,monkeypatch):
    import agent
    calls=[]
    class Fake:
        def __init__(self,model):self.model=model;self.base='https://example.test';self.usage=[]
        def chat(self,prompt,images):calls.append(prompt);return {'items':[{'number':'1','figures':[]}]}
    monkeypatch.setattr(agent,'Client',Fake)
    im=tmp_path/'0001.png';Image.new('RGB',(100,150),'white').save(im)
    q={'source_file':'x.pdf','source_hash':'h','page_images':[str(im)],'number':'1','stem':'A'}
    locate_figures([q],tmp_path,tmp_path,progress=lambda s:None,model='one')
    locate_figures([q],tmp_path,tmp_path,progress=lambda s:None,model='one')
    assert len(calls)==1
    q['stem']='B'
    locate_figures([q],tmp_path,tmp_path,progress=lambda s:None,model='one')
    locate_figures([q],tmp_path,tmp_path,progress=lambda s:None,model='two')
    assert len(calls)==3

def test_source_pages_saved_outside_figures_directory(tmp_path):
    p=tmp_path/'0001.png';Image.new('RGB',(100,100)).save(p)
    m=persist({'source_file':'x.pdf','page_images':[str(p)]},tmp_path,'test')
    assert m['source_images'][0].startswith('evidence/')
    assert not list((tmp_path/'images').iterdir())

def test_group_labels_do_not_automatically_duplicate_figures(tmp_path):
    from question_media import enrich
    owner={'source_file':'x.docx','source_hash':'h','number':'23','figures':[{'page':1,'bbox':[0,0,200,200],'shared_with':['24']}]}
    target={'source_file':'x.docx','source_hash':'h','number':'24','figures':[]}
    enrich([owner,target],tmp_path)
    assert target['figures']==[]
    assert any('共享' in m for m in owner['media_errors'])
def test_short_continuation_region_is_not_a_tiny_figure():
    import pytest
    from question_media import validate_regions
    region=[{'page':5,'bbox':[80,100,900,110]}]
    validate_regions(region,[5],minimum_span=1)
    with pytest.raises(ValueError):validate_regions(region,[5])
