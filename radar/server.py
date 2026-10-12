import secrets
from pathlib import Path
from datetime import date
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator
from radar.service import Radar
from radar.topics import TOPICS, BY_ID, keyword_names

ROOT=Path(__file__).resolve().parent.parent

class Fetch(BaseModel):
    topics:list[str]=Field(default_factory=lambda:list(BY_ID),min_length=1,max_length=5)
    days:int=Field(default=30,ge=1,le=3650)
    budget:int=Field(default=30,ge=1,le=200)
    enrich:bool=False
    start_date:date|None=None
    end_date:date|None=None
    @model_validator(mode='after')
    def valid_dates(self):
        if bool(self.start_date)!=bool(self.end_date): raise ValueError('起止日期需要同时指定')
        if self.start_date and (self.start_date>self.end_date or (self.end_date-self.start_date).days>3650): raise ValueError('日期范围无效或超过十年')
        return self
    @field_validator('topics')
    @classmethod
    def valid_topics(cls,value):
        if any(t not in BY_ID for t in value): raise ValueError('未知主题')
        return list(dict.fromkeys(value))
class Selection(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=100)
    queue:bool=False
class Settings(BaseModel): vault_path:str=Field(min_length=1,max_length=1000)
class Classification(BaseModel):
    id:str
    topics:list[str]=Field(min_length=1,max_length=5)
    keywords:list[str]=Field(default_factory=list,max_length=4)
    @field_validator('topics')
    @classmethod
    def valid(cls,value):
        if any(t not in BY_ID for t in value): raise ValueError('未知方向')
        return list(dict.fromkeys(value))

def create_app(radar=None):
    r=radar or Radar(ROOT); token=secrets.token_urlsafe(32)
    app=FastAPI(title='Mihuhu Paper Radar'); app.state.radar=r
    @app.middleware('http')
    async def security(request:Request,call_next):
        host=request.url.hostname
        if host not in ('127.0.0.1','localhost','testserver','::1'):
            return JSONResponse({'detail':'只允许本机访问'},status_code=403)
        origin=request.headers.get('origin')
        expected=request.url.scheme+'://'+request.headers.get('host','')
        if (origin and origin!=expected) or request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'拒绝跨站请求'},status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(request.headers.get('x-radar-token',''),token):
            return JSONResponse({'detail':'会话令牌无效，请刷新页面'},status_code=403)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        return response
    @app.exception_handler(ValueError)
    async def value_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=409)
    @app.get('/api/state')
    def state():
        papers=r.papers()
        return {'token':token,'settings':r.store.settings(),'topics':TOPICS,'task':dict(r.task),
            'stats':{'total':len(papers),'new':sum(not p['imported'] for p in papers),'imported':sum(p['imported'] for p in papers)}}
    @app.get('/api/papers')
    def papers(topic:str='',q:str='',min_score:int=0,show:str='all'):
        rows=r.papers()
        if topic: rows=[p for p in rows if topic in p['topics']]
        if q:
            term=q.casefold(); rows=[p for p in rows if term in (p['title']+' '+p['abstract']+' '+p.get('abstract_zh','')+' '+str(p['authors'])).casefold()]
        rows=[p for p in rows if p['score']>=min_score]
        if show=='new': rows=[p for p in rows if not p['imported']]
        if show=='imported': rows=[p for p in rows if p['imported']]
        return {'papers':rows,'total':len(rows)}
    @app.get('/api/papers/{pid:path}')
    def detail(pid:str):
        rows=r.papers(); p=next((p for p in rows if p['id']==pid),None)
        if not p: raise HTTPException(404,'论文不存在')
        return p
    @app.get('/api/logs')
    def logs(): return {'logs':r.store.logs()}
    def keywords():
        names={k for t in TOPICS for k in t['keywords']}
        folder=r.vault().checked('05-keywords')
        if folder.exists(): names.update(p.stem for p in folder.glob('*.md') if p.stem!='关键词索引')
        return sorted(names,key=str.casefold)
    @app.get('/api/keywords')
    def keyword_list(): return {'keywords':keywords()}
    @app.post('/api/classify')
    def classify_candidate(body:Classification):
        p=r.select([body.id])[0]
        if any(k not in keywords() for k in body.keywords): raise ValueError('请复用已有关键词')
        p['manual_topics']=body.topics; p['topics']=body.topics; p['manual_keywords']=list(dict.fromkeys(body.keywords))
        r.store.upsert(p,manual=True); r.previews.clear()
        return {**p,'keywords':keyword_names(p)}
    @app.post('/api/fetch')
    def fetch(body:Fetch):
        return r.begin(r.fetch,body.topics,body.days,body.budget,body.enrich,None,
            body.start_date.isoformat() if body.start_date else None,body.end_date.isoformat() if body.end_date else None)
    @app.post('/api/cancel')
    def cancel(): r.cancel.set(); return {'message':'已请求取消，正在等待当前网络请求结束'}
    @app.post('/api/enrich')
    def enrich(body:Selection):
        r.select(body.ids); return r.begin(r.enrich,body.ids)
    @app.post('/api/preview')
    def preview(body:Selection): return r.preview(body.ids,body.queue)
    @app.post('/api/import')
    def importing(body:Selection): return r.import_selected(body.ids,body.queue)
    @app.post('/api/settings')
    def settings(body:Settings):
        path=Path(body.vault_path).expanduser().resolve()
        if not path.is_dir(): raise ValueError('目录不存在，请先在 Obsidian 中创建或选择库')
        r.store.set_setting('vault_path',str(path)); r.previews.clear(); return r.store.settings()
    @app.get('/api/digests')
    def digests(): return {'digests':r.store.digests()}
    @app.post('/api/digest')
    def make_digest():
        path,rows=r.digest(); return {'path':str(path) if path else None,'count':len(rows),'url':'/reports/'+path.name if path else None}
    @app.get('/reports/{name}')
    def report(name:str):
        p=r.root/'reports'/name
        if Path(name).name!=name or not name.endswith('.md') or not p.is_file() or p.is_symlink(): raise HTTPException(404)
        return FileResponse(p,media_type='text/markdown',filename=name)
    web=ROOT/'web'
    if web.exists(): app.mount('/',StaticFiles(directory=web,html=True),name='web')
    return app

app=create_app()
