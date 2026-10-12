import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest
from radar.service import Radar
from radar.server import create_app
from fastapi.testclient import TestClient
from test_core import paper
from radar.topics import classify

def test_fetch_error_does_not_advance_checkpoint(tmp_path):
    r=Radar(tmp_path)
    class Broken:
        def query(self,*a,**k): raise OSError('offline')
    result=r.fetch(['watermark'],30,2,False,client=Broken())
    assert result['status']=='failed' and r.store.checkpoint('watermark') is None

def test_budget_is_reported_and_existing_filtered_from_digest(tmp_path):
    r=Radar(tmp_path); root=tmp_path/'vault'; root.mkdir(); r.store.set_setting('vault_path',str(root))
    class Fixture:
        def query(self,*a,**k): return [paper()],100
    result=r.fetch(['agent-watermark'],30,1,False,client=Fixture())
    assert result['status']=='complete' and result['truncated']
    assert r.store.checkpoint('agent-watermark') is None
    path,rows=r.digest(limit=10)
    assert len(rows)==1 and path.exists()
    assert 'Alice Example' in path.read_text() and 'Example University' in path.read_text()
    # Generating a draft does not acknowledge delivery, avoiding lost notifications.
    assert len(r.store.unreported(rows))==1
    r.store.mark_reported([rows[0]['id']])
    assert r.digest()[1]==[]

def test_http_token_origin_and_preview_requirement(tmp_path):
    root=tmp_path/'vault'; root.mkdir()
    r=Radar(tmp_path); r.store.set_setting('vault_path',str(root)); p=paper(); p.update(classify(p)); r.store.upsert(p)
    with TestClient(create_app(r)) as c:
        state=c.get('/api/state').json(); token=state['token']
        payload={'ids':['2401.12345'],'queue':False}
        assert c.post('/api/import',json=payload).status_code==403
        h={'X-Radar-Token':token,'Origin':'https://evil.example'}
        assert c.post('/api/import',headers=h,json=payload).status_code==403
        h={'X-Radar-Token':token}
        assert c.post('/api/import',headers=h,json=payload).status_code==409
        assert c.post('/api/preview',headers=h,json=payload).status_code==200
        result=c.post('/api/import',headers=h,json=payload)
        assert result.status_code==200 and result.json()['results'][0]['status']=='created'
        assert c.get('/api/papers').json()['papers'][0]['existing_path']

def test_unknown_topic_and_budget_rejected(tmp_path):
    with TestClient(create_app(Radar(tmp_path))) as c:
        h={'X-Radar-Token':c.get('/api/state').json()['token']}
        assert c.post('/api/fetch',headers=h,json={'topics':['fake'],'budget':1,'days':30}).status_code==422
        assert c.post('/api/fetch',headers=h,json={'topics':['watermark'],'budget':999999,'days':30}).status_code==422

def test_recent_update_uses_beijing_date(tmp_path):
    r=Radar(tmp_path)
    date=datetime.now(ZoneInfo('Asia/Shanghai')).replace(hour=1,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()
    p=paper(); p['updated']=date; p['published']='2024-01-20T00:00:00Z'
    class Recent:
        def query(self,*a,**k): return ([p],1) if k['sort']=='lastUpdatedDate' else ([],0)
    r.fetch(['agent-watermark'],1,3,False,client=Recent())
    assert r.store.get(p['id']) is not None

def test_manual_classification_persists_across_fetch(tmp_path):
    root=tmp_path/'vault'; root.mkdir(); r=Radar(tmp_path); r.store.set_setting('vault_path',str(root))
    p=paper(); p.update(classify(p)); r.store.upsert(p)
    with TestClient(create_app(r)) as c:
        h={'X-Radar-Token':c.get('/api/state').json()['token']}
        result=c.post('/api/classify',headers=h,json={'id':p['id'],'topics':['distillation'],'keywords':['Fingerprinting']})
        assert result.status_code==200 and result.json()['keywords']==['Fingerprinting']
        r.store.upsert(p)
        assert r.store.get(p['id'])['topics']==['distillation']
        assert c.get('/api/keywords').json()['keywords']

def test_truncated_query_resumes_after_restart(tmp_path):
    r=Radar(tmp_path); offsets=[]
    class Paged:
        def query(self,*a,**k):
            offsets.append(k['start']); p=paper(); p['id']=f"2401.{12345+k['start']}"
            return [p],5
    r.fetch(['agent-watermark'],30,1,False,client=Paged())
    r=Radar(tmp_path)
    r.fetch(['agent-watermark'],30,1,False,client=Paged())
    assert any(offset>0 for offset in offsets)

def test_preview_lists_entity_changes(tmp_path):
    root=tmp_path/'vault'; root.mkdir(); r=Radar(tmp_path); r.store.set_setting('vault_path',str(root))
    p=paper(); p.update(classify(p)); r.store.upsert(p)
    preview=r.preview([p['id']])
    assert any(f['path'].endswith('作者索引.md') for f in preview['files'])
    assert any(f['path'].endswith('关键词索引.md') for f in preview['files'])

def test_historical_range_does_not_scan_current_revisions(tmp_path):
    r=Radar(tmp_path); modes=[]
    class History:
        def query(self,*a,**k):
            modes.append(k['sort'])
            return ([],0) if k['sort']=='submittedDate' else ([paper()],1)
    r.fetch(['watermark'],30,5,False,client=History(),start_date='2024-01-01',end_date='2024-01-31')
    assert modes==['submittedDate'] and not r.store.papers()

def test_shifted_revision_head_remains_pending_until_new_gap_scanned(tmp_path):
    r=Radar(tmp_path)
    def make(n):
        p=paper(); p['id']=f'2401.{12000+n}'; p['updated']=datetime.now(timezone.utc).isoformat(); return p
    old=[make(n) for n in range(8)]; rows=list(old)
    class Moving:
        def query(self,*a,**k):
            if k['sort']=='submittedDate': return [],0
            off=k['start']; return rows[off:off+k['count']],len(rows)
    client=Moving()
    r.fetch(['agent-watermark'],7,2,False,client=client)
    r.fetch(['agent-watermark'],7,2,False,client=client)
    fresh=[make(n) for n in range(10,15)]; rows=fresh+old
    task=r.fetch(['agent-watermark'],7,2,False,client=client)
    assert task['truncated'], 'new head gap must not be claimed complete'
    for _ in range(12):
        task=r.fetch(['agent-watermark'],7,2,False,client=client)
        if not task['truncated']:
            assert all(r.store.get(p['id']) for p in fresh+old), 'completion must not hide a shifted-head gap'
    assert all(r.store.get(p['id']) for p in fresh+old)

def test_inflight_enrichment_cannot_overwrite_new_classification(tmp_path,monkeypatch):
    import radar.service as service
    root=tmp_path/'vault'; root.mkdir(); r=Radar(tmp_path); r.store.set_setting('vault_path',str(root))
    p=paper(); p.update(classify(p)); r.store.upsert(p)
    entered=threading.Event(); release=threading.Event()
    def gated(p,client): entered.set(); assert release.wait(3); p['affiliation_note']='checked'; return p
    monkeypatch.setattr(service,'enrich_paper',gated)
    with TestClient(create_app(r)) as c:
        h={'X-Radar-Token':c.get('/api/state').json()['token']}
        body={'id':p['id'],'topics':['watermark'],'keywords':['Watermarking']}
        assert c.post('/api/classify',headers=h,json=body).status_code==200
        thread=threading.Thread(target=r.enrich,args=([p['id']],)); thread.start(); assert entered.wait(3)
        body.update(topics=['distillation'],keywords=['Fingerprinting'])
        assert c.post('/api/classify',headers=h,json=body).status_code==200
        release.set(); thread.join(3)
        saved=r.store.get(p['id'])
        assert saved['manual_topics']==['distillation'] and saved['manual_keywords']==['Fingerprinting']
