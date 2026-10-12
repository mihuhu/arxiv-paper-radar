import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from radar.summaries import abstract_fingerprint, SUMMARY_FIELDS

DEFAULT_VAULT=str(Path.home()/'Obsidian'/'paper-vault')
def now(): return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, data_dir):
        self.root=Path(data_dir); self.root.mkdir(parents=True,exist_ok=True); self.db=self.root/'radar.sqlite3'
        with self.connect() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logs(seq INTEGER PRIMARY KEY AUTOINCREMENT,time TEXT,message TEXT,level TEXT);
            CREATE TABLE IF NOT EXISTS reported(id TEXT PRIMARY KEY,version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS digests(name TEXT PRIMARY KEY,created TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS checkpoints(topic TEXT PRIMARY KEY,value TEXT);''')
            c.execute('CREATE TABLE IF NOT EXISTS summaries(id TEXT PRIMARY KEY,version INTEGER NOT NULL,abstract_hash TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,generated_at TEXT NOT NULL)')
    def connect(self):
        c=sqlite3.connect(self.db,timeout=30); c.row_factory=sqlite3.Row; return c
    def get(self, pid):
        with self.connect() as c:
            row=c.execute('SELECT payload FROM papers WHERE id=?',(pid,)).fetchone()
            return self.with_summary(json.loads(row[0]),c) if row else None
    def with_summary(self,p,c):
        p={k:v for k,v in p.items() if k not in SUMMARY_FIELDS}
        row=c.execute('SELECT * FROM summaries WHERE id=?',(p['id'],)).fetchone()
        matched=bool(row and row['version']==p.get('version',1) and row['abstract_hash']==abstract_fingerprint(p['abstract']))
        p.update(abstract_zh=row['text'] if matched else '',abstract_zh_status='ready' if matched else ('outdated' if row else 'pending'),
            abstract_zh_source=row['source'] if row else '',abstract_zh_generated_at=row['generated_at'] if row else '')
        return p
    def save_summary(self,pid,text,source,version,abstract):
        if not 30<=len(text.strip())<=5000 or not any('\u4e00'<=ch<='\u9fff' for ch in text): raise ValueError('中文摘要内容无效')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT payload FROM papers WHERE id=?',(pid,)).fetchone()
            if not row: raise ValueError('论文不存在')
            paper=json.loads(row[0]); fingerprint=abstract_fingerprint(abstract)
            if paper.get('version',1)!=version or abstract_fingerprint(paper['abstract'])!=fingerprint:
                raise ValueError('版本或原始摘要不匹配，不能绑定中文摘要')
            c.execute('INSERT OR REPLACE INTO summaries VALUES(?,?,?,?,?,?)',(pid,version,fingerprint,text.strip(),source,now()))
    def upsert(self,paper,manual=False):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT payload FROM papers WHERE id=?',(paper['id'],)).fetchone()
            p={k:v for k,v in paper.items() if k not in SUMMARY_FIELDS}
            if row:
                old=json.loads(row[0])
                if old.get('version',1)>p.get('version',1): return False
                for key in ['manual_topics','manual_keywords']:
                    if key in old and not manual: p[key]=old[key]
                if 'manual_topics' in p: p['topics']=p['manual_topics']
                if old.get('version',1)==p.get('version',1):
                    if not p.get('institutions') and old.get('institutions'):
                        for key in ['institutions','affiliation_source','affiliation_note','affiliation_status']:
                            p[key]=old.get(key,'')
                    if old.get('institutions') and not paper.get('institutions'): p['authors']=old['authors']
                # Classification evaluates all directions; do not retain obsolete rule hits.
                c.execute('UPDATE papers SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
            else: c.execute('INSERT INTO papers VALUES(?,?,?)',(p['id'],json.dumps(p,ensure_ascii=False),now()))
        return not bool(row)
    def papers(self):
        result=[]
        with self.connect() as c:
            rows=c.execute('SELECT payload,first_seen FROM papers').fetchall()
            for row in rows:
                p=self.with_summary(json.loads(row[0]),c); p['first_seen']=row[1]; result.append(p)
        return sorted(result,key=lambda p:p.get('published',''),reverse=True)
    def settings(self):
        with self.connect() as c: rows=c.execute('SELECT key,value FROM settings').fetchall()
        default=str(Path(os.environ.get('ARXIV_RADAR_VAULT') or DEFAULT_VAULT).expanduser().resolve())
        return {'vault_path':default,**{r[0]:json.loads(r[1]) for r in rows}}
    def set_setting(self,key,value):
        with self.connect() as c: c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
    def log(self,message,level='info'):
        with self.connect() as c: c.execute('INSERT INTO logs(time,message,level) VALUES(?,?,?)',(now(),message,level))
    def logs(self):
        with self.connect() as c: rows=c.execute('SELECT time,message,level FROM logs ORDER BY seq DESC LIMIT 150').fetchall()
        return [dict(r) for r in rows]
    def checkpoint(self,topic,value=None):
        with self.connect() as c:
            if value is not None: c.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?)',(topic,json.dumps(value)))
            row=c.execute('SELECT value FROM checkpoints WHERE topic=?',(topic,)).fetchone()
        return json.loads(row[0]) if row else None
    def unreported(self,papers):
        with self.connect() as c: seen={r[0]:r[1] for r in c.execute('SELECT * FROM reported')}
        return [p for p in papers if p['id'] not in seen]
    def record_digest(self,name,papers):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO digests VALUES(?,?,?)',(name,now(),json.dumps([p['id'] for p in papers])))
    def mark_reported(self,ids):
        with self.connect() as c:
            for pid in ids:
                row=c.execute('SELECT payload FROM papers WHERE id=?',(pid,)).fetchone()
                if row: c.execute('INSERT OR REPLACE INTO reported VALUES(?,?)',(pid,json.loads(row[0]).get('version',1)))
    def digests(self):
        with self.connect() as c: rows=c.execute('SELECT name,created FROM digests ORDER BY created DESC LIMIT 60').fetchall()
        return [{**dict(r),'url':'/reports/'+r['name']} for r in rows]
