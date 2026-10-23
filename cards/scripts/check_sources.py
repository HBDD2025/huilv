#!/usr/bin/env python3
"""Check official public pages. Never convert a page diff into a verified benefit."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ALLOWED={'americanexpress.com','hilton.com','chase.com','ihgplc.com','capitalone.com','capitalonetravel.com','citi.com','bankofamerica.com','alaskaair.com','hsbc.com.hk','icbcasia.com','asia.ccb.com','cncbinternational.com','bochk.com','hangseng.com','hkbea.com','sc.com','cmbwinglungbank.com'}
def trusted(url):
    u=urllib.parse.urlsplit(url)
    return u.scheme=='https' and u.hostname and not u.username and not u.password and any(u.hostname==d or u.hostname.endswith('.'+d) for d in ALLOWED)
class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not trusted(newurl):raise ValueError('重定向目标不在官方域名清单')
        return super().redirect_request(req,fp,code,msg,headers,newurl)
class Text(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','noscript','svg'}:self.skip+=1
        if tag in {'br','p','li','h1','h2','h3','h4','div'}:self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript','svg'}:self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)
def fingerprint(html):
    p=Text();p.feed(html)
    text='\n'.join(' '.join(line.split()) for line in ''.join(p.parts).splitlines() if line.strip())
    # Keep reward-related lines, not entire copyrighted web pages. Cookie banners,
    # review widgets and changing welcome offers can still trigger false positives.
    lines=[line for line in text.splitlines() if re.search(r'\$|\bpoints?\b|\bmiles?\b|\bcredit\b|\breward\b|\blounge\b|\banniversary\b|\bfee\b|\b\d+[xX%]\b|existing card|回贈|優惠|積分|獎賞|年費|签账|簽賬|現金',line,re.I)]
    evidence='\n'.join(lines)
    lower=text.lower()
    if len(text)<500 or len(evidence)<150 or len(lines)<5:raise ValueError('网页内容不足，可能依赖登录或 JavaScript')
    if any(x in lower for x in ('access denied','verify you are human','just a moment','captcha','temporarily unavailable')):raise ValueError('被站点验证或临时不可用页面拦截')
    return hashlib.sha256(evidence.encode()).hexdigest(),len(lines)
def inspect(source,old,now):
    previous=dict(old or {})
    result={**previous,'attemptedAt':now}
    try:
        if not trusted(source['url']):raise ValueError('不是允许的官方 HTTPS 来源')
        request=urllib.request.Request(source['url'],headers={'User-Agent':'CardGuideSourceMonitor/1.0 (public benefits reference; daily check)','Accept':'text/html'})
        with urllib.request.build_opener(OfficialRedirect()).open(request,timeout=25) as response:
            if not trusted(response.geturl()):raise ValueError('最终来源不在清单')
            if 'text/html' not in response.headers.get('Content-Type',''):raise ValueError('来源不是 HTML，请人工检查')
            raw=response.read(3_000_001)
            if len(raw)>3_000_000:raise ValueError('页面过大，未作为成功抓取')
            html=raw.decode(response.headers.get_content_charset() or 'utf-8',errors='replace')
        digest,lines=fingerprint(html)
        changed=bool(previous.get('sha256') and previous['sha256']!=digest)
        # needsReview remains true until a human/agent explicitly acknowledges it.
        result.update(status='changed' if changed else 'unchanged' if previous.get('sha256') else 'baseline',sha256=digest,lastSuccessAt=now,needsReview=bool(previous.get('needsReview')) or changed,matchedLines=lines)
        if changed:result['changedAt']=now
        result.pop('error',None)
    except (OSError,ValueError,urllib.error.URLError) as exc:
        # Keep prior success and pending flag. A failure must never look current.
        result.update(status='failed',error=str(exc)[:170])
    return source['id'],result

def main():
    data=json.loads((ROOT/'data/cards.json').read_text())
    hk=json.loads((ROOT/'data/hk-cards.json').read_text())
    urls=dict.fromkeys(c['url'] for c in hk['cards'])
    hk_sources=[{'id':f'hk-{i+1}','label':next(c['bank']+' · '+c['name'] for c in hk['cards'] if c['url']==url),'url':url} for i,url in enumerate(urls)]
    all_sources=data['sources']+hk_sources
    path=ROOT/'data/source-status.json'
    previous=json.loads(path.read_text()) if path.exists() else {'sources':{}}
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=dict(pool.map(lambda s:inspect(s,previous.get('sources',{}).get(s['id']),now),all_sources))
    out={'lastRun':now,'mode':'github_actions','sources':results}
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    counts={k:sum(s['status']==k for s in results.values()) for k in ['baseline','unchanged','changed','failed']}
    print(json.dumps(counts,ensure_ascii=False))
    summary=ROOT/'data/monitor-summary.md'
    summary.write_text('# 官方来源巡检\n\n'+now+'\n\n'+'\n'.join('- '+s['label']+': '+results[s['id']]['status'] for s in all_sources)+'\n\n抓取结果不等于人工内容核验。失败不会覆盖上次成功的指纹，变化不会自动写成权益。\n')
if __name__=='__main__':main()
