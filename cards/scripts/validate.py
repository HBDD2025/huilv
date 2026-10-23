#!/usr/bin/env python3
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parents[1]
def validate():
 d=json.loads((ROOT/'data/cards.json').read_text());m=json.loads((ROOT/'data/source-status.json').read_text())
 assert d['schemaVersion']==1
 assert len({c['id'] for c in d['cards']})==len(d['cards'])
 sources={s['id']:s for s in d['sources']};card_ids={c['id'] for c in d['cards']};benefit_ids=set()
 assert len(sources)==len(d['sources'])
 for s in sources.values():
  u=urlsplit(s['url']);assert u.scheme=='https' and u.hostname and not u.username
  dt.date.fromisoformat(s['reviewedAt'])
 for c in d['cards']:
  assert re.fullmatch('[a-z0-9-]+',c['id'])
  assert c['status'] in ['verified','account'] and c['base']>=0
  assert all(x in sources for x in c['sources'])
  for b in c['benefits']:
   assert b['id'] not in benefit_ids;benefit_ids.add(b['id'])
   assert b['source'] in sources
   assert b['cycle'] in ['month','quarter','half','year','anniversary','ongoing','once']
   assert b['status'] in ['verified','account']
  for r in c['rates']:assert r['value']>=0 and r['scenes'] and r['region'] in ['all','us','foreign']
 for p in d['promotions']:
  assert p['source'] in sources and all(c in card_ids for c in p['cards'])
  dt.date.fromisoformat(p['end'])
 for a in d['alerts']:assert a['source'] in sources and set(a['cards'])<=card_ids
 hk=json.loads((ROOT/'data/hk-cards.json').read_text());assert len(hk['cards'])==23
 assert sum(c['type']=='扣账卡' for c in hk['cards'])==6
 assert len({(c['bank'],c['name']) for c in hk['cards']})==23
 from check_sources import trusted
 for c in hk['cards']:
  assert c['type'] in ['信用卡','扣账卡'] and c['bank'] and c['name'] and c['offer'] and c['note'] and c['categories'] and trusted(c['url']) and (not c.get('termsUrl') or trusted(c['termsUrl']))
 assert set(m['sources'])<=sources.keys()|{f'hk-{i+1}' for i in range(len({c['url'] for c in hk['cards']}))}
 # No card numbers, limits, approval dates or secrets are part of the public schema.
 raw=(ROOT/'data/cards.json').read_text()+(ROOT/'data/hk-cards.json').read_text()
 assert not re.search(r'(?i)creditLimit|approvedDate|cardNumber|access_token|api_key',raw)
 print(f"Validated {len(card_ids)} US + {len(hk['cards'])} HK cards, {len(benefit_ids)} benefits, {len(sources)} official sources")
if __name__=='__main__':validate()
