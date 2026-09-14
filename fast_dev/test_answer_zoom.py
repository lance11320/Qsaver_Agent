import copy
from pathlib import Path
import fitz
import pytest
import answer_zoom as zoom

def test_reading_requires_number_count_and_complete():
    good={'number':'38','characters':list('TTFT'),'complete':True}
    assert zoom.value(good,'38',4)=='TTFT'
    assert zoom.value(good,'39',4) is None
    assert zoom.value(good,'38',3) is None
    assert zoom.value(dict(good,characters=list('T?FT')),'38',4) is None
    assert zoom.value(dict(good,complete=False),'38',4) is None
    adjacent=dict(good,number='39',characters=list('TFTF'))
    assert zoom.value([adjacent,good],'38',4)=='TTFT'
    assert zoom.value([good,good],'38',4) is None

def test_batch_omission_retries_only_missing_image(tmp_path,monkeypatch):
    calls=[]
    def cached(client,prompt,images,folder):
        calls.append(images)
        return {'id':images[0][0],'number':'38','characters':list('TTFT'),'complete':True}
    monkeypatch.setattr(zoom,'cached',cached)
    result=zoom.read_crops(object(),[('one','a.png'),('two','b.png')],tmp_path)
    assert set(result)=={'one','two'} and calls[1]==[('two','b.png')]

def test_invalid_crop_and_preserved_resolution(tmp_path):
    with fitz.open() as doc:
        doc.new_page(width=200,height=300)
        with pytest.raises(ValueError):zoom.crop_line(doc,1,[0,0,1000,1000],tmp_path,'x')
        raw,enhanced=zoom.crop_line(doc,1,[100,100,600,130],tmp_path,'valid')
    from PIL import Image
    with Image.open(raw) as a,Image.open(enhanced) as b:
        assert a.size==b.size and a.width>=400

def question():
    return {'number':'38','stem':'判断正误','options':['a','b','c','d'],'answer':'TFFT',
            'answer_source':{'source_file':'answer.pdf','source_pages':[5]},'review_flags':['答案复核不一致']}

def test_zoom_corrects_only_matching_local_readings(tmp_path,monkeypatch):
    monkeypatch.setattr(zoom,'page_answers',lambda *a:{'38':{'confirmed':True,'answer':'TTFT','readings':['TTFT','TTFT']}})
    q=question();zoom.verify([q],object(),tmp_path)
    assert q['answer']=='TTFT' and q['review_flags']==[]
    assert q['answer_replacement_history'][0]['answer']=='TFFT'

def test_conflicting_local_views_block_even_if_page_agrees(tmp_path,monkeypatch):
    monkeypatch.setattr(zoom,'page_answers',lambda *a:{'38':{'confirmed':False,'answer':'','readings':['TTFT','TFFT']}})
    q=question();q['review_flags']=[];zoom.verify([q],object(),tmp_path)
    assert q['answer']=='TFFT' and zoom.FLAG in q['review_flags']

def test_localization_failure_blocks(tmp_path,monkeypatch):
    monkeypatch.setattr(zoom,'page_answers',lambda *a:{})
    q=question();zoom.verify([q],object(),tmp_path)
    assert not q['answer_zoom_review']['confirmed'] and zoom.FLAG in q['review_flags']

def test_continued_solution_recovers_printed_answer_page(tmp_path,monkeypatch):
    import agent
    q=question()
    solutions=[{'source_file':'answer.pdf','page_images':['4.png','5.png']}]
    class Client:
        workers=1
        def chat(self,prompt,images):
            return {'answers':[{'number':'38','answer':'TTFT'}]} if images==['4.png'] else {'answers':[]}
    captured=[]
    monkeypatch.setattr(zoom,'verify',lambda qs,*args:captured.extend(qs[0]['answer_source']['source_pages']))
    agent.verify_answers([q],solutions,Client(),tmp_path)
    assert captured==[4,5]
    assert q['answer_source']['original_source_pages']==[5]
    assert q['answer']=='TFFT'  # page audit locates; only subsequent zoom may change the answer

@pytest.mark.parametrize('second_answer,confirmed',[('TTFT',True),('TFFT',False)])
def test_band_fallback_requires_consistent_views(tmp_path,monkeypatch,second_answer,confirmed):
    pdf=tmp_path/'source.pdf'
    with fitz.open() as doc:
        doc.new_page();doc.save(pdf)
    calls=[]
    def read(client,images,folder):
        calls.append(images)
        answer='TTFT' if len(calls)==1 else second_answer
        return {'band_0':[{'number':'38','complete':True,'characters':list('TTFT')}],
                'band_1':[{'number':'38','complete':True,'characters':list(answer)}]}
    monkeypatch.setattr(zoom,'read_crops',read)
    result=zoom.read_bands(pdf,1,{'38':4},object(),tmp_path)
    assert result['38']['confirmed'] is confirmed
    assert len(calls)==2 and len(calls[0])==5
