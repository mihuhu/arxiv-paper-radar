import fcntl
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
import httpx

NS={'a':'http://www.w3.org/2005/Atom','os':'http://a9.com/-/spec/opensearch/1.1/','ax':'http://arxiv.org/schemas/atom'}
ID_PATTERN = re.compile(r'^(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7})(?:v\d+)?$')

def normalize_id(value):
    value=str(value).strip()
    value=re.sub(r'^https?://(?:export\.)?arxiv\.org/(?:abs|pdf|html)/','',value)
    value=re.sub(r'\.pdf$','',value)
    if not ID_PATTERN.fullmatch(value): raise ValueError('无效 arXiv ID')
    return re.sub(r'v\d+$','',value)

def _txt(node, path):
    return ' '.join((node.findtext(path,default='',namespaces=NS) or '').split())

def parse_feed(xml):
    root=ET.fromstring(xml)
    if root.tag != '{'+NS['a']+'}feed': raise ValueError('arXiv 未返回 Atom 数据')
    rows=[]
    for e in root.findall('a:entry',NS):
        raw=_txt(e,'a:id')
        if '/api/errors' in raw: raise ValueError('arXiv API: '+_txt(e,'a:summary'))
        pid=normalize_id(raw); ver=re.search(r'v(\d+)$',raw)
        authors=[]
        for a in e.findall('a:author',NS):
            authors.append({'name':_txt(a,'a:name'),'affiliations':[' '.join((x.text or '').split()) for x in a.findall('ax:affiliation',NS) if x.text]})
        institutions=list(dict.fromkeys(x for a in authors for x in a['affiliations']))
        rows.append({'id':pid,'version':int(ver.group(1)) if ver else 1,'title':_txt(e,'a:title'),
            'abstract':_txt(e,'a:summary'),'authors':authors,'published':_txt(e,'a:published'),'updated':_txt(e,'a:updated'),
            'url':f'https://arxiv.org/abs/{pid}','pdf_url':f'https://arxiv.org/pdf/{pid}',
            'categories':[c.get('term','') for c in e.findall('a:category',NS)],
            'institutions':institutions,'affiliation_status':'已核实作者单位' if institutions else '待核实',
            'affiliation_source':f'https://export.arxiv.org/api/query?id_list={pid}' if institutions else '',
            'topics':[],'score':0,'reasons':[]})
    total=int(root.findtext('os:totalResults',default=str(len(rows)),namespaces=NS))
    return rows,total

class Cancelled(Exception): pass

class ArxivClient:
    """One cross-process connection, at least 3s between all arXiv requests."""
    def __init__(self, data_dir, cancel=None, log=None):
        self.root=Path(data_dir); self.root.mkdir(parents=True,exist_ok=True)
        self.cancel=cancel or threading.Event(); self.log=log or (lambda message:None)
    def check(self):
        if self.cancel.is_set(): raise Cancelled('抓取已取消')
    def get(self, url):
        if not re.match(r'^https://(?:export\.)?arxiv\.org/',url): raise ValueError('只允许 arXiv 来源')
        lockpath=self.root/'arxiv.lock'; clockpath=self.root/'arxiv-clock.json'
        for attempt in range(3):
            self.check()
            with lockpath.open('a+') as lock:
                while True:
                    try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); break
                    except BlockingIOError:
                        if self.cancel.wait(.2): self.check()
                try:
                    try: last=float(clockpath.read_text())
                    except (OSError,ValueError): last=0
                    delay=max(0,3.1-(time.time()-last))
                    if delay and self.cancel.wait(delay): self.check()
                    clockpath.write_text(str(time.time()))
                    with httpx.Client(timeout=httpx.Timeout(35,connect=15),follow_redirects=True,headers={'User-Agent':'MihuhuPaperRadar/1.0 (personal literature discovery; single connection)'}) as client:
                        response=client.get(url)
                        response.raise_for_status()
                        return response.text
                except (httpx.TimeoutException,httpx.NetworkError,httpx.HTTPStatusError) as exc:
                    retry=isinstance(exc,(httpx.TimeoutException,httpx.NetworkError)) or exc.response.status_code in (429,500,502,503,504)
                    if not retry or attempt==2: raise
                    self.log(f'arXiv 请求重试 {attempt+1}/2：{type(exc).__name__}')
                finally: fcntl.flock(lock,fcntl.LOCK_UN)
            if self.cancel.wait(3*(2**attempt)): self.check()
        raise RuntimeError('arXiv 请求失败')
    def query(self, query, start=0, count=30, sort='submittedDate'):
        url='https://export.arxiv.org/api/query?'+urlencode({'search_query':query,'start':start,'max_results':count,'sortBy':sort,'sortOrder':'descending'})
        raw=self.get(url)
        cache=self.root/'raw'; cache.mkdir(exist_ok=True)
        key=hashlib.sha256(url.encode()).hexdigest()[:20]
        (cache/(key+'.xml')).write_text(raw)
        (cache/(key+'.json')).write_text(json.dumps({'url':url,'fetched_at':time.time()},ensure_ascii=False,indent=2))
        return parse_feed(raw)
