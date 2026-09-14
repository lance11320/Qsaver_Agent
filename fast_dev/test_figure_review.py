import json
import fitz
import pytest
import figure_review as review

def setup_result(tmp_path,monkeypatch):
    monkeypatch.setattr(review.agent,'ROOT',tmp_path)
    doc=fitz.open();p=doc.new_page(width=300,height=400);p.draw_rect(fitz.Rect(60,90,230,250));pdf=tmp_path/'test.pdf';doc.save(pdf);doc.close()
    run=tmp_path/'runs'/'test';run.mkdir(parents=True)
    q={'source_file':str(pdf),'source_hash':'abc','number':'1','stem':'如图所示','options':[],'source_pages':[1],'page_images':[], 'has_figures':True,'figures':[{'page':1,'bbox':[150,200,850,700]}],'review_flags':['题图待视觉复核','答案冲突'],'media_errors':[]}
    path=run/'result.json';path.write_text(json.dumps({'questions':[q]}),encoding='utf-8')
    return path,q

def test_confirm_keeps_answer_flags_and_original(tmp_path,monkeypatch):
    path,q=setup_result(tmp_path,monkeypatch);before=path.read_bytes()
    out,data=review.save_review(path,0,review.identity(q),'confirm',[])
    saved=data['questions'][0]
    assert saved['review_flags']==['答案冲突']
    assert (tmp_path/saved['image']).exists()
    assert saved['image'].startswith('images/')
    assert path.read_bytes()==before
    assert saved['figure_review']['status']=='confirmed'

def test_no_figure_clears_images_and_rejects_stale(tmp_path,monkeypatch):
    path,q=setup_result(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='变化'):review.save_review(path,0,'bad','none',[])
    out,data=review.save_review(path,0,review.identity(q),'none',[])
    assert data['questions'][0]['images']==[]
    assert data['questions'][0]['review_flags']==['答案冲突']

def test_multiple_boxes_and_invalid_page(tmp_path,monkeypatch):
    path,q=setup_result(tmp_path,monkeypatch)
    with pytest.raises(ValueError):review.save_review(path,0,review.identity(q),'replace',[{'page':2,'bbox':[100,100,500,500]}])
    regs=[{'page':1,'bbox':[100,200,400,500]},{'page':1,'bbox':[500,200,900,500]}]
    out,data=review.save_review(path,0,review.identity(q),'replace',regs)
    assert len(data['questions'][0]['figure_assets'])==2
    assert len(data['questions'][0]['images'])==1
    assert review.draw_page(q,1,regs).size==(540,784)

def test_suspected_missing_figures():
    assert review.suspected({'stem':'结果如下图所示'})
    assert review.suspected({'media_errors':['未定位']})
    assert not review.suspected({'stem':'选择正确的答案'})
