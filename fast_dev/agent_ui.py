"""Miniscope-inspired conversational entry point for the document agent."""
from pathlib import Path
import gradio as gr
from chat_service import rpc

ASSETS=Path(__file__).parent/'chat_assets'

def build_panel():
    return gr.HTML(html_template=(ASSETS/'chat.html').read_text(encoding='utf-8-sig'),css_template=(ASSETS/'chat.css').read_text(encoding='utf-8-sig'),js_on_load=(ASSETS/'chat.js').read_text(encoding='utf-8-sig'),server_functions=[rpc],apply_default_css=False,elem_id='document-agent-panel')
