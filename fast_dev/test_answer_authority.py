import answer_authority as a

def test_question_handwriting_is_not_a_solution():
    docs=[{'file':'questions.pdf','plan':{'role':'questions'}},{'file':'answers.pdf','plan':{'role':'solutions'}}]
    q={'kind':'question','source_file':'questions.pdf','source_pages':[1],'answer':'ACD','explanation':'手写'}
    fake=dict(q,kind='solution');formal=dict(q,kind='solution',source_file='answers.pdf',answer='TFTT')
    kept=a.sanitize([q,fake,formal],docs)
    assert len(kept)==2 and q['answer']==''
    a.assign(q,formal)
    assert q['answer']=='TFTT' and q['answer_source']['source_file']=='answers.pdf'

def test_tf_shape_and_length_not_guessed_from_choices():
    q={'stem':'判断下列说法正误','options':['a','b','c','d'],'answer':'ACD'}
    assert a.format_flags(q) and q['answer']=='ACD'
    q['answer']='t f t t';assert not a.format_flags(q) and q['answer']=='TFTT'
    q['answer']='TFT';assert a.format_flags(q)
    assert not a.format_flags({'stem':'选择正确的选项','answer':'ACD','options':['a','b','c','d']})

def test_recovery_never_returns_to_question_file():
    result={'documents':[{'file':'q','group':'x','plan':{'role':'questions'}},{'file':'a','group':'x','plan':{'role':'solutions'}}]}
    assert a.recovery_sources(result,'x',[{'source_file':'q'}])==['a']
    result['documents'].pop()
    assert a.recovery_sources(result,'x',[{'source_file':'q'}])==[]

def test_mixed_document_segments_are_enforced():
    docs=[{'file':'mixed','plan':{'role':'mixed','segments':[{'role':'questions','start_page':1,'end_page':3},{'role':'solutions','start_page':4,'end_page':5}]}}]
    assert not a.authorized({'source_file':'mixed','source_pages':[2]},docs)
    assert a.authorized({'source_file':'mixed','source_pages':[4]},docs)
