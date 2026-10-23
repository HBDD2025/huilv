import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def embedded(path):
    value=json.loads(path.read_text())
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
html=(ROOT/'web/template.html').read_text().replace('__CARD_DATA__',embedded(ROOT/'data/cards.json')).replace('__SOURCE_DATA__',embedded(ROOT/'data/source-status.json')).replace('__HK_DATA__',embedded(ROOT/'data/hk-cards.json'))
html=html.replace('__RECOMMEND_JS__',(ROOT/'web/recommend.js').read_text()).replace('__ADVISOR_JS__',(ROOT/'web/advisor.js').read_text()).replace('__HK_JS__',(ROOT/'web/hk.js').read_text())
(ROOT/'index.html').write_text(html)
if (ROOT/'dist').exists():(ROOT/'dist/index.html').write_text(html)
print('Built self-contained index.html')
