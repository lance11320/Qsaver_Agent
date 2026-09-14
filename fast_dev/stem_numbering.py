"""Remove explicit source-question labels, preserving scientific numbers and subparts."""
import re

GROUP=re.compile(r'^\s*【\s*(?:题组\s*\d+\s*[-—–~至]\s*\d+|\d+\s*[-—–~至]\s*\d+\s*为题[组目])\s*】[ \t]*')
LABEL=re.compile(r'^(?P<space>[ \t]*)(?:第\s*(?P<cn>\d{1,3})\s*题\s*[:：.．、]?|(?P<plain>\d{1,3})\s*[.．、](?!\d))[ \t]*')

def clean_stem(stem,number=None):
    if not isinstance(stem,str):return stem
    text=GROUP.sub('',stem,count=1)
    expected=str(number or '').strip().rstrip('.．、')
    lines=text.splitlines(keepends=True)
    for i,line in enumerate(lines):
        match=LABEL.match(line)
        if not match:continue
        found=match['cn'] or match['plain']
        # Away from the start, only remove an exact known source number, once.
        if (expected and found!=expected) or (i>0 and (not expected or text==stem)):continue
        remainder=line[match.end():]
        if not remainder.strip():continue
        lines[i]=match['space']+remainder
        break
    return ''.join(lines)

def display_stem(q):
    return clean_stem(q.get('stem',''),q.get('number') or q.get('agent_source',{}).get('number') or q.get('original_number'))

def normalize(q):
    before=q.get('stem','');after=display_stem(q)
    if before!=after:
        if not q.get('number') and not q.get('agent_source',{}).get('number'):
            label=LABEL.match(GROUP.sub('',before,count=1))
            if label:q.setdefault('original_number',label['cn'] or label['plain'])
        q['stem']=after
    return q
