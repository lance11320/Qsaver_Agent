import base64
import json
from pathlib import Path

import fitz
from PIL import Image
import pytest
import agent
import image_policy
import text_review
import thinking_policy


def test_render_variants_preserve_old_coordinates_and_use_requested_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, 'config', lambda: {})
    pdf = tmp_path/'source.pdf'
    with fitz.open() as doc:
        doc.new_page(width=595, height=842)
        doc.save(pdf)
    pages = tmp_path/'pages'
    pages.mkdir()
    legacy = pages/'0001.png'
    legacy.write_bytes(b'old raster referenced by a saved crop')
    low = agent.prepare(pdf, pages, render_scale=1.8)[0]['images'][0]
    high = agent.prepare(pdf, pages)[0]['images'][0]
    assert low != high and legacy.read_bytes().startswith(b'old raster')
    assert Image.open(low).size == (1071, 1516+64)
    assert Image.open(high).size == (1785, 2526+64)
    assert Path(high).stem == '0001'  # downstream physical-page identification
    assert agent.prepare(pdf, pages)[0]['images'][0] == high


@pytest.mark.parametrize('model', ['qwen3.8-flash', 'other-provider-model'])
def test_request_keeps_image_bytes_and_limits_qwen_server_resizing(tmp_path, monkeypatch, model):
    monkeypatch.setattr(agent, 'config', lambda: {'api_key':'test-only'})
    path = tmp_path/'image.png'
    Image.new('RGB', (1786, 2590), 'white').save(path)
    captured = []
    class Response:
        status_code = 200
        def json(self):
            return {'choices':[{'finish_reason':'stop', 'message':{'content':'{"ok":true}'}}]}
    class Transport:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            captured.append(json)
            return Response()
    monkeypatch.setattr(agent.httpx, 'Client', Transport)
    client = agent.Client(model)
    client.chat('read', [path])
    payload = captured[0]
    block = next(b for b in payload['messages'][1]['content'] if b['type']=='image_url')
    assert base64.b64decode(block['image_url']['url'].split(',', 1)[1]) == path.read_bytes()
    if model.startswith('qwen'):
        assert block['max_pixels'] == 5242880
        assert 'max_pixels' not in block['image_url']
        assert payload['vl_high_resolution_images'] is False
    else:
        assert 'max_pixels' not in block and 'vl_high_resolution_images' not in payload
    assert client.usage[0]['image_inputs'][0]['width'] == 1786


def test_review_cache_isolated_by_thinking_and_image_policy(tmp_path, monkeypatch):
    class Client:
        model='qwen3.8-flash'
        base='https://example.invalid/v1'
        image_max_pixels=5242880
        calls=0
        def chat(self, *args):
            self.calls += 1
            return {'attempt': self.calls}
    c = Client()
    def call(): return text_review.request(c, 'same text', [], tmp_path, 'text_review')
    assert call() == call() == {'attempt':1}
    monkeypatch.setitem(thinking_policy.BUDGETS, 'text_review', 2048)
    assert call() == {'attempt':2}
    c.image_max_pixels = 2621440
    assert call() == {'attempt':3}


@pytest.mark.parametrize('model', ['qwen3.8-flash','qwen3.8-max','current'])
def test_explicit_qwen_reviewer_uses_effective_api(monkeypatch, model):
    monkeypatch.setattr(agent, 'config', lambda: {'text_review_model':model})
    class Client:
        model='qwen3.8-max'
        base='https://unsaved.example/v1'
        key='unsaved-test-key'
        usage=[]
    source=Client()
    review=text_review.reviewer(source)
    assert review.model == ('qwen3.8-max' if model=='current' else model)
    assert review.key==source.key and review.base==source.base and review is not source
    assert thinking_policy.parameters(review.model, 'text_review')['thinking_budget']==8192


@pytest.mark.parametrize('cfg', [{'pdf_render_scale':float('nan')}, {'pdf_render_scale':True}, {'qwen_image_max_pixels':999999999}])
def test_invalid_pixel_settings_rejected(cfg):
    with pytest.raises(ValueError): image_policy.settings(cfg)
