"""Stage ETA from completed file-equivalents, never a fabricated whole-job deadline."""
import time
def update(session,event):
    if not isinstance(event,dict):
        session['progress']=str(event);return
    stage=event['stage'];p=session.get('work_progress',{})
    if p.get('stage')!=stage:p={'stage':stage,'started':time.time(),'files':{},'total':event.get('total',0)}
    if 'file' in event:p['files'][event['file']]=event.get('fraction',1)
    p['total']=event.get('total',p['total']);done=sum(p['files'].values());elapsed=time.time()-p['started']
    p['remaining_files']=max(0,p['total']-sum(v>=1 for v in p['files'].values()))
    p['eta_seconds']=round(elapsed/done*(p['total']-done)) if done>0 and elapsed>=2 else None
    session['work_progress']=p
    if event.get('text'):session['progress']=event['text']
