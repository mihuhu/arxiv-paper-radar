import fcntl
import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
import yaml
from radar.arxiv import normalize_id
from radar.topics import BY_ID, keyword_names

LOCK=threading.Lock()

def safe_name(value,limit=110):
    original=str(value).strip()
    cleaned=re.sub(r'[\\/:*?"<>|\[\]#^\x00-\x1f]','_',original).strip(' .')
    if not cleaned: cleaned='untitled'
    changed=cleaned!=original or len(cleaned)>limit
    return cleaned[:limit]+('-'+hashlib.sha256(original.encode()).hexdigest()[:8] if changed else '')

def frontmatter(text):
    if not text.startswith('---\n'): return {}
    parts=text.split('---',2)
    if len(parts)<3: return {}
    try:
        data=yaml.safe_load(parts[1]); return data if isinstance(data,dict) else {}
    except yaml.YAMLError: return {}

def digest(content): return hashlib.sha256(content).hexdigest()

class Vault:
    def __init__(self,root,backup_root):
        self.root=Path(root).expanduser().resolve()
        if not self.root.is_dir(): raise ValueError('Obsidian 目录不存在，请在设置中选择现有库')
        self.backup_root=Path(backup_root)
    def checked(self,rel):
        p=self.root/rel
        if p.resolve()!=p.absolute() or not p.resolve().is_relative_to(self.root): raise ValueError('目标目录含符号链接或越出库目录')
        return p
    def existing(self):
        result={}; folder=self.checked('03-literature/papers')
        if folder.exists():
            for p in folder.rglob('*.md'):
                if p.is_symlink() or not p.resolve().is_relative_to(self.root): continue
                data=frontmatter(p.read_text(encoding='utf-8'))
                for value in [data.get('arxiv'),data.get('arxiv_url')]:
                    if not value: continue
                    try: result[normalize_id(value)]=str(p); break
                    except ValueError: pass
        return result
    def note_path(self,p):
        pid=normalize_id(p['id']).replace('/','-')
        slug=re.sub(r'[^a-z0-9]+','-',p['title'].lower()).strip('-')[:65] or 'paper'
        return self.checked(f'03-literature/papers/arxiv-{pid}-{slug}.md')
    def preview(self,papers,queue=False):
        existing=self.existing(); items=[]
        for p in papers:
            pid=normalize_id(p['id']); path=Path(existing[pid]) if pid in existing else self.note_path(p)
            exists=pid in existing or path.exists()
            reason='已存在，保留原笔记' if exists else ('新增待讨论论文' if queue else '新增参考论文')
            if exists:
                text=path.read_text(); meta=frontmatter(text)
                versions=re.findall(r'v(\d+)',str(meta.get('arxiv',''))+' '+str(meta.get('arxiv_url','')))
                versions+=re.findall(r'（v(\d+)）',text)
                known=max(map(int,versions)) if versions else None
                if known and p['version']>known: reason=f"发现 v{p['version']} 更新（库内 v{known}），保留原笔记"
                elif not known and p['version']>1: reason=f"缓存版本 v{p['version']}；原笔记未记录版本，保留原笔记"
            items.append({'id':pid,'title':p['title'],'path':str(path),'action':'skip' if exists else 'create',
                'reason':reason})
        return {'vault_path':str(self.root),'items':items,'warnings':[]}
    def note(self,p,queue):
        date=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        authors=[f"[[04-authors/{safe_name(a['name'])}|{a['name'].replace('|',' ')}]]" for a in p['authors']]
        keywords=[f'[[05-keywords/{safe_name(k)}|{k}]]' for k in keyword_names(p)]
        directions=[BY_ID[t]['name'] for t in p.get('topics',[]) if t in BY_ID]
        data={'type':'literature-note','topic':'mihuhu-paper','status':'reference','discussion_status':'待讨论' if queue else '参考论文',
            'arxiv':normalize_id(p['id']),'year':int(p['published'][:4]),'created':date,'paper_title':p['title'],'short_title':p['title'],
            'first_author':authors[0] if authors else None,'authors':authors,'arxiv_url':p['url'],'pdf_url':p['pdf_url'],
            'project_url':None,'code_url':None,'venue':None,'primary_direction':directions[0] if directions else None,
            'directions':directions,'primary_task':None,'tasks':[],'keywords':keywords,'methods':[],'datasets':[],'metrics':[],
            'related_papers':[],'relation_types':[],'world_model_role':None,'summary':None,'open_questions':[]}
        info=[f"- arXiv：[原文]({p['url']})（v{p['version']}）",f"- PDF：[下载]({p['pdf_url']})",f"- 作者：{', '.join(a['name'] for a in p['authors'])}",
            '- 单位：'+('；'.join(p.get('institutions',[])) or '待核实'),'- 单位核验：'+p.get('affiliation_status','待核实'),
            f"- 发布日期：{p['published'][:10]}",f"- 更新日期：{p['updated'][:10]}",'- 总索引：[[03-literature/阅读记录]]']
        if p.get('affiliation_source'): info.append(f"- 单位来源：{p['affiliation_source']}")
        body=f"# {p['title']}\n\n## 基本信息\n\n"+'\n'.join(info)+'\n\n## arXiv 原始摘要\n\n'+p['abstract']+'\n\n## 关键词\n\n'+'\n'.join('- '+k for k in keywords)
        body+='\n\n## 来源与导入记录\n\n'+f'- {date} 由本地论文雷达从 arXiv API 导入；主题为检索分类，可人工调整。\n- 未自动生成方法解读、实验结论或评价。\n'
        return ('---\n'+yaml.safe_dump(data,allow_unicode=True,sort_keys=False,width=120)+'---\n\n'+body).encode()
    def _index(self,current,header,link,paper_link,related_col):
        text=current or header
        lines=text.splitlines(); found=False
        for i,line in enumerate(lines):
            if line.startswith('|') and re.search(re.escape(link[:-2])+r'(?:\||\]\])',line):
                # Reliable split: protect aliases before separating Markdown table cells.
                protected=re.sub(r'\[\[.*?\]\]',lambda m:m.group(0).replace('|','\u0000'),line)
                cells=[s.replace('\u0000','|') for s in protected.split('|')]
                if len(cells)<related_col+2: raise ValueError('现有索引格式无法安全识别')
                if paper_link not in cells[related_col]:
                    cells[related_col]=cells[related_col].rstrip()+'，'+paper_link+' '
                lines[i]='|'.join(cells); found=True; break
        if not found:
            if '|---' not in text and '| ---' not in text: raise ValueError('现有索引格式无法安全识别')
            lines.append(f'| {link} | 待核实（arXiv metadata） | {paper_link} | arXiv 作者元数据 |' if related_col==3 else f'| {link} | 分类轴 | {paper_link} | 检索分类 |')
        return '\n'.join(lines).rstrip()+'\n'
    def plan(self,papers,queue=False):
        preview=self.preview(papers,queue); changes={}; expected={}
        def read(rel):
            p=self.checked(rel)
            if p not in expected: expected[p]=p.read_bytes() if p.exists() else None
            content=changes.get(p,expected[p]); return content.decode() if content is not None else ''
        def write(rel,text):
            p=self.checked(rel); read(rel); changes[p]=text.encode() if isinstance(text,str) else text
        for p,item in zip(papers,preview['items']):
            if item['action']=='skip': continue
            rel=str(Path(item['path']).relative_to(self.root)); write(rel,self.note(p,queue))
            paper_link='[['+rel[:-3]+']]'
            for a in p['authors']:
                name=a['name']; entity='04-authors/'+safe_name(name)+'.md'; link='[['+entity[:-3]+']]'
                old=read(entity)
                if not old:
                    fm={'type':'author-note','created':datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),'status':'active'}
                    institution='；'.join(a.get('affiliations',[])) or '待核实（arXiv metadata）'
                    old='---\n'+yaml.safe_dump(fm,allow_unicode=True,sort_keys=False)+'---\n\n# '+name+'\n\n- 机构/身份：'+institution+'\n'
                    if a.get('affiliations'): old+='- 来源：'+(p.get('affiliation_source') or p['url'])+'（affiliation as listed in paper）\n'
                if paper_link not in old: old+='\n- '+paper_link+'\n'
                write(entity,old)
                index='04-authors/作者索引.md'; old=read(index)
                write(index,self._index(old,'# 作者索引\n\n| 作者 | 机构/身份 | 相关论文 | 备注 |\n|---|---|---|---|\n',link,paper_link,3))
            for name in keyword_names(p):
                entity='05-keywords/'+safe_name(name)+'.md'; link='[['+entity[:-3]+']]'; old=read(entity)
                if not old: old='---\ntype: keyword-note\nstatus: active\n---\n\n# '+name+'\n'
                if paper_link not in old: old+='\n- '+paper_link+'\n'
                write(entity,old)
                index='05-keywords/关键词索引.md'; old=read(index)
                write(index,self._index(old,'# 关键词索引\n\n| 关键词 | 类型 | 相关论文 | 备注 |\n|---|---|---|---|\n',link,paper_link,3))
        # Capture duplicates too, so the preview notices a user edit before import.
        for item in preview['items']:
            p=Path(item['path'])
            if p.exists() and p not in expected: expected[p]=p.read_bytes()
        snapshot=digest(json.dumps({str(p):digest(v) if v is not None else None for p,v in expected.items()},sort_keys=True).encode())
        return preview,changes,expected,snapshot
    def snapshot(self,papers,queue=False): return self.plan(papers,queue)[3]
    def import_papers(self,papers,queue=False,expected_snapshot=None):
        self.backup_root.mkdir(parents=True,exist_ok=True)
        with LOCK, (self.backup_root/'vault.lock').open('a+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            preview,changes,expected,snapshot=self.plan(papers,queue)
            if expected_snapshot is not None and snapshot!=expected_snapshot: raise ValueError('预览后文件发生变化，请重新预览')
            batch=self.backup_root/(datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
            batch.mkdir(); manifest={'vault_path':str(self.root),'status':'prepared','files':[]}
            for p,content in changes.items():
                before=expected[p]; rel=p.relative_to(self.root)
                if before is not None:
                    backup=batch/'files'/rel; backup.parent.mkdir(parents=True,exist_ok=True); backup.write_bytes(before)
                manifest['files'].append({'path':str(rel),'created':before is None,'before_sha256':digest(before) if before is not None else None,'after_sha256':digest(content)})
            manifestpath=batch/'manifest.json'; manifestpath.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
            written=[]
            try:
                for p,content in changes.items():
                    self.checked(p.relative_to(self.root))
                    before=p.read_bytes() if p.exists() else None
                    if before!=expected[p]: raise ValueError('写入前检测到文件变化，请重新预览')
                    p.parent.mkdir(parents=True,exist_ok=True)
                    tmp=p.parent/('.radar-'+uuid.uuid4().hex+'.tmp')
                    try: tmp.write_bytes(content); os.replace(tmp,p)
                    finally: tmp.unlink(missing_ok=True)
                    written.append(p)
            except Exception:
                for p in reversed(written):
                    if p.read_bytes()!=changes[p]: continue
                    if expected[p] is None: p.unlink()
                    else: p.write_bytes(expected[p])
                manifest['status']='rolled-back'; manifestpath.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)); raise
            manifest['status']='complete'; manifestpath.write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
            results=[{'id':i['id'],'status':'skipped' if i['action']=='skip' else 'created','path':i['path'],'message':i['reason'],
                'obsidian_url':'obsidian://open?vault='+quote(self.root.name)+'&file='+quote(str(Path(i['path']).relative_to(self.root))) } for i in preview['items']]
            return {'results':results,'backup_path':str(batch)}
