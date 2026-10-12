from pathlib import Path
import pytest
import yaml
from radar.arxiv import parse_feed, normalize_id
from radar.topics import classify, build_query
from radar.affiliations import parse_affiliations
from radar.storage import Store
from radar.vault import Vault

# Synthetic protocol fixtures, never displayed as fetched papers.
ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:os="http://a9.com/-/spec/opensearch/1.1/" xmlns:ax="http://arxiv.org/schemas/atom">
<os:totalResults>1</os:totalResults><entry><id>http://arxiv.org/abs/2401.12345v2</id>
<title>Behavioral Watermarking for LLM Agents</title><summary>Detect unauthorized distillation through agent trajectory watermarking and model fingerprinting.</summary>
<published>2024-01-20T00:00:00Z</published><updated>2024-02-01T00:00:00Z</updated>
<author><name>Alice Example</name><ax:affiliation>Example University</ax:affiliation></author>
<category term="cs.CR"/><link href="http://arxiv.org/pdf/2401.12345v2" title="pdf"/></entry></feed>'''

def paper():
    return parse_feed(ATOM)[0][0]

def test_atom_versions_and_affiliation():
    rows, total = parse_feed(ATOM)
    assert total == 1 and rows[0]['id'] == '2401.12345'
    assert rows[0]['version'] == 2
    assert rows[0]['authors'][0]['affiliations'] == ['Example University']
    assert rows[0]['url'] == 'https://arxiv.org/abs/2401.12345'

def test_api_error_is_not_a_paper():
    with pytest.raises(ValueError, match='arXiv'):
        parse_feed('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#x</id><title>Error</title><summary>Bad query</summary></entry></feed>')

def test_normalize_old_and_new_ids():
    assert normalize_id('https://arxiv.org/abs/hep-th/9901001v3') == 'hep-th/9901001'
    with pytest.raises(ValueError): normalize_id('../../etc/passwd')

def test_topics_cross_match_and_distillation_noise():
    result = classify(paper())
    assert 'agent-watermark' in result['topics'] and 'distillation' in result['topics']
    assert result['reasons'] and result['score'] > 0
    assert 'distillation' not in classify({'title':'Efficient knowledge distillation for language models','abstract':'Compress teachers into fast students.'})['topics']

def test_unrelated_fingerprints_and_agent_used_for_image_watermarks():
    unrelated=[
        {'title':'Embedding-Bias in Conditional Independence Testing','abstract':'Condition on language model text embeddings for valid statistical independence testing.'},
        {'title':'Visual Evidence Reuse in Agentic VLM Pipelines','abstract':'An agent uses an image preprocessing fingerprint to share a visual cache.'},
        {'title':'Agentic extraction of materials knowledge','abstract':'Large-language-model extraction of chemical entities from papers.'},
        {'title':'Agent Evolution','abstract':'An LLM agent applies protocol fingerprinting to a network intrusion dataset.'},
        {'title':'ProxyEraseAgent: Blind Watermark Removal','abstract':'An agent removes invisible image watermarking using proxy decoders.'},
        {'title':'PROTAC Permeability Prediction','abstract':'An expert-in-the-loop LLM extraction workflow mines chemical measurements.'},
        {'title':'Memory schema evolution','abstract':'A cross-model evaluation of a long conversational agent supported model independence.'},
    ]
    for p in unrelated:
        assert not classify(p)['topics'], p['title']
    text={'title':'Could LLM Watermark Detection be Public?','abstract':'Watermarks for chatbot and agentic outputs, with public detectors for text.'}
    assert classify(text)['topics']==['watermark']

def test_query_date_and_topic_validation():
    q = build_query('agent-security', '2026-10-01', '2026-10-11')
    assert 'submittedDate:' in q and '202609301600' in q
    with pytest.raises(ValueError): build_query('bad', '2026-10-01', '2026-10-11')

def test_affiliation_is_scoped_to_author_block():
    html = '<div class="ltx_authors"><span class="ltx_creator ltx_role_author"><span class="ltx_personname">Alice Example</span><span class="ltx_affiliation">Example University</span></span></div><p>Prior work at Other University.</p>'
    result = parse_affiliations(html, [{'name':'Alice Example','affiliations':[]}])
    assert result['institutions'] == ['Example University']
    assert result['authors'][0]['affiliations'] == ['Example University']
    assert 'Other University' not in str(result)

def test_no_affiliation_is_explicit_unknown():
    r = parse_affiliations('<p>A research paper</p>', [{'name':'Alice','affiliations':[]}])
    assert r['institutions'] == [] and r['affiliation_status'] == '待核实'

def test_latexml_affiliation_label_is_removed():
    html='<div class="ltx_authors"><span class="ltx_creator"><span class="ltx_personname">Alice</span><span class="ltx_contact ltx_role_affiliation"><span class="ltx_contact_name">Affiliation: </span>Example University</span></span></div>'
    r=parse_affiliations(html,[{'name':'Alice','affiliations':[]}])
    assert r['institutions']==['Example University']

def test_unicode_authors_do_not_share_affiliation_by_empty_name():
    html='<div class="ltx_authors"><span class="ltx_creator"><span class="ltx_personname">张三</span><span class="ltx_affiliation">机构甲</span></span><span class="ltx_creator"><span class="ltx_personname">李四</span><span class="ltx_affiliation">机构乙</span></span></div>'
    r=parse_affiliations(html,[{'name':'张三','affiliations':[]},{'name':'李四','affiliations':[]}])
    assert r['authors'][0]['affiliations']==['机构甲'] and r['authors'][1]['affiliations']==['机构乙']

def test_ambiguous_duplicate_names_remain_unassigned():
    html='<div class="ltx_authors"><span class="ltx_creator"><span class="ltx_personname">Wei Wang</span><span class="ltx_affiliation">University A</span></span></div>'
    r=parse_affiliations(html,[{'name':'Wei Wang','affiliations':[]},{'name':'Wei Wang','affiliations':[]}])
    assert not any(a['affiliations'] for a in r['authors'])
    assert r['institutions']==['University A']

def test_plural_context_matches_agent_watermark():
    assert 'agent-watermark' in classify({'title':'Agent Watermarks for Autonomous Agents','abstract':'Behavioral watermarking detects trajectory theft.'})['topics']

def test_storage_preserves_enrichment_and_higher_version(tmp_path):
    store = Store(tmp_path)
    p = paper(); store.upsert(p)
    p['institutions'] = ['Example University']; p['affiliation_source'] = p['url']; store.upsert(p)
    old = paper(); old['version'] = 1; old['title'] = 'Old title'; store.upsert(old)
    assert store.get(p['id'])['title'] == p['title']
    assert store.get(p['id'])['institutions'] == ['Example University']
    assert len(store.papers()) == 1

def test_refetch_preserves_affiliation_source_and_status_together(tmp_path):
    s=Store(tmp_path); p=paper(); p['affiliation_source']='https://arxiv.org/html/2401.12345v2'; s.upsert(p)
    fresh=paper(); fresh.update(institutions=[],affiliation_source='',affiliation_status='待核实')
    fresh['authors'][0]['affiliations']=[]; s.upsert(fresh)
    out=s.get(p['id'])
    assert out['affiliation_source']==p['affiliation_source']
    assert out['affiliation_status']=='已核实作者单位'

def test_vault_import_and_duplicate_preserve_user_text(tmp_path):
    root = tmp_path/'vault'; root.mkdir(); backups = tmp_path/'backups'
    vault = Vault(root, backups)
    p = paper(); p.update(classify(p))
    result = vault.import_papers([p])
    note = Path(result['results'][0]['path'])
    data = yaml.safe_load(note.read_text().split('---')[1])
    assert data['type'] == 'literature-note' and data['discussion_status'] == '参考论文'
    assert data['authors'] and data['keywords']
    note.write_text(note.read_text()+'\nMy private understanding\n')
    before = note.read_bytes()
    again = vault.import_papers([p])
    assert again['results'][0]['status'] == 'skipped' and note.read_bytes() == before
    assert (root/'04-authors/作者索引.md').exists()
    assert (root/'05-keywords/关键词索引.md').exists()
    assert list(backups.glob('*/manifest.json'))

def test_existing_nested_id_and_queue(tmp_path):
    root = tmp_path/'vault'; (root/'03-literature/papers/sub').mkdir(parents=True)
    (root/'03-literature/papers/sub/existing.md').write_text('---\narxiv: "2401.12345v1"\n---\nkeep')
    vault = Vault(root, tmp_path/'backups')
    assert vault.preview([paper()])['items'][0]['action'] == 'skip'
    p = paper(); p['id']='2401.12346'
    out = vault.import_papers([p], queue=True)
    assert 'discussion_status: 待讨论' in Path(out['results'][0]['path']).read_text()
    assert 'v2' in vault.preview([paper()])['items'][0]['reason']

def test_vault_rejects_symlink_escape(tmp_path):
    root = tmp_path/'vault'; root.mkdir(); outside = tmp_path/'outside'; outside.mkdir()
    (root/'03-literature').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='目录'):
        Vault(root, tmp_path/'backups').preview([paper()])

def test_existing_aliased_entity_index_is_reused(tmp_path):
    root=tmp_path/'vault'; (root/'04-authors').mkdir(parents=True)
    index=root/'04-authors/作者索引.md'
    index.write_text('# 作者索引\n\n| 作者 | 机构 | 相关论文 | 备注 |\n|---|---|---|---|\n| [[04-authors/Alice Example|Alice Example]] | Keep University | [[old]] | Keep note |\n')
    Vault(root,tmp_path/'backups').import_papers([paper()])
    text=index.read_text()
    assert text.count('04-authors/Alice Example') == 1
    assert 'Keep University' in text and 'Keep note' in text

def test_preview_conflict_blocks_import(tmp_path):
    root=tmp_path/'vault'; (root/'04-authors').mkdir(parents=True)
    index=root/'04-authors/作者索引.md'
    index.write_text('# 作者索引\n\n| 作者 | 机构 | 相关论文 | 备注 |\n|---|---|---|---|\n')
    vault=Vault(root,tmp_path/'backups'); snapshot=vault.snapshot([paper()])
    index.write_text(index.read_text()+'\nHuman edited this\n')
    with pytest.raises(ValueError, match='变化'): vault.import_papers([paper()], expected_snapshot=snapshot)
