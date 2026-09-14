"""Versioned local question bank writes and explicit, conflict-checked rollback."""
import contextlib
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
import agent
from contextvars import ContextVar
READ_VERSION=ContextVar("bank_read_version",default=None)

def read_bank():
    path=agent.ROOT/"questions.json"
    raw=path.read_bytes() if path.exists() else b"[]"
    READ_VERSION.set(hashlib.sha256(raw).hexdigest())
    data=json.loads(raw)
    if not isinstance(data,list):raise ValueError("题库必须是数组")
    return data


def bank_hash():
    p=agent.ROOT/'questions.json'
    return hashlib.sha256(p.read_bytes() if p.exists() else b'[]').hexdigest()

@contextlib.contextmanager
def locked():
    p=agent.ROOT/'questions.lock';fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:yield
    finally:os.close(fd);p.unlink(missing_ok=True)

def snapshot(label):
    bank=agent.ROOT/'questions.json';data=bank.read_bytes() if bank.exists() else b'[]';questions=json.loads(data)
    ident=time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
    folder=agent.ROOT/'bank_versions'/ident;folder.mkdir(parents=True)
    (folder/'questions.json').write_bytes(data)
    assets={};missing=[]
    for q in questions:
        refs=([q['image']] if q.get('image') else [])+(q.get('images') or [])
        for ref in refs:
            source=(agent.ROOT/str(ref).replace('\\','/')).resolve()
            if str(ref) in assets:continue
            if not source.is_file():missing.append(str(ref));continue
            digest=hashlib.sha256(source.read_bytes()).hexdigest();blob=agent.ROOT/'bank_versions'/'assets'/digest
            blob.parent.mkdir(exist_ok=True)
            if not blob.exists():shutil.copy2(source,blob)
            assets[str(ref)]=digest
    meta={'id':ident,'created':time.time(),'label':label,'count':len(questions),'sha256':hashlib.sha256(data).hexdigest(),'assets':assets,'missing_images':missing}
    agent.dump(folder/'metadata.json',meta)
    return meta

def versions():
    items=[]
    for p in (agent.ROOT/'bank_versions').glob('*/metadata.json'):
        m=json.loads(p.read_text(encoding='utf-8'));items.append({k:m[k] for k in ('id','created','label','count','sha256')})
    return sorted(items,key=lambda x:x['created'],reverse=True)

def commit(questions,label='题库修改',already_locked=False,expected=None):
    if not isinstance(questions,list):raise ValueError('题库必须是题目数组')
    with contextlib.nullcontext() if already_locked else locked():
        if expected and expected!=bank_hash():raise ValueError('题库已被其它操作修改，请重新加载后保存')
        snapshot('修改前 · '+label)
        agent.dump(agent.ROOT/'questions.json',questions)
        return snapshot(label)

def rollback(ident,expected):
    if not re.fullmatch(r'\d{8}_\d{6}_[a-f0-9]{8}',ident):raise ValueError('版本编号无效')
    folder=agent.ROOT/'bank_versions'/ident
    meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
    data=(folder/'questions.json').read_bytes()
    if hashlib.sha256(data).hexdigest()!=meta['sha256']:raise ValueError('版本数据校验失败')
    with locked():
        if bank_hash()!=expected:raise ValueError('确认后题库又发生了变化，请重新选择回滚版本')
        restored=[]
        for ref,digest in meta['assets'].items():
            blob=agent.ROOT/'bank_versions'/'assets'/digest
            if not blob.exists() or hashlib.sha256(blob.read_bytes()).hexdigest()!=digest:raise ValueError('版本附图校验失败')
            target=(agent.ROOT/ref.replace('\\','/')).resolve()
            if not target.is_relative_to(agent.ROOT.resolve()):
                if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('工作区外的旧题图已变化，无法自动恢复')
            else:restored.append((blob,target))
        snapshot('回滚前自动保存')
        for blob,target in restored:
            target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_name(target.name+'.restore-'+uuid.uuid4().hex);shutil.copy2(blob,tmp);os.replace(tmp,target)
        agent.dump(agent.ROOT/'questions.json',json.loads(data))
        return snapshot('回滚至 '+ident)
