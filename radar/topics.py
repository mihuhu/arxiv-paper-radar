from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

TOPICS = [
    {'id':'tool-abuse','name':'工具越权','description':'权限边界、工具滥用与工具投毒','terms':['unauthorized tool','tool misuse','privilege escalation','excessive agency','confused deputy','tool poisoning','permission','authorization','unauthorized access'], 'keywords':['Tool Use Security','Prompt Injection']},
    {'id':'agent-security','name':'智能体安全','description':'提示注入、劫持与多智能体安全','terms':['prompt injection','agent security','agent safety','agent hijacking','multi-agent attack','tool poisoning','mcp security','agentic security','agent attack'], 'keywords':['Multi-Agent Security','Prompt Injection']},
    {'id':'distillation','name':'蒸馏检测','description':'模型指纹、溯源与未授权蒸馏','terms':['distillation detection','unauthorized distillation','antidistillation','anti-distillation','model provenance','model lineage','model fingerprinting','llm fingerprinting','language model fingerprinting','fingerprinting of large language models','model stealing','ownership verification','independence tests for language models','radioactive','distillation-aware','black-box model extraction'], 'keywords':['Knowledge Distillation Detection','Model Provenance Testing','Fingerprinting']},
    {'id':'watermark','name':'模型与文本水印','description':'生成文本水印、检测与迁移','terms':['watermark','watermarking','radioactive'], 'keywords':['Watermarking']},
    {'id':'agent-watermark','name':'智能体水印','description':'轨迹、行为与工具调用水印','terms':['agent watermark','agent watermarks','agent watermarking','trajectory watermarking','behavioral watermarking','behavioral watermark','watermarking llm agents','watermarking for llm agents','provenance for llm agents','agent fingerprinting'], 'keywords':['Agent Watermarking']},
]
BY_ID = {t['id']:t for t in TOPICS}
CONTEXT = ['language model','language models','llm','llms','gpt','agent','agents','agentic']

def _hits(text, terms):
    return [term for term in terms if re.search(r'(?<![a-z])'+re.escape(term)+r'(?![a-z])', text)]

def classify(paper):
    title = paper.get('title','').lower(); abstract = paper.get('abstract','').lower()
    text = title+' '+abstract
    context = _hits(text, CONTEXT)
    topics=[]; reasons=[]; scores=[]
    for topic in TOPICS:
        hits = _hits(text, topic['terms'])
        if not hits or not context: continue
        if topic['id']=='agent-watermark' and not _hits(text,['agent','agents','agentic','trajectory','trajectories','tool calls']): continue
        if topic['id']=='watermark' and not _hits(text,['language model','language models','llm','llms','text','token','tokens','chatbot','trajectory','trajectories','behavioral watermarking']): continue
        if topic['id']=='tool-abuse' and not _hits(text,['tool','tools','agent','agents','agentic','mcp']): continue
        topics.append(topic['id'])
        reasons.append(topic['name']+'：'+', '.join(hits[:5]))
        scores.append(min(95, 35+15*len(_hits(title,topic['terms']))+8*len(hits)))
    return {'topics':topics,'score':max(scores,default=0),'reasons':reasons}

def _field(term):
    return f'(ti:"{term}" OR abs:"{term}")'

def build_query(topic_id, start_date=None, end_date=None):
    if topic_id not in BY_ID: raise ValueError('未知主题')
    topic = BY_ID[topic_id]
    terms = ' OR '.join(_field(t) for t in topic['terms'])
    context = ' OR '.join(_field(t) for t in CONTEXT)
    query = f'({terms}) AND ({context})'
    if start_date and end_date:
        tz=ZoneInfo('Asia/Shanghai')
        begin=datetime.fromisoformat(start_date).replace(tzinfo=tz).astimezone(timezone.utc)
        end=(datetime.fromisoformat(end_date)+timedelta(days=1)).replace(tzinfo=tz).astimezone(timezone.utc)-timedelta(minutes=1)
        if begin>end: raise ValueError('日期范围无效')
        query+=f' AND submittedDate:[{begin:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]'
    return query

def keyword_names(paper):
    if 'manual_keywords' in paper: return paper['manual_keywords']
    names=[]
    for tid in paper.get('topics',[]):
        if tid in BY_ID: names.extend(BY_ID[tid]['keywords'])
    return list(dict.fromkeys(names))[:4]
