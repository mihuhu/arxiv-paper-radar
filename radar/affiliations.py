import copy
import re
import unicodedata
from bs4 import BeautifulSoup

def _clean(node):
    clone=BeautifulSoup(str(node),'html.parser')
    for x in clone.select('sup,.ltx_note_mark,.ltx_tag,.ltx_contact_name'): x.decompose()
    return ' '.join(clone.get_text(' ',strip=True).split()).strip(' ,;')

def _key(name): return ''.join(c for c in unicodedata.normalize('NFKD',name.casefold()) if c.isalnum())

def parse_affiliations(html, authors):
    soup=BeautifulSoup(html,'html.parser'); updated=copy.deepcopy(authors)
    institutions=[]
    for block in soup.select('.ltx_authors'):
        for node in block.select('.ltx_affiliation,.ltx_role_affiliation'):
            text=_clean(node)
            if text and len(text)<700 and '@' not in text: institutions.append(text)
        # Only assign an institution if this creator names exactly one known author.
        for creator in block.select('.ltx_creator'):
            names=creator.select('.ltx_personname'); affs=creator.select('.ltx_affiliation,.ltx_role_affiliation')
            if len(names)!=1 or not affs: continue
            key=_key(_clean(names[0])); values=[_clean(a) for a in affs]
            values=[v for v in values if v and '@' not in v and len(v)<700]
            matches=[a for a in updated if key and _key(a['name'])==key]
            if len(matches)==1:
                a=matches[0]; a['affiliations']=list(dict.fromkeys(a.get('affiliations',[])+values))
    institutions=list(dict.fromkeys(institutions+[x for a in updated for x in a.get('affiliations',[])]))
    mapped=any(a.get('affiliations') for a in updated)
    status='已核实作者单位' if mapped else ('已核实论文单位（未逐作者对应）' if institutions else '待核实')
    return {'authors':updated,'institutions':institutions,'affiliation_status':status}

def enrich_paper(paper, client):
    url=f"https://arxiv.org/html/{paper['id']}v{paper['version']}"
    try:
        html=client.get(url)
        if hasattr(client,'root'):
            folder=client.root/'raw'; folder.mkdir(exist_ok=True)
            (folder/(paper['id'].replace('/','-')+'v'+str(paper['version'])+'.html')).write_text(html)
        result=parse_affiliations(html,paper['authors'])
        paper.update(result)
        if result['institutions']: paper['affiliation_source']=url
        paper['affiliation_note']='单位来自论文作者栏；未逐作者对应的单位不作个人归属判断。' if result['institutions'] else 'arXiv HTML 作者栏未提供可自动核实的单位，可查看原文 PDF。'
    except Exception as exc:
        from radar.arxiv import Cancelled
        if isinstance(exc,Cancelled): raise
        paper['affiliation_note']=f'单位核验未完成：{type(exc).__name__}；可查看原文 PDF。'
    return paper
