#!/usr/bin/env python3
"""抓取刷卡汇率（银联、JCB）、内地银行牌价、香港银行牌价，写入 data/rates.json。

每个来源互相独立：一家失败不影响其它，失败的沿用上一次成功的数字并标记 stale。
统一口径：内地银行与刷卡汇率 = 1 外币兑人民币；香港银行 = 1 外币兑港元（页面再按 100/10000 换算显示）。
运行：python scripts/fetch_rates.py
"""
import datetime as dt
import json
import pathlib
import re
import ssl
import sys
import time
import xml.etree.ElementTree as ET

import requests
import requests.adapters
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "rates.json"

CODES = ["USD", "EUR", "GBP", "JPY", "HKD", "MOP", "SGD", "AUD", "NZD", "CAD", "CHF", "KRW", "THB",
         "MYR", "IDR", "LAK", "PHP", "DKK", "NOK", "SEK", "RUB", "ZAR"]
HK_CODES = ["CNY"] + [c for c in CODES if c != "HKD"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}
BJT = dt.timezone(dt.timedelta(hours=8))
TIMEOUT = 40

# 各家银行对货币的中文叫法 → ISO 代码
CN_NAMES = {
    "美元": "USD", "美圆": "USD", "欧元": "EUR", "英镑": "GBP", "日元": "JPY", "日圆": "JPY",
    "港币": "HKD", "港元": "HKD", "澳门元": "MOP", "澳门币": "MOP", "新加坡元": "SGD", "新加坡币": "SGD", "新币": "SGD",
    "澳大利亚元": "AUD", "澳元": "AUD", "澳洲元": "AUD", "新西兰元": "NZD", "纽元": "NZD", "加拿大元": "CAD", "加元": "CAD",
    "瑞士法郎": "CHF", "韩元": "KRW", "韩国元": "KRW", "韩币": "KRW", "泰国铢": "THB", "泰铢": "THB",
    "马来西亚林吉特": "MYR", "林吉特": "MYR", "马来西亚元": "MYR", "印尼卢比": "IDR", "印度尼西亚卢比": "IDR", "印尼盾": "IDR",
    "老挝基普": "LAK", "基普": "LAK", "菲律宾比索": "PHP", "丹麦克朗": "DKK", "挪威克朗": "NOK", "瑞典克朗": "SEK",
    "俄罗斯卢布": "RUB", "卢布": "RUB", "南非兰特": "ZAR", "兰特": "ZAR", "人民币": "CNY", "新台币": "TWD",
}
# ISO 数字代码（建行 XML 用）
ISO_NUM = {"840": "USD", "978": "EUR", "826": "GBP", "392": "JPY", "344": "HKD", "446": "MOP", "702": "SGD",
           "036": "AUD", "554": "NZD", "124": "CAD", "756": "CHF", "410": "KRW", "764": "THB", "458": "MYR",
           "360": "IDR", "418": "LAK", "608": "PHP", "208": "DKK", "578": "NOK", "752": "SEK", "643": "RUB",
           "710": "ZAR", "156": "CNY"}


def log(msg):
    print(msg, flush=True)


def warn(msg):
    print(f"::warning::{msg}", flush=True)


def to_code(text):
    """从「美元」「美元(USD)」「USD/CNY」「USD」这类文本里认出 ISO 代码。"""
    if not text:
        return None
    s = str(text).strip()
    m = re.search(r"\b([A-Z]{3})\b", s)
    if m and (m.group(1) in CODES or m.group(1) in ("CNY", "TWD")):
        return m.group(1)
    s2 = re.sub(r"[\s（(].*$", "", s)
    return CN_NAMES.get(s2) or CN_NAMES.get(s)


def num(text):
    """把 "668.28"、"--"、"" 变成浮点数或 None。"""
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    if not s or s in ("--", "-", "—", "/", "N/A", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def scale(rates, usd_key="hui_sell", hint=None):
    """把按 100 外币报价的表统一成 1 外币；用美元价是否大于 50 来判断（1 美元只会是几块钱）。"""
    probe = None
    usd = rates.get("USD") or {}
    for k in (usd_key, "hui_buy", "tt_sell", "tt_buy"):
        if usd.get(k) is not None:
            probe = usd[k]
            break
    per100 = hint if hint is not None else (probe is not None and probe > 50)
    if not per100:
        return rates
    out = {}
    for code, row in rates.items():
        out[code] = {k: (round(v / 100, 6) if isinstance(v, (int, float)) else v) for k, v in row.items()}
    return out


class LegacyTLSAdapter(requests.adapters.HTTPAdapter):
    """部分银行服务器还要求 TLS 旧式重协商，OpenSSL 3 默认拒绝；这里放开那一项，证书校验照常。"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def legacy_session():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.mount("https://", LegacyTLSAdapter())
    return s


def get(url, session=None, insecure_fallback=False, **kw):
    """GET 并检查状态码。insecure_fallback=True 时，TLS 失败先换旧式 TLS 设置重试，再不行就跳过证书校验（只用于读公开牌价）。"""
    kw.setdefault("timeout", TIMEOUT)
    kw.setdefault("headers", HEADERS)
    client = session or requests
    try:
        resp = client.get(url, **kw)
    except requests.exceptions.SSLError as exc:
        if not insecure_fallback:
            raise
        log(f"  TLS 失败，改用旧式 TLS 设置重试：{url}（{str(exc)[-100:]}）")
        try:
            resp = legacy_session().get(url, **kw)
        except requests.exceptions.SSLError:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            log("  仍然失败，跳过证书校验再试一次")
            resp = legacy_session().get(url, verify=False, **kw)
    resp.raise_for_status()
    return resp


def err_text(exc):
    s = str(exc)
    return f"{type(exc).__name__}: " + (s if len(s) <= 320 else s[:120] + " … " + s[-200:])


def parse_generic_table(html, name_col_hint="币种"):
    """解析带「现汇买入/现钞买入/现汇卖出/现钞卖出」表头的 HTML 表格（快易理财网等聚合页通用）。"""
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        header = None
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            if not cells:
                continue
            if header is None:
                if any("买入" in c for c in cells) and any("卖出" in c for c in cells):
                    header = cells
                continue
        if not header:
            continue
        idx = {}
        for i, h in enumerate(header):
            h2 = h.replace(" ", "")
            if "现汇买入" in h2 or "结汇" in h2:
                idx.setdefault("hui_buy", i)
            elif "现钞买入" in h2:
                idx.setdefault("chao_buy", i)
            elif "现汇卖出" in h2 or "购汇" in h2:
                idx.setdefault("hui_sell", i)
            elif "现钞卖出" in h2:
                idx.setdefault("chao_sell", i)
            elif "时间" in h2 or "日期" in h2:
                idx.setdefault("time", i)
        if "hui_buy" not in idx and "hui_sell" not in idx:
            continue
        rates = {}
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(cells) < 3:
                continue
            code = to_code(cells[0])
            if not code or code == "CNY":
                continue
            row = {k: (num(cells[i]) if k != "time" else cells[i]) for k, i in idx.items() if i < len(cells)}
            if any(row.get(k) is not None for k in ("hui_buy", "hui_sell", "chao_buy", "chao_sell")):
                rates[code] = row
        if rates:
            return rates
    raise RuntimeError("页面里没有找到牌价表")


# ================================================================ 刷卡汇率
def _find_rate_list(obj):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and {"transCur", "baseCur", "rateData"} <= set(obj[0]):
            return obj
        for item in obj:
            found = _find_rate_list(item)
            if found:
                return found
    elif isinstance(obj, dict):
        for value in obj.values():
            found = _find_rate_list(value)
            if found:
                return found
    return []


def fetch_unionpay():
    today = dt.datetime.now(BJT).date()
    last_err = "未知错误"
    for back in range(0, 8):
        day = today - dt.timedelta(days=back)
        url = f"https://www.unionpayintl.com/upload/jfimg/{day:%Y%m%d}.json"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}（{url}）"
                continue
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            last_err = f"{exc}（{url}）"
            continue
        rates = {}
        for entry in _find_rate_list(data):
            trans, base, value = entry.get("transCur"), entry.get("baseCur"), entry.get("rateData")
            if base == "CNY" and trans in CODES and value is not None:
                try:
                    rates[trans] = float(value)
                except (TypeError, ValueError):
                    pass
        if rates:
            return {"date": day.isoformat(), "rates": rates}
        last_err = f"文件里没有以人民币计价的汇率（{url}）"
    raise RuntimeError(last_err)


def fetch_jcb():
    """JCB 美元基准日表：索引页 usd.html 列出各日链接 usdMMDDYYYY.html，表内 1 美元 = Buy/Mid/Sell 外币；用 Mid 折算成 1 外币兑人民币。"""
    base = "https://www.jcb.jp/rate/"
    headers = {**HEADERS, "Accept-Language": "ja,en;q=0.8,zh-CN;q=0.6", "Referer": base + "usd.html"}
    index = get(base + "usd.html", headers=headers)
    links = re.findall(r'href="([^"]*usd(\d{8})\.html)"', index.text)
    if not links:
        raise RuntimeError("索引页里没有找到日表链接")
    # 文件名是 MMDDYYYY，按 YYYYMMDD 排序取最新
    links.sort(key=lambda x: x[1][4:] + x[1][:4], reverse=True)
    errors = []
    for href, stamp in links[:3]:
        url = href if href.startswith("http") else base + href.lstrip("/").split("rate/")[-1]
        try:
            resp = get(url, headers=headers)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        mids = {}
        for tr in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            # 行的样子：USD ｜ = ｜ Buy ｜ Mid ｜ Sell ｜ CNY，报价币种在最后一个三字母格
            found = [c.strip() for c in cells if re.fullmatch(r"[A-Z]{3}", c.strip())]
            if not found or (len(found) == 1 and found[0] == "USD"):
                continue
            code = found[-1]
            nums = [num(c) for c in cells if num(c) is not None]
            if len(nums) >= 3:
                mids[code] = nums[1]  # Buy / Mid / Sell
            elif nums:
                mids[code] = nums[0]
        usd_cny = mids.get("CNY")
        if not usd_cny:
            errors.append(f"{url}: 表里没有 CNY")
            continue
        rates = {"USD": round(usd_cny, 6)}
        for code in CODES:
            if code != "USD" and mids.get(code):
                rates[code] = round(usd_cny / mids[code], 8)
        return {"date": f"{stamp[4:]}-{stamp[:2]}-{stamp[2:4]}", "rates": rates}
    raise RuntimeError("; ".join(errors)[:300])


# ================================================================ 内地银行（1 外币兑人民币）
def fetch_boc():
    resp = get("https://www.boc.cn/sourcedb/whpj/")
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    rates = {}
    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8:
            continue
        code = to_code(cells[0])
        if not code or code == "CNY":
            continue
        stamp = cells[6].strip() if ":" in cells[6] else f"{cells[6]} {cells[7]}".strip()
        rates[code] = {"hui_buy": num(cells[1]), "chao_buy": num(cells[2]), "hui_sell": num(cells[3]),
                       "chao_sell": num(cells[4]), "time": stamp.replace("/", "-")}
    if not rates:
        raise RuntimeError("没有解析到牌价表")
    rates = scale(rates, hint=True)
    return {"date": max(r["time"] for r in rates.values()), "rates": rates}


def fetch_icbc():
    resp = get("https://papi.icbc.com.cn/exchanges/ns/getLatest", insecure_fallback=True, headers={**HEADERS, "Accept": "application/json"})
    data = resp.json()
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"返回不是预期结构：{str(data)[:120]}")
    rates = {}
    for r in rows:
        code = to_code(r.get("currencyENName")) or to_code(r.get("currencyCHName"))
        if not code or code == "CNY":
            continue
        rates[code] = {"hui_buy": num(r.get("foreignBuy")), "chao_buy": num(r.get("cashBuy")),
                       "hui_sell": num(r.get("foreignSell")), "chao_sell": num(r.get("cashSell")),
                       "time": f"{r.get('publishDate', '')} {r.get('publishTime', '')}".strip()}
    if not rates:
        raise RuntimeError("接口返回里没有认得的币种")
    rates = scale(rates)
    return {"date": max(r["time"] for r in rates.values()), "rates": rates}


def fetch_abc():
    resp = get("https://ewealth.abchina.com/app/data/api/DataService/ExchangeRateV2", insecure_fallback=True, headers={**HEADERS, "Accept": "application/json"})
    data = resp.json()
    table = (((data or {}).get("Data") or {}).get("Table")) if isinstance(data, dict) else None
    if not isinstance(table, list):
        raise RuntimeError(f"返回不是预期结构：{str(data)[:120]}")
    rates = {}
    for r in table:
        code = to_code(r.get("CurrName"))
        if not code or code == "CNY":
            continue
        t = str(r.get("PublishTime", ""))[:19].replace("T", " ")
        rates[code] = {"hui_buy": num(r.get("BuyingPrice")), "chao_buy": num(r.get("CashBuyingPrice")),
                       "hui_sell": num(r.get("SellPrice")), "chao_sell": num(r.get("SellPrice")), "time": t}
    if not rates:
        raise RuntimeError("接口返回里没有认得的币种")
    rates = scale(rates)
    return {"date": max(r["time"] for r in rates.values()), "rates": rates}


def fetch_ccb():
    resp = get("https://www2.ccb.com/cn/home/news/jshckpj_new.xml", insecure_fallback=True, headers={**HEADERS, "Accept": "application/xml,text/xml,*/*"})
    root = ET.fromstring(resp.content)
    rates = {}
    for node in root.iter():
        if not node.tag.endswith("ReferencePriceSettlement"):
            continue
        f = {child.tag.split("}")[-1]: (child.text or "").strip() for child in node}
        code = ISO_NUM.get(f.get("Ofrd_Ccy_CcyCd", "").zfill(3))
        if not code or code == "CNY":
            continue
        d, t = f.get("LstPr_Dt", ""), f.get("LstPr_Tm", "")
        stamp = f"{d[:4]}-{d[4:6]}-{d[6:8]} {t[:2]}:{t[2:4]}:{t[4:6]}" if len(d) == 8 and len(t) == 6 else f"{d} {t}".strip()
        rates[code] = {"hui_buy": num(f.get("BidRateOfCcy")), "chao_buy": num(f.get("BidRateOfCash")),
                       "hui_sell": num(f.get("OfrRateOfCcy")), "chao_sell": num(f.get("OfrRateOfCash")), "time": stamp}
    if not rates:
        raise RuntimeError("XML 里没有牌价节点")
    rates = scale(rates)
    return {"date": max(r["time"] for r in rates.values()), "rates": rates}


def fetch_bocom():
    resp = get("https://www.bankcomm.com/BankCommSite/zh-cn/personal/forex/forexQuotation.html", insecure_fallback=True)
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    m = re.search(r"更新时间[：:]\s*([\d\-/]+\s*[\d:]*)", soup.get_text(" "))
    stamp = m.group(1).strip().replace("/", "-") if m else ""
    rates = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if len(cells) < 6:
            continue
        code = to_code(cells[0])
        if not code or code == "CNY":
            continue
        unit = num(cells[1]) or 1
        vals = [num(c) for c in cells[2:6]]
        # 列序：现汇买入｜现汇卖出｜现钞买入｜现钞卖出
        rates[code] = {"hui_buy": vals[0] / unit if vals[0] is not None else None,
                       "hui_sell": vals[1] / unit if vals[1] is not None else None,
                       "chao_buy": vals[2] / unit if vals[2] is not None else None,
                       "chao_sell": vals[3] / unit if vals[3] is not None else None, "time": stamp}
    if not rates:
        raise RuntimeError("页面里没有牌价行（可能是 JS 渲染或被拦截）")
    return {"date": stamp, "rates": rates}


def fetch_cib():
    session = requests.Session()
    session.headers.update(HEADERS)
    page = session.get("https://personalbank.cib.com.cn/pers/main/pubinfo/ifxQuotationQuery.do", timeout=TIMEOUT)
    page.raise_for_status()
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日[^\d]{0,12}(\d{1,2}:\d{2}:\d{2})", page.text)
    stamp = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} {m.group(4)}" if m else ""
    url = ("https://personalbank.cib.com.cn/pers/main/pubinfo/ifxQuotationQuery/list"
           f"?_search=false&dataSet.nd={int(time.time() * 1000)}&dataSet.rows=80&dataSet.page=1&dataSet.sidx=&dataSet.sort=asc")
    resp = session.get(url, timeout=TIMEOUT, headers={**HEADERS, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                                                      "Referer": "https://personalbank.cib.com.cn/pers/main/pubinfo/ifxQuotationQuery.do"})
    resp.raise_for_status()
    data = resp.json()
    rates = {}
    for row in data.get("rows") or []:
        cell = row.get("cell") or []
        if len(cell) < 7:
            continue
        code = to_code(cell[1]) or to_code(cell[0])
        if not code or code == "CNY":
            continue
        unit = num(cell[2]) or 100
        # 列序：中文名｜代码｜单位｜现汇买入｜现汇卖出｜现钞买入｜现钞卖出
        vals = [num(c) for c in cell[3:7]]
        rates[code] = {"hui_buy": vals[0] / unit if vals[0] is not None else None,
                       "hui_sell": vals[1] / unit if vals[1] is not None else None,
                       "chao_buy": vals[2] / unit if vals[2] is not None else None,
                       "chao_sell": vals[3] / unit if vals[3] is not None else None, "time": stamp}
    if not rates:
        raise RuntimeError("接口返回 rows 为空（可能需要会话 cookie）")
    return {"date": stamp, "rates": rates}


def make_kylc(slug):
    """快易理财网的单家银行牌价页：按 1 外币报价，时间形如 MM-DD HH:mm。"""
    def fetch():
        resp = get(f"https://www.kylc.com/bank/rmbfx/b-{slug}.html")
        resp.encoding = resp.apparent_encoding or "utf-8"
        rates = parse_generic_table(resp.text)
        year = dt.datetime.now(BJT).year
        for r in rates.values():
            t = r.get("time") or ""
            if re.fullmatch(r"\d{2}-\d{2} \d{2}:\d{2}", t):
                r["time"] = f"{year}-{t}"
        rates = scale(rates)
        return {"date": max((r.get("time") or "") for r in rates.values()), "rates": rates}
    return fetch


def fetch_cbhb_ipcn():
    """ip.cn 的渤海银行牌价页：列序 货币｜现汇买入｜现汇卖出｜现钞买入｜现钞卖出｜发布时间，按 1 外币报价。"""
    resp = get("https://ip.cn/paijia/cbhb.html")
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")
    rates = {}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        if len(cells) < 6:
            continue
        code = to_code(cells[0])
        if not code or code == "CNY":
            continue
        vals = [num(c) for c in cells[1:5]]
        rates[code] = {"hui_buy": vals[0], "hui_sell": vals[1], "chao_buy": vals[2], "chao_sell": vals[3], "time": cells[5].replace("/", "-")}
    if not rates:
        raise RuntimeError("页面里没有找到牌价表")
    rates = scale(rates)
    return {"date": max(r.get("time") or "" for r in rates.values()), "rates": rates}


# ================================================================ 香港银行（1 外币兑港元）
# 每个抓取函数返回 {"date", "rates": {CODE: {tt_buy, tt_sell, note_buy, note_sell, time}}}
HK_FETCHERS = {}

# ================================================================ 汇总
SOURCES = [
    # key, 显示名, 分组, 来源, 函数
    ("unionpay", "银联", "card", "官网", fetch_unionpay),
    ("jcb", "JCB", "card", "官网", fetch_jcb),
    ("icbc", "工商银行", "cn", "官网", fetch_icbc),
    ("abc", "农业银行", "cn", "官网", fetch_abc),
    ("boc", "中国银行", "cn", "官网", fetch_boc),
    ("ccb", "建设银行", "cn", "官网", fetch_ccb),
    ("bocom", "交通银行", "cn", "官网", fetch_bocom),
    ("cib", "兴业银行", "cn", "官网", fetch_cib),
    ("citic", "中信银行", "cn", "kylc", make_kylc("citic")),
    ("cgb", "广发银行", "cn", "kylc", make_kylc("cgb")),
    ("pab", "平安银行", "cn", "kylc", make_kylc("pab")),
    ("nbcb", "宁波银行", "cn", "kylc", make_kylc("nbcb")),
    ("shengjing", "盛京银行", "cn", "kylc", make_kylc("shengjingb")),
    ("cbhb", "渤海银行", "cn", "ipcn", fetch_cbhb_ipcn),
]
SOURCES += [(key, name, "hk", origin, fn) for key, (name, origin, fn) in HK_FETCHERS.items()]


def main():
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            previous = {}
    prev_sources = previous.get("sources", {})

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sources": {},
        "card": {code: {} for code in CODES},
        "banks_cn": {},
        "banks_hk": {},
    }
    ok_count = 0
    for key, label, group, origin, fn in SOURCES:
        started = time.time()
        try:
            result = fn()
            if not result or not result.get("rates"):
                raise RuntimeError("没有数据")
        except Exception as exc:  # noqa: BLE001
            result = None
            err = err_text(exc)
        if result:
            ok_count += 1
            if group != "card":
                for row in result["rates"].values():
                    for k, v in list(row.items()):
                        if isinstance(v, float):
                            row[k] = round(v, 6)
            out["sources"][key] = {"ok": True, "date": result.get("date"), "stale": False, "name": label, "group": group, "origin": origin, "error": None}
            if group == "card":
                for code, value in result["rates"].items():
                    if code in out["card"]:
                        out["card"][code][key] = value
            elif group == "cn":
                out["banks_cn"][key] = result["rates"]
            else:
                out["banks_hk"][key] = result["rates"]
            log(f"[{label}] 成功，{len(result['rates'])} 个币种，日期 {result.get('date')}，{time.time() - started:.1f}s")
        else:
            old = prev_sources.get(key, {})
            out["sources"][key] = {"ok": False, "date": old.get("date"), "stale": True, "name": label, "group": group, "origin": origin, "error": err}
            kept = 0
            if group == "card":
                for code in CODES:
                    v = (previous.get("card", {}).get(code) or {}).get(key)
                    if v is not None:
                        out["card"][code][key] = v
                        kept += 1
            else:
                bucket = "banks_cn" if group == "cn" else "banks_hk"
                old_rates = previous.get(bucket, {}).get(key)
                if old_rates:
                    out[bucket][key] = old_rates
                    kept = len(old_rates)
            warn(f"{label} 抓取失败：{err}；沿用上次 {kept} 个币种")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"写入 data/{OUT.name}，{ok_count}/{len(SOURCES)} 个来源成功")
    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
