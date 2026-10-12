"""Version-bound Chinese reading summaries and local report synchronization."""
import hashlib
import re
from pathlib import Path
from radar.arxiv import normalize_id

SUMMARY_FIELDS=('abstract_zh','abstract_zh_status','abstract_zh_source','abstract_zh_generated_at')

def abstract_fingerprint(text):
    return hashlib.sha256(' '.join(text.split()).encode('utf-8')).hexdigest()

def parse_report(text):
    entries=[]
    for block in re.split(r'(?m)^## (?!#)',text)[1:]:
        locator=re.search(r'https?://arxiv\.org/abs/([A-Za-z0-9./-]+)',block)
        original=re.search(r'(?ms)^### 原始摘要\s*\n(.*?)(?=^#{1,3} |\Z)',block)
        if not locator or not original: continue
        version=re.search(r'(?:版本\s*[:：]\s*|（|\()v(\d+)',block[:original.start()])
        if not version: continue
        chinese=re.search(r'(?ms)^### 中文摘要\s*\n(.*?)(?=^#{1,3} |\Z)',block[:original.start()])
        if chinese: summary=chinese.group(1).strip()
        else:
            paragraphs=block[:original.start()].split('\n',1)[-1].split('\n\n')
            candidates=[p.strip() for p in paragraphs if re.search('[\u4e00-\u9fff]',p) and not p.lstrip().startswith(('-','#'))]
            summary=candidates[-1] if candidates else ''
        if not summary: continue
        title=re.sub(r'^\d+\s+','',block.splitlines()[0]).strip()
        entries.append({'id':locator.group(1),'version':int(version.group(1)),
            'title':title,'text':summary,'abstract':original.group(1).strip()})
    return entries

def sync_reports(store,folder):
    saved=0; rejected=[]; folder=Path(folder)
    if not folder.is_dir(): return {'saved':0,'rejected':[]}
    for path in sorted(folder.glob('*.md')):
        if path.is_symlink(): continue
        try:
            stat=path.stat(); signature=[stat.st_mtime_ns,stat.st_size]
        except OSError as exc:
            rejected.append({'file':path.name,'id':'','reason':type(exc).__name__}); continue
        checkpoint=store.checkpoint('summary-report:'+path.name)
        if checkpoint and checkpoint.get('signature')==signature and checkpoint.get('complete'): continue
        failures=[]
        try: entries=parse_report(path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,ValueError) as exc:
            rejected.append({'file':path.name,'id':'','reason':type(exc).__name__}); continue
        for entry in entries:
            try:
                pid=normalize_id(entry['id']); paper=store.get(pid)
                if not paper:
                    raise ValueError('缓存中尚无对应论文')
                if paper['title']!=entry['title']: raise ValueError('标题不匹配')
                store.save_summary(pid,entry['text'],path.name,entry['version'],entry['abstract'])
                saved+=1
            except ValueError as exc:
                failures.append({'file':path.name,'id':entry['id'],'reason':str(exc)})
        rejected.extend(failures)
        store.checkpoint('summary-report:'+path.name,{'signature':signature,'complete':not failures})
    return {'saved':saved,'rejected':rejected}
