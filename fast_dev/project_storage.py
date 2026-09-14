"""Durable uploads and bounded regenerable previews; project results are never cache."""
import shutil
import time
from pathlib import Path
import agent


def retain_uploads(paths, project):
    retained=[]
    for path in paths:
        source=Path(path)
        target=agent.ROOT/'project_sources'/project/agent.digest(source)[:20]/source.name
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copy2(source,target)
        retained.append(str(target.resolve()))
    return retained


def trim_previews(max_bytes=512*1024*1024, max_age_days=7):
    """Only evict reproducible page previews, never source files, crops or review results."""
    root=(agent.ROOT/'review_ui').resolve()
    if not root.is_dir() or root.is_symlink():return {'files':0,'bytes':0}
    files=[]
    for p in root.rglob('*'):
        if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root):
            stat=p.stat();files.append((stat.st_mtime,stat.st_size,p))
    total=sum(size for _,size,_ in files);removed=freed=0
    for modified,size,path in sorted(files):
        if total<=max_bytes and modified>=time.time()-max_age_days*86400:continue
        try:path.unlink()
        except OSError:continue
        total-=size;freed+=size;removed+=1
    return {'files':removed,'bytes':freed}
