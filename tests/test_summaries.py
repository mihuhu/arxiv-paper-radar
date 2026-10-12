from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from radar.storage import Store
from radar.summaries import sync_reports
from radar.service import Radar
from radar.server import create_app
from radar.topics import classify
from test_core import paper

ZH='该论文研究智能体行为水印，利用轨迹中的统计信号检测未经授权的蒸馏，并结合模型指纹进行归属验证。'

def test_summary_survives_refetch_and_becomes_stale_on_new_version(tmp_path):
    s=Store(tmp_path); p=paper(); s.upsert(p)
    s.save_summary(p['id'],ZH,'test.md',p['version'],p['abstract'])
    s.upsert(paper())
    assert s.get(p['id'])['abstract_zh']==ZH
    newer=paper(); newer['version']=3; s.upsert(newer)
    assert s.get(p['id'])['abstract_zh']=='' and s.get(p['id'])['abstract_zh_status']=='outdated'

def test_changed_abstract_cannot_use_same_version_summary(tmp_path):
    s=Store(tmp_path); p=paper(); s.upsert(p)
    s.save_summary(p['id'],ZH,'test.md',p['version'],p['abstract'])
    p['abstract']+=' Updated experimental results.'; s.upsert(p)
    assert s.get(p['id'])['abstract_zh']==''

def test_summary_write_rejects_stale_source(tmp_path):
    s=Store(tmp_path); p=paper(); s.upsert(p)
    with pytest.raises(ValueError,match='原始摘要'):
        s.save_summary(p['id'],ZH,'bad.md',p['version'],'Wrong source')
    assert not s.get(p['id'])['abstract_zh']

def test_report_sync_binds_id_version_and_english(tmp_path):
    s=Store(tmp_path/'data'); p=paper(); s.upsert(p)
    folder=tmp_path/'reports'; folder.mkdir()
    text=f"# 简报\n\n## {p['title']}\n\n- 原文：[{p['id']}]({p['url']})\n- 版本：v2\n\n### 中文摘要\n\n{ZH}\n\n### 原始摘要\n\n{p['abstract']}\n"
    (folder/'report.md').write_text(text)
    assert sync_reports(s,folder)['saved']==1
    assert s.papers()[0]['abstract_zh']==ZH
    assert sync_reports(s,folder)['saved']==0
    (folder/'wrong.md').write_text(text.replace(p['abstract'],'Not the original abstract'))
    result=sync_reports(s,folder)
    assert result['saved']==0 and result['rejected']

def test_legacy_report_and_http_chinese_search(tmp_path):
    root=tmp_path/'vault';root.mkdir();r=Radar(tmp_path);r.store.set_setting('vault_path',str(root))
    p=paper();p.update(classify(p));r.store.upsert(p)
    folder=tmp_path/'reports';folder.mkdir()
    (folder/'legacy.md').write_text(f"## {p['title']}\n\n- arXiv：[{p['id']}]({p['url']})（v2）\n- 单位：待核实\n\n{ZH}\n\n### 原始摘要\n\n{p['abstract']}\n")
    with TestClient(create_app(r)) as c:
        rows=c.get('/api/papers',params={'q':'未经授权的蒸馏'}).json()['papers']
        assert len(rows)==1 and rows[0]['abstract_zh']==ZH
        assert c.get('/api/papers/'+p['id']).json()['abstract_zh_source']=='legacy.md'

def test_legacy_chinese_quote_inside_english_does_not_replace_summary():
    from radar.summaries import parse_report
    p=paper(); original='This paper studies 安全 mechanisms in LLM agents.'
    text=f"## {p['title']}\n\n- 原文：[{p['id']}]({p['url']})（v2）\n\n{ZH}\n\n### 原始摘要\n\n{original}\n"
    assert parse_report(text)[0]['text']==ZH

def test_bad_report_does_not_block_valid_sync_or_http_state(tmp_path):
    root=tmp_path/'vault';root.mkdir();r=Radar(tmp_path);r.store.set_setting('vault_path',str(root))
    p=paper();p.update(classify(p));r.store.upsert(p)
    folder=tmp_path/'reports';folder.mkdir()
    text=f"## {p['title']}\n\n- 原文：[{p['id']}]({p['url']})\n- 版本：v2\n\n### 中文摘要\n\n{ZH}\n\n### 原始摘要\n\n{p['abstract']}\n"
    (folder/'valid.md').write_text(text)
    (folder/'bad.md').write_text(text.replace(p['url'],'https://arxiv.org/abs/2601.bad'))
    (folder/'broken-encoding.md').write_bytes(b'\xff\xfe\xff')
    with TestClient(create_app(r)) as c:
        state=c.get('/api/state'); assert state.status_code==200 and state.json()['token']
        assert state.headers['cache-control']=='no-store'
        rows=c.get('/api/papers'); assert rows.status_code==200 and rows.json()['papers'][0]['abstract_zh']==ZH
    assert sync_reports(r.store,folder)['rejected']
