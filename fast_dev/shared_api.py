"""One active remote API configuration for the workbench and Co-pilot."""
import agent

REGIONS={'China / Beijing':'https://dashscope.aliyuncs.com/compatible-mode/v1',
         'Singapore / International':'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
         'US / Virginia':'https://dashscope-us.aliyuncs.com/compatible-mode/v1',
         'Hong Kong':'https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1'}

def active(model=None):
    cfg=agent.config()
    if 'api_model_name' in cfg:
        return {'model':cfg.get('api_model_name') or agent.DEFAULT_MODEL,
                'base_url':cfg.get('api_base_url') or REGIONS.get(cfg.get('api_region'),REGIONS['China / Beijing']),
                'api_key':cfg.get('api_key','')}
    # Compatibility with older installations that only saved named profiles.
    rows=cfg.get('api_profiles',[])
    p=next((p for p in rows if p.get('model_name')==(model or agent.DEFAULT_MODEL) and p.get('api_key')),None)
    p=p or next((p for p in rows if p.get('api_key')),cfg)
    return {'model':p.get('model_name') or model or agent.DEFAULT_MODEL,
            'base_url':p.get('base_url') or p.get('effective_base_url') or p.get('api_base_url') or REGIONS.get(p.get('region'),REGIONS['China / Beijing']),
            'api_key':p.get('api_key','')}

def save(model,base,key):
    cfg=agent.config()
    cfg.update(backend_mode='远程 API',api_model_name=model,api_base_url=base,api_key=key,save_api_key=True)
    agent.dump(agent.ROOT/'qsaver_backend_config.json',cfg)

def sync(session):
    current=active(session['settings'].get('model'))
    if not session.get('busy'):
        session['settings'].update(model=current['model'],profile='auto',base_url=current['base_url'])
        session['settings'].pop('api_key',None)
    return current
