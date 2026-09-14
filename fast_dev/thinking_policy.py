"""Bounded task-specific reasoning. Transcription never invents answers."""
from contextvars import ContextVar

VERSION='task-thinking-v2'
TASK=ContextVar('qsaver_thinking_task',default='transcribe')
BUDGETS={'plan':2048,'relationship':2048,'cross_page':3072,'semantic_select':4096,
         'figure_review':2048,'extract_retry':2048,'text_review':8192,'transcribe':0}

def parameters(model, task=None):
    task = task or TASK.get()
    if model.startswith('deepseek') and task=='text_review':
        return {'thinking':{'type':'enabled'},'reasoning_effort':'high'}
    # Non-Qwen compatible endpoints must not receive Qwen-specific parameters.
    if not model.startswith('qwen'):return {}
    budget=BUDGETS.get(task,0)
    return {'enable_thinking':bool(budget),**({'thinking_budget':budget} if budget else {})}

def call(client,prompt,images=(),task='transcribe'):
    token=TASK.set(task)
    try:return client.chat(prompt,images)
    finally:TASK.reset(token)
