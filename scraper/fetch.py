# -*- coding: utf-8 -*-
"""
抓取中国各基金公司「美股 QDII 基金」的申购状态 / 单日限额 / 净值，
聚合后写入 docs/data.json 供前端看板读取。

数据来源：天天基金网（非官方接口，仅供参考，不构成投资建议）
接口字段/结构可能随对方改版变化，脚本已做容错，出问题优先看日志核对字段。

只用标准库（urllib），无需第三方依赖。
"""
import json
import os
import re
import ssl
import sys
import time
import datetime
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")

# 只在这两类里找：QDII-* 和 指数型-海外股票（纳指/标普 ETF联接就在后者）
US_KW = ["标普", "纳斯达克", "纳指", "道琼斯", "道指", "美股", "美国"]
# 名称里出现这些则排除（美元债、港股、A股红利等非“美股”标的）
EXCLUDE_KW = ["债", "货币", "港股", "香港", "A股", "中国", "恒生", "红利低波"]

_SSL = ssl.create_default_context()


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def http_get(url, referer="http://fund.eastmoney.com/", timeout=20, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
                raw = resp.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("gbk", errors="replace")
        except Exception as e:  # 网络抖动时重试
            last = e
            time.sleep(0.6 * (attempt + 1))
    raise last


def strip_tags(x):
    return re.sub(r"<[^>]+>", "", x or "").replace("&nbsp;", " ").strip()


def get_fund_universe():
    """全量基金库：[[code, pinyin, name, type, pinyinfull], ...]"""
    txt = http_get("http://fund.eastmoney.com/js/fundcode_search.js")
    m = re.search(r"=\s*(\[.*\]);?\s*$", txt, re.S)
    return json.loads(m.group(1)) if m else []


def is_us_equity(name, ftype):
    if not ("QDII" in ftype or "海外股票" in ftype):
        return False
    if any(e in name for e in EXCLUDE_KW):
        return False
    return any(k in name for k in US_KW)


def get_detail(code):
    """基金主页：交易状态(申购状态) + 单日累计限额 + 基金公司"""
    result = {"buy_status": None, "daily_limit": None, "company": None}
    try:
        html = http_get(f"http://fund.eastmoney.com/{code}.html", timeout=15)
    except Exception as e:
        log(f"  主页失败 {code}: {e}")
        return result

    m = re.search(r"交易状态：</span><span class=\"staticCell\">(.*?)</span>"
                  r"<span class=\"staticCell\">", html, re.S)
    if m:
        raw = strip_tags(m.group(1))
        status = re.split(r"[\s(（]", raw)[0] or None
        result["buy_status"] = status
        # 仅在“限大额/限购”状态下保留单日限额；暂停/开放/场内不显示限额
        lm = re.search(r"单日累计[^\d]*([\d.]+\s*[万亿]?元)", raw)
        if lm and status and "限" in status:
            result["daily_limit"] = lm.group(1).strip()

    cm = (re.search(r"基金公司</a>：.*?<a[^>]*>(.*?)</a>", html, re.S)
          or re.search(r"/company/\d+\.html[^>]*>(.*?)</a>", html, re.S))
    if cm:
        result["company"] = strip_tags(cm.group(1))
    return result


def get_gz(code):
    """fundgz 接口：单位净值 + 净值日期（前端盘中估值用的也是它）"""
    try:
        text = http_get(f"https://fundgz.1234567.com.cn/js/{code}.js", timeout=10)
        m = re.search(r"jsonpgz\((.*?)\);", text)
        if not m:
            return {}
        j = json.loads(m.group(1))
        return {"nav": j.get("dwjz"), "nav_date": j.get("jzrq")}
    except Exception as e:
        log(f"  fundgz 失败 {code}: {e}")
        return {}


def collect_funds():
    universe = get_fund_universe()
    log(f"全量基金库：{len(universe)}")
    funds, seen = [], set()
    for a in universe:
        code, name, ftype = a[0], a[2], a[3]
        if code in seen:
            continue
        if is_us_equity(name, ftype):
            funds.append({"code": code, "name": name})
            seen.add(code)

    # 合并人工白名单（补漏）
    wl_path = os.path.join(os.path.dirname(__file__), "funds_whitelist.json")
    if os.path.exists(wl_path):
        for f in json.load(open(wl_path, encoding="utf-8")):
            if f.get("code") and f["code"] not in seen:
                funds.append({"code": f["code"], "name": f.get("name", f["code"])})
                seen.add(f["code"])
    return funds


def main():
    funds = collect_funds()
    log(f"命中美股 QDII：{len(funds)}")

    by_company = {}
    for i, f in enumerate(funds, 1):
        detail = get_detail(f["code"])
        gz = get_gz(f["code"])
        company = detail.get("company") or "未知"
        by_company.setdefault(company, []).append({
            "code": f["code"],
            "name": f["name"],
            "buy_status": detail.get("buy_status"),
            "daily_limit": detail.get("daily_limit"),
            "nav": gz.get("nav"),
            "nav_date": gz.get("nav_date"),
        })
        log(f"[{i}/{len(funds)}] {f['code']} {f['name']} "
            f"状态={detail.get('buy_status')} 限额={detail.get('daily_limit')}")
        time.sleep(0.15)  # 降频，别把自己封了

    result = {
        "updated_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat(timespec="seconds"),
        "source": "天天基金网（非官方接口，仅供参考，不构成投资建议）",
        "companies": [
            {"company": c, "funds": sorted(fs, key=lambda x: x["code"])}
            for c, fs in sorted(by_company.items())
        ],
    }

    os.makedirs(os.path.join(DOCS, "history"), exist_ok=True)
    with open(os.path.join(DOCS, "data.json"), "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)
    today = datetime.date.today().isoformat()
    with open(os.path.join(DOCS, "history", f"{today}.json"), "w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2)

    total = sum(len(x["funds"]) for x in result["companies"])
    log(f"完成：{len(result['companies'])} 家公司，{total} 只基金 -> docs/data.json")


if __name__ == "__main__":
    main()
