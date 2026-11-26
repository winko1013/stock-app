"""主力潜伏选股 · 真实数据层

数据来源优先级：
  行情（现价 / 涨跌幅）：同花顺 Financial-API（需 HITHINK_FINANCE_API_KEY）
                        → akshare 东财实时行情
                        → 新浪行情（hq.sinajs.cn，不走东财）
                        → 个股资金流里的最新收盘价
                        → 模拟数据
  主力资金流向：akshare（东财口径；同花顺官方文档明确说明资金流接口
                不对外开放，仅在同花顺 AI 客户端内部使用）
                → 仓库快照 fund_flow_snapshot.json（真实数据，截至快照日）
  K 线：akshare（东财，前复权）；取不到时个股详情图用资金流收盘价代替
全部失败时用内置模拟数据兜底，并在界面标注数据来源。
"""

import os
import json
from datetime import datetime, timedelta

import pandas as pd
import requests

THS_BASE = "https://fuyao.aicubes.cn"
SNAPSHOT_URL = f"{THS_BASE}/api/a-share/prices/snapshot"

# 诊断记录：每次取数失败的原因，展示在设置页，方便定位云端取不到数的原因
ERRORS = []


def _record_err(where, exc):
    ERRORS.append(f"{where}: {type(exc).__name__}: {str(exc)[:150]}")


def _clear_errors():
    ERRORS.clear()

# ---------------- 熔断器：东财被限流时 10 分钟内不再重复尝试 ----------------
# Cloud 共享 IP 会被东财反复限流；每次失败都重试只会拖慢页面。
# 一旦某类接口失败就跳闸，10 分钟后自动恢复尝试。
import time as _time

_BLOCKED_UNTIL = {}
_CIRCUIT_COOLDOWN = 600  # 秒


def _akshare_blocked(key):
    return _time.time() < _BLOCKED_UNTIL.get(key, 0)


def _akshare_trip(key):
    _BLOCKED_UNTIL[key] = _time.time() + _CIRCUIT_COOLDOWN


# ---------------- 超时保护：akshare 的请求没有 timeout 参数 ----------------
# 东财接口卡住时整个页面会一直空白（Streamlit 要等脚本跑完先渲染）。
# 把 akshare 调用放进线程，超时就当失败，返回 None 走下一级兜底。
import threading as _threading


def _run_with_timeout(fn, timeout):
    """跑 fn，最多等 timeout 秒；返回 (结果, 是否超时)。
    fn 入面抛出的异常会原样再抛，等调用方按原有逻辑记录。"""
    box = {}

    def _target():
        try:
            box["v"] = fn()
        except Exception as e:
            box["e"] = e

    t = _threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None, True
    if "e" in box:
        raise box["e"]
    return box.get("v"), False

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
    {"代码": "688012", "名称": "中微公司", "分类": "热门赛道+半导体", "模拟现价": 239.90,
     "模拟持续流入天数": 18, "模拟首次流入日期": "2025-10-12", "模拟累计净流入亿": 11.2,
     "模拟相对大盘": "强于大盘", "模拟建议卖出价": "280-310"},
    {"代码": "603986", "名称": "兆易创新", "分类": "热门赛道+半导体", "模拟现价": 198.28,
     "模拟持续流入天数": 12, "模拟首次流入日期": "2025-10-28", "模拟累计净流入亿": 8.6,
     "模拟相对大盘": "强于大盘", "模拟建议卖出价": "230-260"},
    {"代码": "688008", "名称": "澜起科技", "分类": "热门赛道+半导体", "模拟现价": 126.40,
     "模拟持续流入天数": 9, "模拟首次流入日期": "2025-11-02", "模拟累计净流入亿": 6.4,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "145-165"},
    {"代码": "002049", "名称": "紫光国微", "分类": "热门赛道+半导体", "模拟现价": 46.20,
     "模拟持续流入天数": 7, "模拟首次流入日期": "2025-11-06", "模拟累计净流入亿": 3.8,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "54-62"},
    {"代码": "600460", "名称": "士兰微", "分类": "热门赛道+半导体", "模拟现价": 20.68,
     "模拟持续流入天数": 6, "模拟首次流入日期": "2025-11-08", "模拟累计净流入亿": 2.9,
     "模拟相对大盘": "弱于大盘", "模拟建议卖出价": "24-28"},
    {"代码": "002594", "名称": "比亚迪", "分类": "新能源", "模拟现价": 74.45,
     "模拟持续流入天数": 11, "模拟首次流入日期": "2025-10-22", "模拟累计净流入亿": 9.8,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "85-95"},
    {"代码": "300274", "名称": "阳光电源", "分类": "新能源", "模拟现价": 70.49,
     "模拟持续流入天数": 14, "模拟首次流入日期": "2025-10-18", "模拟累计净流入亿": 7.5,
     "模拟相对大盘": "强于大盘", "模拟建议卖出价": "82-95"},
    {"代码": "601012", "名称": "隆基绿能", "分类": "新能源", "模拟现价": 10.92,
     "模拟持续流入天数": 4, "模拟首次流入日期": "2025-11-12", "模拟累计净流入亿": 1.8,
     "模拟相对大盘": "弱于大盘", "模拟建议卖出价": "13-15"},
    {"代码": "600276", "名称": "恒瑞医药", "分类": "医药生物", "模拟现价": 47.70,
     "模拟持续流入天数": 8, "模拟首次流入日期": "2025-11-03", "模拟累计净流入亿": 4.2,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "55-63"},
    {"代码": "300015", "名称": "爱尔眼科", "分类": "医药生物", "模拟现价": 8.78,
     "模拟持续流入天数": 5, "模拟首次流入日期": "2025-11-10", "模拟累计净流入亿": 1.5,
     "模拟相对大盘": "弱于大盘", "模拟建议卖出价": "10-12"},
    {"代码": "000333", "名称": "美的集团", "分类": "大市值蓝筹+消费", "模拟现价": 94.14,
     "模拟持续流入天数": 10, "模拟首次流入日期": "2025-10-26", "模拟累计净流入亿": 5.3,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "108-120"},
    {"代码": "600036", "名称": "招商银行", "分类": "周期金融", "模拟现价": 43.20,
     "模拟持续流入天数": 6, "模拟首次流入日期": "2025-11-07", "模拟累计净流入亿": 3.4,
     "模拟相对大盘": "同步大盘", "模拟建议卖出价": "49-55"},
]

MOCK_SCORES = {
    "300604": (92, 88, 85), "688981": (85, 82, 80), "002371": (88, 90, 86),
    "300750": (78, 85, 75), "600519": (65, 95, 70), "000858": (70, 92, 72),
    "300014": (82, 80, 78), "601318": (60, 88, 65), "002415": (75, 83, 70),
    "688012": (82, 85, 80), "603986": (78, 82, 76), "688008": (75, 80, 74),
    "002049": (72, 78, 70), "600460": (68, 75, 66), "002594": (76, 84, 72),
    "300274": (80, 83, 78), "601012": (65, 72, 62), "600276": (70, 78, 68),
    "300015": (62, 70, 60), "000333": (68, 88, 70), "600036": (60, 85, 65),
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
    if _akshare_blocked("spot"):
        return None

    def _fetch():
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

    try:
        out, timed_out = _run_with_timeout(_fetch, 20)
        if timed_out:
            raise TimeoutError("akshare 行情超时 20 秒")
        return out
    except Exception as e:
        _akshare_trip("spot")
        _record_err("akshare 行情", e)
        return None


def fetch_quotes_sina(codes):
    """新浪行情（hq.sinajs.cn，不走东财，是 Cloud 上东财被限时的备用行情源）。
    成功返回 {code: dict}，失败返回 None。"""
    try:
        prefix = {"6": "sh", "0": "sz", "3": "sz", "4": "bj", "8": "bj"}
        symbols = ",".join(prefix.get(c[0], "sz") + c for c in codes)
        resp = requests.get(
            f"http://hq.sinajs.cn/list={symbols}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
        if resp.status_code != 200 or not resp.text.strip():
            return None
        out = {}
        for line in resp.text.strip().split("\n"):
            if '"' not in line:
                continue
            sym, payload = line.split("=", 1)
            code = sym.strip()[-6:]
            parts = payload.strip().strip('";').split(",")
            if len(parts) < 10:
                continue
            try:
                price = float(parts[3])
                prev = float(parts[2])
            except ValueError:
                continue
            if price <= 0 or prev <= 0:
                continue
            out[code] = {
                "name": parts[0],
                "price": price,
                "change_pct": round((price / prev - 1) * 100, 2),
                "volume": float(parts[8]),
                "turnover": float(parts[9]),
                "prev_close": prev,
            }
        return out or None
    except Exception as e:
        _record_err("新浪行情", e)
        return None


def _flow_dict_from_frame(ff, snapshot_date=None):
    """由资金流 DataFrame（日期/收盘价/涨跌幅/主力净流入-净额）算出 streak 等指标。"""
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
        "snapshot": snapshot_date is not None,
        "snapshot_date": snapshot_date,
    }


def load_flow_snapshot():
    """读仓库里随代码一起部署的资金流快照（fund_flow_snapshot.json）。
    返回 {code: DataFrame}，文件缺失或损坏返回 {}。"""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "fund_flow_snapshot.json"), encoding="utf-8") as f:
            snap = json.load(f)
        out = {}
        for code, rows in snap.get("stocks", {}).items():
            df = pd.DataFrame(rows)
            df = df.rename(columns={"date": "日期", "close": "收盘价",
                                    "change_pct": "涨跌幅",
                                    "main_net_inflow": "主力净流入-净额"})
            out[code] = df
        out["_as_of"] = snap.get("as_of")
        return out
    except Exception as e:
        _record_err("快照读取", e)
        return {}


def fetch_fund_flow(code):
    """akshare 个股资金流（近约 100 个交易日，东财口径）。
    快照优先：仓库快照够新（最新数据 3 天内）就直接用，不碰东财——
    Cloud 上东财长期被限流，每次尝试都要等很久；日线资金流收盘后才更新，
    快照已是最新的收盘数据。快照太旧或没有时才试 akshare（带熔断），
    再不行才用旧快照；都没有才返回 None。
    返回 dict：streak_days / cum_inflow（亿）/ first_date / outflow_days /
    stall_days / last_date / last_price / last_change / flow_df（近 60 日）
    / snapshot / snapshot_date。"""
    snap = load_flow_snapshot()
    df = snap.get(code)
    if df is not None and not df.empty:
        last_date = pd.to_datetime(df["日期"]).max()
        if (datetime.now() - last_date).days <= 3:
            return _flow_dict_from_frame(df, snapshot_date=snap.get("_as_of"))
    if not _akshare_blocked("flow"):
        def _fetch():
            import akshare as ak
            return ak.stock_fund_flow_individual_hist_em(symbol=code, market=market_of(code))

        try:
            ff, timed_out = _run_with_timeout(_fetch, 25)
            if timed_out:
                raise TimeoutError("akshare 资金流超时 25 秒")
            if ff is not None and not ff.empty:
                return _flow_dict_from_frame(ff)
            _record_err(f"资金流 {code}", Exception("akshare 返回空数据"))
        except Exception as e:
            _akshare_trip("flow")
            _record_err(f"资金流 {code}", e)
    if df is not None and not df.empty:
        return _flow_dict_from_frame(df, snapshot_date=snap.get("_as_of"))
    return None


def fetch_history(code, days=120):
    """akshare 日 K（前复权）。返回 DataFrame（日期/收盘/涨跌幅/换手率/振幅），失败返回 None。"""
    if _akshare_blocked("hist"):
        return None
    def _fetch():
        import akshare as ak
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 90)).strftime("%Y%m%d")
        return ak.stock_zh_a_hist_em(symbol=code, period="daily",
                                     start_date=start, end_date=end, adjust="qfq")

    try:
        h, timed_out = _run_with_timeout(_fetch, 25)
        if timed_out:
            raise TimeoutError("akshare K线超时 25 秒")
        if h is None or h.empty:
            return None
        h = h.sort_values("日期").reset_index(drop=True)
        h["日期"] = pd.to_datetime(h["日期"])
        return h
    except Exception as e:
        _akshare_trip("hist")
        _record_err(f"K线 {code}", e)
        return None


def fetch_hs300_20d():
    """沪深 300 近 20 个交易日涨幅（%）。先走新浪 K 线直连（快，Cloud 上可用），
    失败再走 akshare；都失败返回 None。"""
    try:
        resp = requests.get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData",
            params={"symbol": "sh000300", "scale": "240", "ma": "no", "datalen": "30"},
            timeout=10,
        )
        data = resp.json()
        closes = [float(d["close"]) for d in data]
        if len(closes) >= 21:
            return (closes[-1] / closes[-21] - 1) * 100
    except Exception as e:
        _record_err("沪深300（新浪）", e)
    def _fetch():
        import akshare as ak
        return ak.index_zh_daily_sina(symbol="sh000300")

    try:
        idx, timed_out = _run_with_timeout(_fetch, 15)
        if timed_out:
            raise TimeoutError("akshare 沪深300超时 15 秒")
        closes = idx["close"].astype(float).reset_index(drop=True)
        if len(closes) < 22:
            return None
        return (closes.iloc[-1] / closes.iloc[-21] - 1) * 100
    except Exception as e:
        _record_err("沪深300", e)
        return None


def get_stock_monitor(code):
    """为任意一只 A 股取监测数据（持股监测用，不限于 9 只监控池）。
    返回 dict：name / price / change_pct / streak_days / cum_inflow /
    first_date / outflow_days / stall_days / sell / flow_ok；
    行情和资金流都取不到时返回 None。"""
    flow = fetch_fund_flow(code)
    # 资金流走快照时 K 线也不用试（Cloud 上必失败）；卖出价改用现价推算
    hist = None if (flow and flow.get("snapshot")) else fetch_history(code)
    quotes = fetch_quotes_sina([code])
    q = (quotes or {}).get(code)
    name = (q or {}).get("name")
    if q and q.get("price"):
        price, change_pct = q["price"], q.get("change_pct", 0.0)
    elif flow:
        price, change_pct = flow["last_price"], flow["last_change"]
    else:
        return None
    if flow:
        streak, cum = flow["streak_days"], flow["cum_inflow"]
        first_date, outflow, stall = flow["first_date"], flow["outflow_days"], flow["stall_days"]
        flow_ok = True
    else:
        streak, cum, first_date, outflow, stall = 0, 0.0, None, 0, 0
        flow_ok = False
    hi60 = None
    if hist is not None and len(hist) >= 25:
        hi60 = float(hist["最高"].astype(float).tail(60).max())
    sell = (f"{hi60 * 0.95:.0f}-{hi60 * 1.05:.0f}" if hi60
            else f"{price * 1.15:.0f}-{price * 1.35:.0f}")
    return {
        "name": name, "price": round(price, 2), "change_pct": round(change_pct, 2),
        "streak_days": streak, "cum_inflow": cum, "first_date": first_date,
        "outflow_days": outflow, "stall_days": stall, "sell": sell,
        "flow_ok": flow_ok,
    }


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


# ---------------- 总装：监控池实时数据 ----------------

def build_watchlist():
    """返回 (DataFrame, meta)。meta 含各数据源状态、更新时间与诊断错误。"""
    _clear_errors()
    codes = [w["代码"] for w in WATCHLIST]
    meta = {"quote_source": "模拟", "flow_source": "模拟",
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mock_codes": [], "errors": []}

    # 行情：同花顺官方（有 Key 时）→ 新浪（快，Cloud 可用）→ akshare 东财
    quotes = fetch_quotes_hithink(codes)
    if quotes:
        meta["quote_source"] = "同花顺 Financial-API"
    else:
        quotes = fetch_quotes_sina(codes)
        if quotes:
            meta["quote_source"] = "新浪行情"
        else:
            quotes = fetch_quotes_akshare(codes)
            if quotes:
                meta["quote_source"] = "akshare（东财）"

    hs300_20d = fetch_hs300_20d()

    rows = []
    for w in WATCHLIST:
        code = w["代码"]
        flow = fetch_fund_flow(code)
        # 资金流走快照时 K 线也不用试（Cloud 上必失败）
        hist = None if (flow and flow.get("snapshot")) else fetch_history(code)
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
            if flow.get("snapshot"):
                meta["flow_source"] = f"快照 {flow.get('snapshot_date') or ''}（真实数据，截至快照日）"
            else:
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
        elif flow is not None:
            # K 线取不到时用资金流里的 60 日收盘价算 20 日相对大盘与均线
            closes = flow["flow_df"]["收盘价"].astype(float)
            if len(closes) >= 21:
                ret20 = (closes.iloc[-1] / closes.iloc[-21] - 1) * 100
                rel_20d = ret20 - hs300_20d if hs300_20d is not None else ret20
                above_ma20 = bool(closes.iloc[-1] > closes.tail(20).mean())

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
    meta["errors"] = list(dict.fromkeys(ERRORS))
    return df, meta


def fetch_market_index():
    """新浪大盘指数实时行情（上证/深证成指/创业板/沪深300）。
    s_ 指数串格式：名称,最新价,涨跌额,涨跌幅%,成交量,成交额。
    失败返回 []。"""
    wanted = [("s_sh000001", "上证指数"), ("s_sz399001", "深证成指"),
              ("s_sz399006", "创业板指"), ("s_sh000300", "沪深300")]
    try:
        resp = requests.get(
            "http://hq.sinajs.cn/list=" + ",".join(s for s, _ in wanted),
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
        if resp.status_code != 200:
            return []
        resp.encoding = "gbk"
        text = resp.text
        if not text.strip():
            return []
        names = dict(wanted)
        out = []
        for line in text.strip().split("\n"):
            if '"' not in line or "=" not in line:
                continue
            sym = line.split("=", 1)[0].strip().replace("var hq_str_", "")
            if sym not in names:
                continue
            parts = line.split("=", 1)[1].strip().strip('";').split(",")
            if len(parts) < 4:
                continue
            try:
                out.append({"name": names[sym], "price": float(parts[1]),
                            "change_pct": float(parts[3])})
            except ValueError:
                continue
        return out
    except Exception as e:
        _record_err("大盘指数（新浪）", e)
        return []


def run_backtest(code, streak_n=3, forward_days=10):
    """简单回测：快照资金流里，连续净流入首次达到 streak_n 天的信号日，
    在信号日收盘买入、持有 forward_days 个交易日的涨幅统计。
    用快照约 121 个交易日的真实收盘价与资金流；数据不足返回 None，
    无信号返回 n=0 的 dict。"""
    snap = load_flow_snapshot()
    df = snap.get(code)
    if df is None or df.empty or len(df) < 40:
        return None
    df = df.sort_values("日期").reset_index(drop=True)
    net = df["主力净流入-净额"].astype(float).to_numpy()
    close = df["收盘价"].astype(float).to_numpy()
    dates = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d").tolist()
    streak = 0
    signals = []
    for i, v in enumerate(net):
        streak = streak + 1 if v > 0 else 0
        if streak == streak_n and i + forward_days < len(close):
            ret = (close[i + forward_days] / close[i] - 1) * 100
            signals.append({
                "信号日期": dates[i],
                "信号日收盘": round(float(close[i]), 2),
                f"{forward_days}日后收盘": round(float(close[i + forward_days]), 2),
                f"{forward_days}日涨幅%": round(float(ret), 2),
            })
    if not signals:
        return {"code": code, "n": 0, "signals": [],
                "as_of": snap.get("_as_of"), "rows": len(df)}
    rets = [s[f"{forward_days}日涨幅%"] for s in signals]
    return {"code": code, "n": len(signals),
            "win_rate": round(sum(1 for r in rets if r > 0) / len(rets) * 100, 1),
            "avg_ret": round(sum(rets) / len(rets), 2),
            "signals": signals, "as_of": snap.get("_as_of"), "rows": len(df)}
