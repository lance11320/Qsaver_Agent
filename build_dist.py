"""Create a clean, relocatable Windows distribution from an explicit source allowlist."""
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'fast_dev'
OUT=ROOT/'dist'
MODULES=['Qsaver','agent','agent_ui','chat_service','chat_shell','copilot_tasks',
         'document_map','question_media','figure_refinement','figure_review','network_config','image_policy',
         'bank_versions','teacher_exports','review_workflow','project_storage','bank_cleaning','job_progress','shared_api','thinking_policy','stem_numbering','answer_authority','answer_zoom','text_review','coverage_recovery']

def main():
    if OUT.exists():raise SystemExit('dist already exists; choose a new output or inspect it before rebuilding.')
    app=OUT/'app';runtime=OUT/'runtime';app.mkdir(parents=True);runtime.mkdir()
    for name in MODULES:shutil.copy2(SRC/(name+'.py'),app/(name+'.py'))
    shutil.copytree(SRC/'chat_assets',app/'chat_assets')
    shutil.copy2(SRC/'requirements-lock.txt',OUT/'requirements-lock.txt')
    (app/'qsaver_backend_config.json').write_text(json.dumps({'backend_mode':'远程 API','api_key':'','api_profiles':[]}),encoding='utf-8')
    (app/'questions.json').write_text('[]',encoding='utf-8')
    # A venv executable points to the original machine. Ship the base runtime instead.
    base=Path(sys.base_prefix)
    for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt'):
        if (base/name).exists():shutil.copy2(base/name,runtime/name)
    for name in ('Lib','DLLs','tcl'):
        if (base/name).exists():
            shutil.copytree(base/name,runtime/name,ignore=shutil.ignore_patterns('site-packages','__pycache__','*.pyc'))
    shutil.copytree(SRC/'venv'/'Lib'/'site-packages',runtime/'Lib'/'site-packages',
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc','direct_url.json'))
    (OUT/'start.bat').write_text('@echo off\ncd /d "%~dp0app"\nset PYTHONHOME=\nset PYTHONPATH=\n"%~dp0runtime\\python.exe" -E -s "%~dp0app\\Qsaver.py"\npause\n',encoding='ascii')
    (OUT/'README.txt').write_text('''Qsaver Windows x64 便携版
双击 start.bat 启动。已包含 Python 和依赖，不需要复制开发环境或另外安装 Python。
首次进入模型/API 设置，填写用户自己的 API Key。此包不包含开发者接口配置、题库、项目记录、日志或测试资料。
请将整个 dist 文件夹一起分发，不能只复制 app。当前目录需可写，所有新增题库、附图、版本、项目记录保存在 app 下。
默认使用远程 API；未包含本地大模型、llama-server 或模型权重。
API 设置可保存于用户本地配置。使用后再分发时，应重新运行开发目录的 build_dist.py 生成干净包，不要转发已使用的 app 数据目录。
第三方依赖许可证保留在 runtime 中；依赖版本见 requirements-lock.txt。
''',encoding='utf-8-sig')
    # Check literal configured keys without printing them or copying their configuration.
    secrets=[]
    for config in (ROOT/'qsaver_backend_config.json',SRC/'qsaver_backend_config.json'):
        if config.exists():
            cfg=json.loads(config.read_text(encoding='utf-8'))
            secrets += [cfg.get('api_key','')]+[p.get('api_key','') for p in cfg.get('api_profiles',[])]
    secrets=[v.encode() for v in secrets if v and len(v)>8]
    files=list(OUT.rglob('*'));count=0;size=0
    for p in files:
        if not p.is_file():continue
        data=p.read_bytes();count+=1;size+=len(data)
        if any(secret in data for secret in secrets):raise RuntimeError('Credential leak detected in distribution: '+str(p.relative_to(OUT)))
    (OUT/'BUILD_REPORT.json').write_text(json.dumps({'files':count,'bytes':size,'configured_key_matches':0,
        'modules':MODULES,'python':sys.version.split()[0]},indent=2),encoding='utf-8')
    print(json.dumps({'files':count,'megabytes':round(size/1024**2,1),'configured_key_matches':0}))

if __name__=='__main__':main()
