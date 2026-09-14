from PIL import Image,ImageDraw
from figure_refinement import guard_box,map_local_box
from question_media import persist

def test_boundary_protects_cut_ink_without_shrinking():
    im=Image.new('RGB',(100,100),'white');ImageDraw.Draw(im).rectangle((20,20,80,80),fill='black')
    box,check=guard_box(im,[230,230,770,770],max_search=12)
    assert box[0]<200 and box[1]<200 and box[2]>800 and box[3]>800
    assert check['warnings']==[]

def test_clear_edges_do_not_expand_toward_nearby_text():
    im=Image.new('RGB',(100,100),'white');ImageDraw.Draw(im).rectangle((20,20,80,80),fill='black')
    box,check=guard_box(im,[100,100,900,900])
    assert box==[100,100,900,900]
    assert check['warnings']==[]

def test_boundary_search_is_bounded():
    im=Image.new('RGB',(100,100),'black')
    box,check=guard_box(im,[200,200,800,800],max_search=5)
    assert box==[200,200,800,800]
    assert len(check['warnings'])==4

def test_roi_mapping_uses_source_coordinates():
    assert map_local_box([0,0,1000,1000],(100,200,500,600),(1000,2000))==[100,100,500,300]
    assert map_local_box([250,250,750,750],(100,200,500,600),(1000,2000))==[200,150,400,250]

def test_assisted_parts_publish_only_complete_composite(tmp_path):
    evidence=tmp_path/'evidence';evidence.mkdir()
    for name,color in [('a','red'),('b','blue')]:Image.new('RGB',(30,30),color).save(evidence/f'{name}.png')
    assets=[{'image':'evidence/a.png','page':1,'clip_points':[0,0,10,10]}, {'image':'evidence/b.png','page':1,'clip_points':[20,0,30,10]}]
    q={'source_file':'paper.pdf','figures':[{'assisted_crop':True}],'figure_assets':assets}
    media=persist(q,tmp_path,'final')
    assert media['images']==[media['image']]
    assert media['image'].startswith('images/')
    assert len(list((tmp_path/'images').iterdir()))==1
    with Image.open(tmp_path/media['image']) as im:assert im.size==(90,30)

def test_repairs_are_bounded_and_cached(tmp_path,monkeypatch):
    import question_media
    from figure_refinement import assist_question
    def preview(q,root,key):
        Image.new('RGB',(50,50),'white').save(root/'final.png')
        return {'image':'final.png'}
    monkeypatch.setattr(question_media,'enrich',lambda *args:None)
    monkeypatch.setattr(question_media,'persist',preview)
    class Fake:
        def __init__(self,review):self.model=str(review);self.base='test';self.key='secret';self.calls=0;self.review=review
        def chat(self,*args):
            self.calls+=1
            if self.review:return {'pass':False,'issues':['incomplete'],'evidence':'test'}
            return {'figures':[{'bbox':[200,200,800,800]}]}
    source=tmp_path/'0001.png';Image.new('RGB',(200,300),'white').save(source)
    q={'number':'1','source_file':'x.pdf','stem':'test','figures':[{'page':1,'bbox':[200,300,800,800]}]}
    c,r=Fake(False),Fake(True)
    figures,audit=assist_question(q,source,c,r,tmp_path/'work',max_repairs=2)
    assert not audit['accepted'] and len(audit['rounds'])==3
    assert c.calls<=2 and r.calls<=3
    previous=(c.calls,r.calls)
    assist_question(q,source,c,r,tmp_path/'work',max_repairs=2)
    assert (c.calls,r.calls)==previous
