"""主力潜伏选股 · 真实数据层

数据来源优先级：
  行情（现价 / 涨跌幅）：同花顺 Financial-API（需 HITHINK_FINANCE_API_KEY）
                        → akshare 东财实时行情
                        → 个股资金流里的最新收盘价
                        → 模拟数据
  主力资金流向：akshare（东财口径；同花顺官方文档明确说明资金流接口
                不对外开放，仅在同花顺 AI 客户端内部使用）
  K 线：akshare（东财，前复权）
全部失败时用内置模拟数据兜底，并在界面标注数据来源。
"""

import os
from datetime import datetime, timedelta

import pandas as pd
import requests

THS_BASE = "https://fuyao.aicubes.cn"
SNAPSHOT_URL = f"{THS_BASE}/api/a-share/prices/snapshot"

# 监控池：代码、名称、分类、模拟兜底值（沿用原型 v0.1 的模拟数）
WATCHLIST = [
    {"代码": "300604", "名称": "长川科技", "分类": "热门赛道+半导体", "模拟现价": 178.09,
     "模拟持续流入天数": 47, "模拟首次流入日期": "2025-09-15", "模拟累计净流入亿": 18.5,
     "模拟相对大盘": "强于大盘", "模拟建议卖出价": "220-250"},
    {"代码": "688981", "名称": "中芯国际", "分类": "热门赛道+半导体", "模拟现价": 85.60,
     "模拟持续流入天数": 32, "模拟首次流入日期": "2025-10-08", "模拟累计净流入亿": 12.3,
     "模拟相对大盘": "强于大盘", "模拟建议卖出价": "95-110"},
    {"代码": "002371", "名称": "北方华创", "分类": "热门赛道+半导体", "模拟现价": 320.50,
     "模拟持续流入天数": 28, "模拟首次流入日期": "2025-10-20", "模拟累计净流入亿": 15.8,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "360-400"},
    {"代码": "300750", "名称": "宁德时代", "分类": "新能源", "模拟现价": 198.30,
     "模拟持续流入天数": 15, "模拟首次流入日期": "2025-11-01", "模拟累计净流入亿": 9.2,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "230-260"},
    {"代码": "600519", "名称": "贵州茅台", "分类": "大市值蓝筹+消费", "模拟现价": 1650.00,
     "模拟持续流入天数": 5, "模拟首次流入日期": "2025-11-10", "模拟累计净流入亿": 3.1,
     "模拟相对大盘": "弱于大盘", "模拟建议卖出价": "1800-2000"},
    {"代码": "000858", "名称": "五粮液", "分类": "大市值蓝筹+消费", "模拟现价": 128.50,
     "模拟持续流入天数": 8, "模拟首次流入日期": "2025-11-05", "模拟累计净流入亿": 4.5,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "145-160"},
    {"代码": "300014", "名称": "亿纬锂能", "分类": "新能源", "模拟现价": 45.20,
     "模拟持续流入天数": 22, "模拟首次流入日期": "2025-10-25", "模拟累计净流入亿": 7.8,
     "模拟相对大盘": "强于大盘", "模拟建议卖出价": "55-65"},
    {"代码": "601318", "名称": "中国平安", "分类": "周期金融", "模拟现价": 48.60,
     "模拟持续流入天数": 3, "模拟首次流入日期": "2025-11-15", "模拟累计净流入亿": 1.2,
     "模拟相对大盘": "弱于大盘", "模拟建议卖出价": "55-60"},
    {"代码": "002415", "名称": "海康威视", "分类": "大市值蓝筹", "模拟现价": 32.80,
     "模拟持续流入天数": 12, "模拟首次流入日期": "2025-11-08", "模拟累计净流入亿": 5.6,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "38-42"},
]

MOCK_SCORES = {
    "300604": (92, 88, 85), "688981": (85, 82, 80), "002371": (88, 90, 86),
    "300750": (78, 85, 75), "600519": (65, 95, 70), "000858": (70, 92, 72),
    "300014": (82, 80, 78), "601318": (60, 88, 65), "002415": (75, 83, 70),
}


def get_hithink_key():
    """从 Streamlit secrets 或环境变量取同花顺 Financial-API Key。"""
    try:
        import streamlit as st
        key = st.secrets.get("HITHINK_FINANCE_API_KEY")
        if key:
            return str(key).strip()
    except Exception:
        pass
    return (os.environ.get("HITHINK_FINANCE_API_KEY") or "").strip() or None


def to_ths_code(code):
    """6 位 A 股代码 → 同花顺代码：600519.SH / 300604.SZ / 430001.BJ。"""
    if code.startswith("6"):
        return code + ".SH"
    if code.startswith(("0", "3")):
        return code + ".SZ"
    return code + ".BJ"


def market_of(code):
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    return "bj"


def _clip(x, lo=0, hi=100):
    return max(lo, min(hi, round(float(x), 1)))


# ---------------- 同花顺 Financial-API：行情快照 ----------------

def fetch_quotes_hithink(codes):
    """GET /api/a-share/prices/snapshot。成功返回 {code: dict}，失败返回 None。"""
    key = get_hithink_key()
    if not key:
        return None
    try:
        resp = requests.get(
            SNAPSHOT_URL,
            params={
                "thscodes": ",".join(to_ths_code(c) for c in codes),
                "fields": "last_price,change_rate,volume,turnover,prev_close,"
                          "open_price,high_price,low_price,amplitude,turnover_rate",
            },
            headers={"X-api-key": key},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        if payload.get("code") != 0:
            return None
        out = {}
        for item in payload.get("data", {}).get("item", []):
            code = str(item.get("thscode", "")).split(".")[0]
            if not code:
                continue
            out[code] = {
                "price": float(item.get("last_price") or 0),
                "change_pct": float(item.get("change_rate") or 0),
                "volume": float(item.get("volume") or 0),
                "turnover": float(item.get("turnover") or 0),
                "prev_close": float(item.get("prev_close") or 0),
            }
        return out or None
    except Exception:
        return None


# ---------------- akshare：行情 / 资金流 / K 线 ----------------

def fetch_quotes_akshare(codes):
    """东财实时行情。成功返回 {code: dict}，失败返回 None。"""
    try:
        import akshare as ak
        spot = ak.stock_zh_a_spot_em()
        spot = spot[spot["代码"].astype(str).isin(codes)]
        out = {}
        for _, r in spot.iterrows():
            code = str(r["代码"])
            out[code] = {
                "price": float(r["最新价"]),
                "change_pct": float(r["涨跌幅"]),
                "volume": float(r["成交量"]),
                "turnover": float(r["成交额"]),
                "prev_close": float(r["昨收"]),
            }
        return out or None
    except Exception:
        return None


def fetch_fund_flow(code):
    """akshare 个股资金流（近约 100 个交易日，东财口径）。
    返回 dict：streak_days / cum_inflow（亿）/ first_date / outflow_days /
    stall_days / last_date / last_price / last_change / flow_df（近 60 日）。失败返回 None。"""
    try:
        import akshare as ak
        ff = ak.stock_fund_flow_individual_hist_em(symbol=code, market=market_of(code))
        if ff is None or ff.empty:
            return None
        ff = ff.sort_values("日期").reset_index(drop=True)
        ff["日期"] = pd.to_datetime(ff["日期"])
        net = ff["主力净流入-净额"].astype(float)
        vals = net.tolist()

        streak = 0
        for v in reversed(vals):
            if v > 0:
                streak += 1
            else:
                break
        cum = float(net.iloc[-streak:].sum()) / 1e8 if streak else 0.0
        first_date = ff["日期"].iloc[-streak].strftime("%Y-%m-%d") if streak else None

        outflow = 0
        for v in reversed(vals):
            if v < 0:
                outflow += 1
            else:
                break

        # 流入停滞天数：距上一次净流入日有几个交易日
        stall = 0
        for v in reversed(vals):
            if v > 0:
                break
            stall += 1
        if streak > 0:
            stall = 0

        last = ff.iloc[-1]
        return {
            "streak_days": streak,
            "cum_inflow": round(cum, 2),
            "first_date": first_date,
            "outflow_days": outflow,
            "stall_days": stall,
            "last_date": ff["日期"].iloc[-1].strftime("%Y-%m-%d"),
            "last_price": float(last["收盘价"]),
            "last_change": float(last["涨跌幅"]),
            "flow_df": ff.tail(60).copy(),
        }
    except Exception:
        return None


def fetch_history(code, days=120):
    """akshare 日 K（前复权）。返回 DataFrame（日期/收盘/涨跌幅/换手率/振幅），失败返回 None。"""
    try:
        import akshare as ak
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 90)).strftime("%Y%m%d")
        h = ak.stock_zh_a_hist_em(symbol=code, period="daily",
                                  start_date=start, end_date=end, adjust="qfq")
        if h is None or h.empty:
            return None
        h = h.sort_values("日期").reset_index(drop=True)
        h["日期"] = pd.to_datetime(h["日期"])
        return h
    except Exception:
        return None


def fetch_hs300_20d():
    """沪深 300 近 20 个交易日涨幅（%）。失败返回 None。"""
    try:
        import akshare as ak
        idx = ak.index_zh_daily_sina(symbol="sh000300")
        closes = idx["close"].astype(float).reset_index(drop=True)
        if len(closes) < 22:
            return None
        return (closes.iloc[-1] / closes.iloc[-21] - 1) * 100
    except Exception:
        return None


# ---------------- 评分（公式透明，见界面「评分说明」） ----------------

def compute_scores(streak_days, cum_inflow, rel_20d, above_ma20,
                   avg_turnover, avg_amplitude):
    """潜伏分看资金持续流入；趋势分看 20 日相对大盘与均线；质量分看换手与振幅是否适中。"""
    latent = _clip(streak_days * 6 + min(max(cum_inflow, 0), 30) * 1.0)
    trend = _clip(50 + (rel_20d or 0) * 4 + (8 if above_ma20 else -8))
    quality = _clip(85 - abs((avg_turnover or 4) - 4) * 6 - (avg_amplitude or 0) * 1.5)
    total = round(0.4 * latent + 0.35 * trend + 0.25 * quality, 1)
    return latent, quality, trend, total


def rel_label(rel_20d):
    if rel_20d is None:
        return "同步大盘"
    if rel_20d > 2:
        return "强于大盘"
    if rel_20d < -2:
        return "弱于大盘"
    return "同步大盘"


def _try_twice(fn, *args, **kwargs):
    """失败时隔 2 秒重试一次（东财接口偶发限流/超时）。"""
    import time
    try:
        out = fn(*args, **kwargs)
        if out is not None:
            return out
    except Exception:
        pass
    time.sleep(2)
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


# ---------------- 总装：监控池实时数据 ----------------

def build_watchlist():
    """返回 (DataFrame, meta)。meta 含各数据源状态与更新时间。"""
    codes = [w["代码"] for w in WATCHLIST]
    meta = {"quote_source": "模拟", "flow_source": "模拟",
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "mock_codes": []}

    quotes = fetch_quotes_hithink(codes)
    if quotes:
        meta["quote_source"] = "同花顺 Financial-API"
    else:
        quotes = fetch_quotes_akshare(codes)
        if quotes:
            meta["quote_source"] = "akshare（东财）"

    hs300_20d = fetch_hs300_20d()

    rows = []
    for w in WATCHLIST:
        code = w["代码"]
        flow = _try_twice(fetch_fund_flow, code)
        hist = _try_twice(fetch_history, code)
        q = (quotes or {}).get(code)

        # 现价：官方/东财行情优先，否则用资金流最新收盘价，最后模拟
        if q and q.get("price"):
            price, change_pct = q["price"], q.get("change_pct", 0.0)
            price_real = True
        elif flow:
            price, change_pct = flow["last_price"], flow["last_change"]
            price_real = True
            if meta["quote_source"] == "模拟":
                meta["quote_source"] = "akshare（资金流收盘价）"
        else:
            price, change_pct = w["模拟现价"], 0.0
            price_real = False

        if flow:
            meta["flow_source"] = "akshare（东财口径）"
            streak, cum, first_date = flow["streak_days"], flow["cum_inflow"], flow["first_date"]
            outflow, stall = flow["outflow_days"], flow["stall_days"]
            flow_ok = True
        else:
            streak, cum = w["模拟持续流入天数"], w["模拟累计净流入亿"]
            first_date, outflow, stall = w["模拟首次流入日期"], 0, 0
            flow_ok = False

        # 20 日相对大盘 / 均线 / 换手 / 振幅
        rel_20d, above_ma20, avg_turn, avg_amp, hi60 = None, False, None, None, None
        if hist is not None and len(hist) >= 25:
            closes = hist["收盘"].astype(float)
            ret20 = (closes.iloc[-1] / closes.iloc[-21] - 1) * 100
            rel_20d = ret20 - hs300_20d if hs300_20d is not None else ret20
            ma20 = closes.tail(20).mean()
            above_ma20 = bool(closes.iloc[-1] > ma20)
            avg_turn = float(hist["换手率"].astype(float).tail(20).mean())
            avg_amp = float(hist["振幅"].astype(float).tail(20).mean())
            hi60 = float(hist["最高"].astype(float).tail(60).max())

        if flow_ok:
            # 资金流是真的；K 线缺失时趋势/质量分用中性默认值补
            latent, quality, trend, total = compute_scores(
                streak, cum, rel_20d if rel_20d is not None else 0.0,
                above_ma20, avg_turn if avg_turn is not None else 4.0,
                avg_amp if avg_amp is not None else 0.0)
            rel_txt = rel_label(rel_20d)
            if hi60:
                sell = f"{hi60 * 0.95:.0f}-{hi60 * 1.05:.0f}"
            else:
                sell = f"{price * 1.15:.0f}-{price * 1.35:.0f}"
            src = "真实"
        else:
            latent, quality, trend = MOCK_SCORES[code]
            total = round(0.4 * latent + 0.35 * trend + 0.25 * quality, 1)
            rel_txt = w["模拟相对大盘"]
            sell = w["模拟建议卖出价"]
            src = "模拟"
            meta["mock_codes"].append(code)

        rows.append({
            "代码": code, "名称": w["名称"], "分类": w["分类"],
            "现价": round(price, 2), "涨跌幅": round(change_pct, 2),
            "潜伏分": latent, "质量分": quality, "趋势分": trend, "综合分": total,
            "持续流入天数": streak, "首次流入日期": first_date or "-",
            "累计净流入亿": cum, "相对大盘": rel_txt,
            "相对大盘数值": round(rel_20d, 2) if rel_20d is not None else None,
            "建议卖出价": sell, "最近流出天数": outflow, "流入停滞天数": stall,
            "数据源": src,
        })

    df = pd.DataFrame(rows)
    meta["mock_codes"] = sorted(set(meta["mock_codes"]))
    return df, meta
