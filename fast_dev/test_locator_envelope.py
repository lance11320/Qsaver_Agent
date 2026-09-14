import pytest
import text_review as tr

B=[10,20,200,300]

@pytest.mark.parametrize('obj',[
    {'regions':[{'page':7,'bbox':B}]},
    [{'page':7,'bbox':B}],
    {'page':7,'bbox':B},
    [{'regions':[{'page':7,'bbox':B}]}],
    [{'page_name':'第7页','bbox_2d':B}],
    [{'page':'7','page_name':'第7页','bbox':B,'bbox_2d':B}],
    [{'bbox':B}],
])
def test_known_envelopes_preserve_coordinates(obj):
    result=tr.located_regions(obj,[7])
    assert result==[{'page':7,'bbox':B}]
    assert result[0]['bbox'] is B

@pytest.mark.parametrize('obj,pages',[
    ([{'page':'99','bbox':B}],[7]),
    ([{'page':'7/99','bbox':B}],[7,8]),
    ([{'page':7,'page_name':'第8页','bbox':B}],[7,8]),
    ([{'page':None,'bbox':B}],[7]),
    ([{'page':True,'bbox':B}],[1]),
    ([{'page_':99,'bbox':B}],[7]),
    ([{'bbox':B}],[7,8]),
    ([{'regions':[{'regions':[{'page':7,'bbox':B}]}]}],[7]),
    ({'regions':[]},[7]),
    ({'regions':'bad'},[7]),
    ([{'page_7':{'regions':[]}}],[7]),
    ([{'page':7,'bbox':B,'bbox_2d':[1,2,3,4]}],[7]),
    ([{'page':7,'bbox':B}]*3,[7]),
    ([{'page':7,'bbox':[0,1,float('nan'),3]}],[7]),
    ([{'page':7,'bbox':[0,1,1001,3]}],[7]),
    ([{'page':7,'bbox':[False,1,2,3]}],[7]),
    ([{'page':7,'bbox':[2,1,0,3]}],[7]),
])
def test_invalid_or_ambiguous_results_still_fail(obj,pages):
    with pytest.raises(ValueError):tr.located_regions(obj,pages)

def test_zoom_uses_bare_locator_and_does_not_change_matching_text(tmp_path,monkeypatch):
    import fitz
    source=tmp_path/'source.pdf'
    with fitz.open() as doc:
        doc.new_page();doc.save(source)
    calls=[]
    def request(client,prompt,images,folder):
        calls.append(prompt)
        if len(calls)==1:return [{'page':1,'bbox':B}]
        return {'number':'1','option_label':'A','text':'原文','complete':True}
    monkeypatch.setattr(tr,'request',request)
    q={'source_file':str(source),'source_pages':[1],'number':'1','options':['A.原文']}
    result=tr.zoom_field(q,'options[0]','原文',object(),tmp_path/'crop')
    assert result['status']=='unchanged' and len(calls)==2
