import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from radar.arxiv import ArxivClient, Cancelled
from radar.affiliations import enrich_paper
from radar.storage import Store
from radar.topics import BY_ID, TOPICS, build_query, classify, keyword_names
from radar.vault import Vault
from radar.summaries import sync_reports

TZ=ZoneInfo('Asia/Shanghai')

class Radar:
    def __init__(self,project):
        self.root=Path(project); self.store=Store(self.root/'data'); self.cancel=threading.Event(); self.guard=threading.Lock()
        self.task={'status':'idle','running':False,'message':'等待抓取','completed':0,'total':0,'error':None}
        self.previews={}
    def vault(self): return Vault(self.store.settings()['vault_path'],self.root/'backups')
    def log(self,message,level='info'):
        self.store.log(message,level); self.task['message']=message
    def papers(self):
        sync_reports(self.store,self.root/'reports')
        try: existing=self.vault().existing()
        except (ValueError,OSError): existing={}
        return [{**p,'keywords':keyword_names(p),'existing_path':existing.get(p['id'],''),'imported':p['id'] in existing} for p in self.store.papers() if p.get('topics')]
    def begin(self,fn,*args):
        with self.guard:
            if self.task['running']: raise ValueError('已有任务运行，请等待或取消')
            self.cancel.clear(); self.task={'status':'running','running':True,'message':'准备任务','completed':0,'total':0,'error':None}
            threading.Thread(target=fn,args=args,daemon=True).start()
        return dict(self.task)
    def _scan(self,client,tid,work,budget,new_ids,save):
        offset=work.get('offset',0); fetched=0; total=0; stopped=False; initial=offset
        while offset-initial<budget:
            if self.cancel.is_set(): raise Cancelled()
            rows,total=client.query(work['query'],start=offset,count=min(30,budget-(offset-initial)),sort=work['mode'])
            if initial==0 and offset==0:
                work['anchor']=(rows[0]['id']+'|'+rows[0]['updated']) if rows else 'empty'
            if not rows: return True,fetched,total
            for p in rows:
                updated_date=datetime.fromisoformat(p['updated'].replace('Z','+00:00')).astimezone(TZ).date()
                if work['mode']=='lastUpdatedDate' and str(updated_date)<work['start']:
                    stopped=True; continue
                p.update(classify(p))
                if not p['topics']: continue
                if self.store.upsert(p): new_ids.add(p['id'])
                fetched+=1
            offset+=len(rows); work['offset']=offset; save()
            if stopped or offset>=total: return True,fetched,total
        return False,fetched,total
    def fetch(self,topics,days=30,budget=30,enrich=False,client=None,start_date=None,end_date=None):
        today=datetime.now(TZ).date(); start=today-timedelta(days=days-1)
        end=end_date or str(today); explicit=bool(start_date)
        if explicit: start=datetime.fromisoformat(start_date).date()
        self.task={'status':'running','running':True,'message':'开始抓取','completed':0,'total':len(topics)*(1 if explicit else 2),'error':None,'truncated':False,'fetched':0,'new':0,'failures':[]}
        client=client or ArxivClient(self.root/'data',self.cancel,self.log)
        failures=[]; new_ids=set(); counts=0
        for tid in topics:
            if self.cancel.is_set(): break
            name=BY_ID[tid]['name']; checkpoint_complete=True
            last=self.store.checkpoint('last-scan:'+tid)
            topic_start=str(start)
            if last and not explicit:
                # Include a day of overlap and catch up after offline gaps.
                catchup=str(datetime.fromisoformat(last['date']).date()-timedelta(days=1))
                topic_start=min(topic_start,catchup)
            for mode in (['submittedDate'] if explicit else ['submittedDate','lastUpdatedDate']):
                if self.cancel.is_set(): break
                key='pending:'+tid+':'+mode
                if explicit: key+=':'+str(start)+':'+end
                pending=self.store.checkpoint(key) or []
                old_pending=[dict(w) for w in pending]
                scan_start=topic_start
                if pending and not explicit and mode=='submittedDate':
                    latest=max(w['end'] for w in pending)
                    scan_start=max(topic_start,str(datetime.fromisoformat(latest).date()-timedelta(days=1)))
                query=build_query(tid,scan_start,end) if mode=='submittedDate' else build_query(tid)
                head={'query':query,'mode':mode,'start':scan_start,'end':end,'offset':0}
                try:
                    self.log(f'{name}：检索'+('新提交论文' if mode=='submittedDate' else '近期修订'))
                    complete,count,total=self._scan(client,tid,head,budget,new_ids,lambda:None); counts+=count
                    matching=next((w for w in pending if w['query']==query and w['start']==scan_start and w['end']==end and w.get('anchor')==head.get('anchor')),None)
                    if complete:
                        if matching: pending.remove(matching)
                    elif matching: matching['offset']=max(matching['offset'],head['offset'])
                    else: pending.append(head)
                    self.store.checkpoint(key,pending)
                    # Resume one persisted range after refreshing the newest results.
                    if old_pending and pending:
                        work=pending[0]
                        self.log(f"{name}：续抓 {work['start']} 至 {work['end']}，从第 {work['offset']+1} 条继续")
                        done,count,_=self._scan(client,tid,work,budget,new_ids,lambda:self.store.checkpoint(key,pending)); counts+=count
                        if done: pending.remove(work)
                        self.store.checkpoint(key,pending)
                    if pending:
                        checkpoint_complete=False; self.task['truncated']=True
                        self.log(f'{name}：达到预算，保存 {len(pending)} 个未完成范围，下次续抓','warning')
                    else: self.log(f'{name}：本轮范围扫描完成')
                except Cancelled: break
                except Exception as exc:
                    checkpoint_complete=False; failures.append({'topic':tid,'mode':mode,'error':str(exc)})
                    self.log(f'{name} 抓取失败：{type(exc).__name__}: {exc}','error')
                self.task['completed']+=1
            topic_failed=any(f['topic']==tid for f in failures)
            if not topic_failed and not explicit and not self.cancel.is_set(): self.store.checkpoint('last-scan:'+tid,{'date':str(today)})
            if checkpoint_complete and not topic_failed and not self.cancel.is_set(): self.store.checkpoint(tid,{'date':end,'start':topic_start})
        self.task['fetched']=counts; self.task['new']=len(new_ids)
        if enrich and not self.cancel.is_set():
            for pid in list(new_ids)[:30]:
                if self.cancel.is_set(): break
                self.log('核实作者单位：'+pid)
                try: self.store.upsert(enrich_paper(self.store.get(pid),client))
                except Cancelled: break
        self.task['failures']=failures
        status='cancelled' if self.cancel.is_set() else ('failed' if failures else 'complete')
        self.task.update(status=status,running=False,error='部分检索失败，详见日志' if failures else None)
        self.log(f'本轮结束：新增缓存 {len(new_ids)} 篇'+('；覆盖有限，详见日志' if self.task['truncated'] else ''))
        return dict(self.task)
    def enrich(self,ids):
        client=ArxivClient(self.root/'data',self.cancel,self.log); failures=[]
        self.task.update(total=len(ids),completed=0)
        try:
            for pid in ids:
                if self.cancel.is_set(): raise Cancelled()
                p=self.store.get(pid)
                if not p: continue
                self.log('核实单位：'+p['title']); self.store.upsert(enrich_paper(p,client))
                self.task['completed']+=1
        except Cancelled: pass
        except Exception as exc: failures.append(str(exc)); self.log(str(exc),'error')
        self.task.update(running=False,status='cancelled' if self.cancel.is_set() else ('failed' if failures else 'complete'),error='; '.join(failures) or None)
        self.log('单位核验结束；未确认项保留待核实')
    def select(self,ids):
        if not ids: raise ValueError('请选择论文')
        result=[]
        for pid in dict.fromkeys(ids):
            p=self.store.get(pid)
            if not p: raise ValueError('缓存中找不到论文：'+pid)
            result.append(p)
        return result
    def preview(self,ids,queue=False):
        papers=self.select(ids); vault=self.vault(); result,changes,expected,snapshot=vault.plan(papers,queue)
        result['files']=[{'path':str(p.relative_to(vault.root)),'action':'create' if expected[p] is None else 'modify'} for p in changes]
        key=(tuple(ids),queue,vault.root)
        self.previews[key]={'snapshot':snapshot,'papers_hash':json.dumps(papers,sort_keys=True)}
        return result
    def import_selected(self,ids,queue=False):
        papers=self.select(ids); vault=self.vault(); key=(tuple(ids),queue,vault.root)
        check=self.previews.get(key)
        if not check: raise ValueError('请先预览入库计划')
        if check['papers_hash']!=json.dumps(papers,sort_keys=True): raise ValueError('论文元数据变化，请重新预览')
        result=vault.import_papers(papers,queue,check['snapshot']); self.previews.pop(key,None)
        self.log(f"入库批次：{sum(r['status']=='created' for r in result['results'])} 篇；备份 {result['backup_path']}")
        return result
    def digest(self,limit=20):
        rows=[p for p in self.papers() if p['score']>=43 and not p['imported']]
        rows=self.store.unreported(rows)[:limit]
        if not rows: return None,[]
        folder=self.root/'reports'; folder.mkdir(exist_ok=True)
        name=datetime.now(TZ).strftime('%Y-%m-%d-%H%M%S')+'-'+uuid.uuid4().hex[:5]+'.md'; path=folder/name
        text='# 新论文简报\n\n'+datetime.now(TZ).strftime('%Y-%m-%d %H:%M 北京时间')+'\n\n'
        text+='本简报为首次发现且未入库的候选论文；检索采用结果预算，不能视为全量文献。摘要为 arXiv 原始摘要，中文提要可由定期简报任务补充。\n\n'
        for p in rows:
            text+='## '+p['title']+'\n\n'
            text+='- 作者：'+', '.join(a['name'] for a in p['authors'])+'\n'
            text+='- 单位：'+('；'.join(p.get('institutions',[])) or '待核实（arXiv 元数据及 HTML 未提供可靠对应）')+'\n'
            text+='- 单位核验：'+p.get('affiliation_status','待核实')+'\n'
            if p.get('affiliation_source'): text+='- 单位来源：'+p['affiliation_source']+'\n'
            text+='- 日期：'+p['published'][:10]+'；版本：v'+str(p['version'])+'\n'
            text+='- 方向：'+', '.join(BY_ID[t]['name'] for t in p['topics'])+'\n'
            text+=f"- 原文：[{p['id']}]({p['url']})\n\n### 原始摘要\n\n{p['abstract']}\n\n"
        path.write_text(text); self.store.record_digest(name,rows)
        return path,rows
