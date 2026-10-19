#!/usr/bin/env python3
"""抓取银联、万事达和中国银行的汇率，写入 data/card_rates.json。

三个来源互相独立：一家失败不影响另外两家，失败的一家保留上一次成功的数字并标记为过期。
运行方式：python scripts/fetch_rates.py
"""
import datetime as dt
import json
import pathlib
import sys
import time

import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "card_rates.json"

CODES = ["USD", "EUR", "GBP", "JPY", "HKD", "TWD", "THB", "SGD", "AUD", "KRW", "CAD", "CHF", "MYR", "NZD"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 中国银行牌价表里的货币名称 → ISO 代码
BOC_NAMES = {
    "美元": "USD", "欧元": "EUR", "英镑": "GBP", "日元": "JPY", "港币": "HKD", "新台币": "TWD",
    "泰国铢": "THB", "新加坡元": "SGD", "澳大利亚元": "AUD", "韩国元": "KRW", "加拿大元": "CAD",
    "瑞士法郎": "CHF", "林吉特": "MYR", "新西兰元": "NZD",
}

BJT = dt.timezone(dt.timedelta(hours=8))


def log(msg):
    print(msg, flush=True)


def warn(msg):
    # GitHub Actions 会把这一行显示成警告
    print(f"::warning::{msg}", flush=True)


# ---------------------------------------------------------------- 银联
def _find_rate_list(obj):
    """在银联返回的 JSON 里找到含 transCur / baseCur / rateData 的列表，兼容外层结构变动。"""
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
    """银联国际每天发布一个 JSON 文件，按日期命名；节假日可能缺文件，往前最多找 7 天。"""
    today = dt.datetime.now(BJT).date()
    last_err = "未知错误"
    for back in range(0, 8):
        day = today - dt.timedelta(days=back)
        url = f"https://www.unionpayintl.com/upload/jfimg/{day:%Y%m%d}.json"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
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
            return {"ok": True, "date": day.isoformat(), "rates": rates}
        last_err = f"文件里没有以人民币计价的汇率（{url}）"
    return {"ok": False, "error": last_err}


# ---------------------------------------------------------------- 万事达
def fetch_mastercard():
    """万事达结算汇率查询接口，逐个币种查询：1 外币 = ? 人民币（账单币种人民币，银行附加费 0）。"""
    page = "https://www.mastercard.us/en-us/personal/get-support/convert-currency.html"
    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
        "Upgrade-Insecure-Requests": "1",
    })
    try:
        session.get(page, timeout=30)  # 先拿页面的 cookie，再调接口
    except Exception:  # noqa: BLE001
        pass
    session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Referer": page,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    session.headers.pop("Upgrade-Insecure-Requests", None)
    rates, errors, fx_date = {}, [], None
    for code in CODES:
        url = (
            "https://www.mastercard.us/settlement/currencyrate/conversion-rate"
            f"?fxDate=0000-00-00&transCurr={code}&crdhldBillCurr=CNY&bankFee=0&transAmt=1"
        )
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            value = data.get("conversionRate")
            if value is None:
                raise ValueError(f"返回里没有 conversionRate：{str(data)[:120]}")
            rates[code] = float(value)
            fx_date = data.get("fxDate") or fx_date
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code}: {str(exc)[:80]}")
            # 连着两个币种都被拒，多半是整站拦截，后面的不用再试
            if len(errors) >= 2 and not rates:
                errors.append("前两个币种都失败，放弃其余币种")
                break
        time.sleep(0.8)
    if rates:
        return {"ok": True, "date": fx_date, "rates": rates, "error": "; ".join(errors) or None}
    return {"ok": False, "error": "; ".join(errors)[:500]}


# ---------------------------------------------------------------- 中国银行
def fetch_boc():
    """中国银行外汇牌价页面的 HTML 表格；页面按 100 外币报价，这里换算成 1 外币。"""
    resp = requests.get("https://www.boc.cn/sourcedb/whpj/", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    def num(text):
        try:
            return round(float(text) / 100, 6)
        except (TypeError, ValueError):
            return None

    rates, latest = {}, None
    for row in soup.select("table tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8:
            continue
        code = BOC_NAMES.get(cells[0])
        if not code:
            continue
        # 发布日期一栏有时已经带了时间，别重复拼
        stamp = cells[6].strip() if ":" in cells[6] else f"{cells[6]} {cells[7]}".strip()
        stamp = stamp.replace("/", "-")
        rates[code] = {
            "hui_buy": num(cells[1]),
            "chao_buy": num(cells[2]),
            "hui_sell": num(cells[3]),
            "chao_sell": num(cells[4]),
            "mid": num(cells[5]),
            "time": stamp,
        }
        latest = max(latest or "", stamp)
    if not rates:
        raise RuntimeError("没有解析到牌价表，页面结构可能变了")
    return {"ok": True, "date": latest, "rates": rates}


# ---------------------------------------------------------------- 汇总
SOURCES = [("unionpay", "银联", fetch_unionpay), ("mastercard", "万事达", fetch_mastercard), ("boc", "中国银行", fetch_boc)]


def main():
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            previous = {}
    prev_sources = previous.get("sources", {})
    prev_rates = previous.get("rates", {})

    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sources": {},
        "rates": {code: {} for code in CODES},
    }
    ok_count = 0
    for key, label, fn in SOURCES:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc)[:300]}
        if result.get("ok"):
            ok_count += 1
            out["sources"][key] = {"ok": True, "date": result.get("date"), "error": result.get("error"), "stale": False}
            for code, value in result["rates"].items():
                out["rates"][code][key] = value
            log(f"[{label}] 成功，{len(result['rates'])} 个币种，日期 {result.get('date')}")
            if result.get("error"):
                warn(f"{label} 部分币种失败：{result['error']}")
        else:
            old = prev_sources.get(key, {})
            out["sources"][key] = {"ok": False, "date": old.get("date"), "error": result.get("error"), "stale": True}
            kept = 0
            for code in CODES:
                if key in prev_rates.get(code, {}):
                    out["rates"][code][key] = prev_rates[code][key]
                    kept += 1
            warn(f"{label} 抓取失败：{result.get('error')}；沿用上次结果 {kept} 个币种")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"写入 data/{OUT.name}，{ok_count}/{len(SOURCES)} 个来源成功")
    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
