"""Shared compact sidebar, routing to existing Gradio workbench views."""
import gradio as gr

SHELL_CSS='''
body{background:#fff!important}
.gradio-container{width:100%!important;margin:0!important;max-width:none!important;padding:12px 20px 0 224px!important;background:#fff!important;transition:padding-left .2s}
body.qs-sidebar-collapsed .gradio-container{padding-left:80px!important}
#main-tabs{border:0!important;padding:0!important;background:transparent!important}
#main-tabs > .tab-wrapper,#main-tabs > div[role="tablist"],#main-tabs > .tab-nav{display:none!important}
#main-tabs > .tabitem{border:0!important;padding:0!important;background:transparent!important}
#view-nav,#topbar{display:none!important}
#ai-select-view{order:0}#db-view{order:1}
#workbench-panel button{transition:transform .2s,box-shadow .2s!important;border-radius:18px!important}#workbench-panel button:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 8px 18px #8b5cf621}
#document-agent-panel{padding:0!important;border:0!important}
#qs-sidebar{position:absolute!important;width:0!important;height:0!important;min-height:0!important;overflow:visible!important;padding:0!important;margin:0!important}
#qs-sidebar .html-container,#document-agent-panel .html-container{padding:0!important}
.gradio-container>.main{padding:0!important}.gradio-container>.main>.wrap{padding:0!important}
.gradio-container>footer{display:none!important}
#document-agent-panel footer.review-bottom{display:flex!important}
@media(max-width:800px){.gradio-container{padding:8px 8px 0 72px!important}body.qs-sidebar-collapsed .gradio-container{padding-left:72px!important}}
'''

def build_sidebar():
    return gr.HTML(value="agent",html_template='''<aside class="qs-side" aria-label="主导航"><div class="side-top"><button id="qs-toggle" title="展开 / 收起侧栏" aria-label="展开或收起侧栏">☰</button><strong class="side-label">Qsaver<span>题库工作台</span></strong></div><div class="side-section side-label">工作空间</div><nav><button class="side-link " data-view="entry" title="单题录入"><span>⊞</span><span class="side-label">单题录入</span></button><button class="side-link " data-view="batch" title="多题入库"><span>▤</span><span class="side-label">多题入库</span></button><button class="side-link " data-view="selection" title="选题导出"><span>◇</span><span class="side-label">选题导出</span></button><button class="side-link active" data-view="agent" title="题库Co-pilot"><span>✦</span><span class="side-label">题库Co-pilot</span></button></nav><div class="side-foot"><i></i><span class="side-label">本地工作区 <small>FAST DEV</small></span></div></aside>''',css_template='''
.qs-side{font:16px/1.5 var(--font, "Montserrat", ui-sans-serif, system-ui, sans-serif);position:fixed;inset:12px auto 12px 12px;width:196px;z-index:40;background:#f6f7fb;border:1px solid #e6e8ef;border-radius:18px;display:flex;flex-direction:column;overflow:hidden;transition:width .2s;color:#475569}.side-top{height:81px;display:flex;align-items:center;gap:9px;padding:0 10px;flex-shrink:0}.side-top button{border:0;background:transparent;font-size:19px;color:#7b8a7e;padding:8px;cursor:pointer}.side-top strong{font-size:19px;font-weight:600;letter-spacing:-.03em;color:#1e293b}.side-top strong span{display:block;font-size:9px;font-weight:400;letter-spacing:.13em;color:#99a596;margin-top:1px}.side-section{font-size:9px;letter-spacing:.12em;color:#a3afa0;padding:20px 19px 10px}.qs-side nav{padding:0 10px;display:grid;gap:5px}.side-link{display:flex;gap:12px;align-items:center;white-space:nowrap;width:100%;border:0;border-radius:18px;padding:12px 13px;background:transparent;color:#64748b;text-align:left;cursor:pointer;font-size:16px}.side-link{font-size:18px}.side-link>span:first-child{font-size:18px;width:19px;text-align:center}.side-link{transition:transform .2s,box-shadow .2s,background .2s}.side-link:hover{transform:translateY(-2px);box-shadow:0 7px 15px #8b5cf61c;background:#ede9fe}.side-link.active{background:#eee8ff;color:#8855ee;font-weight:600}.side-foot{display:flex;align-items:center;gap:9px;margin:auto 16px 22px;font-size:10px;white-space:nowrap;color:#a1ad9a}.side-foot i{width:6px;height:6px;border-radius:50%;background:#8b5cf6}.side-foot small{display:block;font-size:8px;letter-spacing:.12em;color:#b7c0b2}.qs-side.collapsed{width:54px}.qs-side.collapsed .side-label{display:none}.qs-side.collapsed .side-top{padding:0 3px}.qs-side.collapsed nav{padding:0 5px}.qs-side.collapsed .side-link{padding:10px 11px}.qs-side.collapsed .side-foot{margin:auto auto 22px}@media(max-width:800px){.qs-side{width:50px;inset:8px auto 8px 8px}.qs-side .side-label{display:none}.qs-side .side-top{padding:0 2px}.qs-side nav{padding:0 3px}.qs-side .side-link{padding:10px}.qs-side .side-foot{margin:auto auto 22px}}
''',js_on_load='''
const side=element.querySelector('.qs-side');
element.querySelector('#qs-toggle').onclick=()=>{const closed=side.classList.toggle('collapsed');document.body.classList.toggle('qs-sidebar-collapsed',closed);};
element.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{props.value=b.dataset.view;trigger('change');element.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));});
''',apply_default_css=False,elem_id='qs-sidebar')
