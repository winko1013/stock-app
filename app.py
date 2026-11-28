import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
import os

from data_provider import build_watchlist, fetch_fund_flow, fetch_history, get_stock_monitor, fetch_market_index, run_backtest, load_pool_additions, save_pool_additions, fetch_today_fund_rank

# ==================== 持仓持久化（holdings.json，重启不丢失） ====================
# 持仓存在 app.py 同目录的 holdings.json（只存本机，不上传 GitHub）。
# 启动时优先读文件，无文件才用默认示例；增删持仓即时写文件。
HOLDINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holdings.json")


def _load_holdings():
    """读 holdings.json；无文件或损坏返回 None（用默认持仓）。"""
    try:
        with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return None


def _save_holdings(holdings):
    """持仓变动即写入 holdings.json。"""
    try:
        with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(holdings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

st.set_page_config(page_title="主力潜伏选股", page_icon="📈", layout="wide")

# ==================== 真实数据（带缓存，失败自动用模拟兜底） ====================
@st.cache_data(ttl=300)
def load_watchlist():
    return build_watchlist()


@st.cache_data(ttl=300)
def _monitor(code):
    """任意一只 A 股的监测数据（持股监测用，不限于监控池）。"""
    return get_stock_monitor(code)


@st.cache_data(ttl=300)
def _market_index():
    return fetch_market_index()


@st.cache_data(ttl=300)
def _backtest(code, streak_n, forward_days):
    return run_backtest(code, streak_n, forward_days)


@st.cache_data(ttl=600)
def _today_rank():
    return fetch_today_fund_rank()


def _beep_html():
    """生成一段 0.5 秒 880Hz 提示音（WAV，base64 内嵌，不依赖外链）。"""
    try:
        import base64
        import io
        import math
        import struct
        import wave
        rate = 8000
        n = int(rate * 0.5)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            frames = b"".join(
                struct.pack("<h", int(12000 * math.sin(2 * math.pi * 880 * i / rate)))
                for i in range(n))
            w.writeframes(frames)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return ('<audio autoplay><source src="data:audio/wav;base64,'
                + b64 + '" type="audio/wav"></audio>')
    except Exception:
        return ""

with st.spinner("正在加载数据，请稍候…"):
    df, meta = load_watchlist()

# 卖出规则阈值（设置页可调）
if "outflow_days_alert" not in st.session_state:
    st.session_state.outflow_days_alert = 3
if "stall_days_alert" not in st.session_state:
    st.session_state.stall_days_alert = 5

# ==================== 侧边栏导航 ====================
st.sidebar.title("📈 主力潜伏选股")
page = st.sidebar.radio("功能导航", ["首页", "今日主力榜", "监控池", "分类选股", "持股监测", "个股详情", "简单回测", "设置"])

st.sidebar.markdown("---")
st.sidebar.caption(
    f"行情：{meta['quote_source']}  \n"
    f"资金流：{meta['flow_source']}（东财口径）  \n"
    f"更新：{meta['updated']}"
)
if meta["mock_codes"]:
    st.sidebar.warning(f"⚠️ 以下股票暂用模拟数据：{','.join(meta['mock_codes'])}")
if st.sidebar.button("🔄 刷新数据"):
    st.cache_data.clear()
    st.rerun()

def _fmt_score(x):
    """中线分 / 辅助参考分显示：数字保留一位小数，缺失显示 —。"""
    try:
        if x is None or pd.isna(x):
            return "—"
        return f"{float(x):.1f}"
    except Exception:
        return "—"


# ==================== 首页 ====================
if page == "首页":
    st.title("主力潜伏选股系统")
    st.markdown("### 大盘环境：上升趋势 ✓")

    idx = _market_index()
    if idx:
        icols = st.columns(len(idx))
        for c, r in zip(icols, idx):
            c.metric(r["name"], f"{r['price']:.2f}", f"{r['change_pct']:+.2f}%")
    else:
        st.caption("大盘指数暂取不到")

    inflow_n = int((df["持续流入天数"] > 0).sum())
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("监控股票数", str(len(df)))
    col2.metric("持续流入中", str(inflow_n))
    col3.metric("今日更新", meta["updated"][11:])
    col4.metric("行情来源", meta["quote_source"].replace("（东财）", ""))

    st.subheader("今日重点关注")
    top = df.nlargest(3, "短线分")[["代码", "名称", "短线分", "持续流入天数", "相对大盘", "建议卖出价"]]
    st.dataframe(top, width="stretch")

    st.subheader("监控池一览")
    _home = df[["代码", "名称", "现价", "涨跌幅", "短线分", "中线分", "辅助参考分",
                "打标", "持续流入天数", "累计净流入亿", "相对大盘", "数据源"]].copy()
    _home["中线分"] = _home["中线分"].map(_fmt_score)
    _home["辅助参考分"] = _home["辅助参考分"].map(_fmt_score)
    st.dataframe(_home, width="stretch")

    st.subheader("📖 双公式")
    _f1, _f2 = st.columns(2)
    with _f1:
        st.markdown("**短线分**")
        st.write("潜伏分 = 持续流入天数×6 + min(累计净流入亿, 30)×1，上限 100。")
        st.write("趋势分 = 50 + 20日相对沪深300涨幅×4，收盘站上20日均线 +8，否则 -8。")
        st.write("质量分 = 85 − |近20日平均换手率 − 4%|×6 − 近20日平均振幅（%）×1.5。")
        st.write("短线分 = 潜伏分×0.4 + 趋势分×0.35 + 质量分×0.25。")
    with _f2:
        st.markdown("**中线分**")
        st.write("潜伏分 = 近20日净流入天数×3.5 + 净流入占比(%)×12。")
        st.write("趋势分 = 50 + 20日相对沪深300涨幅×2.5 − 乖离惩罚（BIAS20 超过 12% 的部分每 1% 扣 2 分）。")
        st.write("质量分 = 90 − 换手偏离扣分 − 近20日平均振幅（%）×2（换手率 2%~6% 扣 0，低于 2% 每低 1% 扣 6 分，高于 6% 每高 1% 扣 4 分）。")
        st.write("中线分硬过滤：上市不足 60 个交易日、ST 股、近 20 日有效交易日不足 18 天、"
                 "近 20 日日均成交额低于 1.5 亿、近 20 日出现过单日跌幅大于 9%，或数据不全时显示「—」。")
    st.write("辅助参考分 = 0.6×短线分 + 0.4×中线分。打标：短线分≥55 且 中线分≥55 → ★双共振。中线分显示「—」时，辅助参考分同样显示「—」，打标置空。")
    st.write("中线分仅供参考，未验证有效；排序与筛选以短线分为准。")
    st.write("建议卖出价 = 近60日最高价附近 ±5%，仅供参考；仅作前高压力参考，不代表必然到价或止盈线。")
    st.write("资金流为东财口径主力净流入；同花顺官方 API 不对外开放资金流接口。")

    st.info("💡 提示：点击左侧「持股监测」查看是否有资金停止流入的持仓股票")

# ==================== 今日主力榜 ====================
elif page == "今日主力榜":
    st.title("今日主力资金净流入排行")
    st.caption("数据：东方财富（akshare）。东财接口成日限流，取唔到时会显示提示，唔系 App 坏。")

    rank_df = _today_rank()
    if rank_df is None or rank_df.empty:
        st.warning("暂时取不到今日排行（东财接口限流），稍后再试。手动添加监控池唔受影响。")
    else:
        st.dataframe(rank_df, width="stretch")
        codes = rank_df["代码"].tolist()
        selected = st.multiselect(
            "勾选加入监控池", codes,
            format_func=lambda x: f"{x} {rank_df[rank_df['代码'] == x]['名称'].values[0]}")
        if st.button("加入监控池", type="primary") and selected:
            adds = load_pool_additions()
            have = {a["代码"] for a in adds} | set(df["代码"].tolist())
            n = 0
            for code in selected:
                if code not in have:
                    name = rank_df[rank_df["代码"] == code]["名称"].values[0]
                    adds.append({"代码": code, "名称": name, "分类": "手动添加"})
                    have.add(code)
                    n += 1
            save_pool_additions(adds)
            st.cache_data.clear()
            st.success(f"已加入 {n} 只（已存本机，重启唔会冇晒）")
            st.rerun()

# ==================== 监控池（含手动添加） ====================
elif page == "监控池":
    st.title(f"监控池（共 {len(df)} 只）")
    st.caption("手动加嘅股存喺本机文件，重启唔会冇晒，唔推 GitHub；云端加嘅重启会冇晒，同持仓一样。")

    adds = load_pool_additions()
    with st.expander("➕ 手动添加股票到监控池", expanded=True):
        c1, c2, c3 = st.columns([2, 2, 2])
        new_code = c1.text_input("股票代码（例：688256）", key="pool_code")
        new_name = c2.text_input("股票名称（可空，会自动查）", key="pool_name")
        new_cat = c3.selectbox("分类", ["手动添加", "热门赛道", "半导体制造", "大市值蓝筹",
                                        "新能源", "周期金融", "消费必需", "医药生物",
                                        "稳健分红", "小市值成长"], key="pool_cat")
        if st.button("添加", type="primary"):
            code = (new_code or "").strip()
            if not (code.isdigit() and len(code) == 6):
                st.error("请输入 6 位股票代码，例如 688256")
            elif code in df["代码"].values:
                st.warning(f"{code} 已在监控池中")
            else:
                name = (new_name or "").strip()
                if not name:
                    m = _monitor(code)
                    name = m.get("name") if m else None
                if not name:
                    st.error("查不到该股行情，请检查代码")
                else:
                    adds.append({"代码": code, "名称": name, "分类": new_cat})
                    save_pool_additions(adds)
                    st.cache_data.clear()
                    st.success(f"已添加 {code} {name}（已存本机）")
                    st.rerun()

    if adds:
        st.subheader("手动添加嘅股票")
        for a in adds:
            col_a, col_b = st.columns([4, 1])
            col_a.write(f"**{a['代码']} {a['名称']}**（{a.get('分类', '手动添加')}）")
            if col_b.button("删除", key=f"del_pool_{a['代码']}"):
                save_pool_additions([x for x in adds if x["代码"] != a["代码"]])
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.subheader("监控池一览")
    _pool = df[["代码", "名称", "现价", "涨跌幅", "短线分", "中线分", "辅助参考分",
                "打标", "持续流入天数", "累计净流入亿", "相对大盘", "数据源"]].copy()
    _pool["中线分"] = _pool["中线分"].map(_fmt_score)
    _pool["辅助参考分"] = _pool["辅助参考分"].map(_fmt_score)
    st.dataframe(_pool, width="stretch")

# ==================== 分类选股 ====================
elif page == "分类选股":
    st.title("分类选股")

    categories = ["热门赛道", "稳健分红", "大市值蓝筹", "小市值成长", "半导体制造",
                  "消费必需", "新能源", "医药生物", "周期金融"]

    # 分类关键词映射：多选项 -> 数据「分类」栏中的关键词（子串匹配）
    CATEGORY_KEYWORDS = {
        "热门赛道": "热门赛道",
        "半导体制造": "半导体",
        "大市值蓝筹": "大市值蓝筹",
        "新能源": "新能源",
        "周期金融": "周期金融",
        "消费必需": "消费",
        "稳健分红": "分红",
        "小市值成长": "小市值",
        "医药生物": "医药",
    }

    selected = st.multiselect("选择分类（可多选）", categories, default=["热门赛道", "半导体制造"])

    min_days = st.slider("最低持续流入天数（0 表示不限）", 0, 60, 1)
    min_score = st.slider("最低短线分", 50, 95, 55)

    if st.button("开始选股", type="primary"):
        result = df[
            (df["持续流入天数"] >= min_days) &
            (df["短线分"] >= min_score)
        ]
        if selected and not result.empty:
            keywords = [CATEGORY_KEYWORDS[c] for c in selected if c in CATEGORY_KEYWORDS]
            mask = result["分类"].apply(
                lambda x: x == "手动添加" or any(k in str(x) for k in keywords))
            result = result[mask]
        result = result.sort_values("短线分", ascending=False)

        if result.empty:
            st.warning("没有符合条件的股票，试下放宽分类或拉低两个滑杆")
        else:
            st.success(f"共找到 {len(result)} 只符合条件的股票")
            _res = result[["代码", "名称", "短线分", "中线分", "辅助参考分", "打标",
                           "持续流入天数", "相对大盘", "建议卖出价", "分类"]].copy()
            _res["中线分"] = _res["中线分"].map(_fmt_score)
            _res["辅助参考分"] = _res["辅助参考分"].map(_fmt_score)
            st.dataframe(_res, width="stretch")

# ==================== 持股监测（核心功能） ====================
elif page == "持股监测":
    st.title("持股监测")
    st.markdown(f"**规则**：主力资金连续≥{st.session_state.outflow_days_alert}天净流出 "
                f"或 流入停滞≥{st.session_state.stall_days_alert}天 → 自动提示卖出")

    # 持仓：优先读 holdings.json（重启不丢失）；无文件用默认示例
    if "holdings" not in st.session_state:
        loaded = _load_holdings()
        st.session_state.holdings = loaded if loaded is not None else [
            {"代码": "300604", "名称": "长川科技", "成本价": 48.50, "数量": 1000},
            {"代码": "688981", "名称": "中芯国际", "成本价": 72.0, "数量": 500},
        ]

    has_alert = False
    alert_codes = []
    for i, h in enumerate(st.session_state.holdings):
        with st.container():
            col1, col2, col3 = st.columns([2, 2, 3])
            row = df[df["代码"] == h["代码"]]
            if not row.empty:
                r = row.iloc[0]
                current_price = float(r["现价"])
                streak = int(r["持续流入天数"])
                outflow = int(r["最近流出天数"])
                stall = int(r["流入停滞天数"])
                sell_ref = r["建议卖出价"]
                flow_ok = True
            else:
                # 监控池外的股票：即时取监测数据（新浪行情 + 资金流）
                m = _monitor(h["代码"])
                if m is None:
                    col1.write(f"**{h['代码']} {h['名称']}**")
                    col1.write("暂取不到该股行情，请稍后刷新重试")
                    st.divider()
                    continue
                current_price = m["price"]
                streak = m["streak_days"]
                outflow = m["outflow_days"]
                stall = m["stall_days"]
                sell_ref = m["sell"]
                flow_ok = m["flow_ok"]
            profit = (current_price - h["成本价"]) / h["成本价"] * 100

            col1.write(f"**{h['代码']} {h['名称']}**")
            col1.write(f"成本：{h['成本价']} | 现价：{current_price}")
            col1.write(f"盈亏：{profit:.1f}%")

            if flow_ok:
                col2.write(f"持续流入：{streak}天")
                col2.write(f"最近流出：{outflow}天 | 停滞：{stall}天")
            else:
                col2.write(f"持续流入：{streak}天")
                col2.write("资金流暂取不到，只看价格")

            # 卖出判断
            if flow_ok and outflow >= st.session_state.outflow_days_alert:
                has_alert = True
                alert_codes.append(h["代码"])
                col3.error("⚠️ 重要卖出提示")
                col3.write("主力资金已连续流出，建议减仓/清仓")
                col3.write(f"参考卖出价：{sell_ref}")
            elif flow_ok and stall >= st.session_state.stall_days_alert:
                col3.warning("⚠️ 流入停滞提示")
                col3.write(f"主力资金已停滞流入 {stall} 天，留意是否转弱")
                col3.write(f"参考卖出价：{sell_ref}")
            elif flow_ok:
                col3.success("✓ 资金仍在流入，继续持有")
            else:
                col3.info("资金流暂取不到，暂无卖出提示")

            if st.button(f"删除 {h['代码']} {h['名称']}", key=f"del_{h['代码']}"):
                st.session_state.holdings = [
                    x for x in st.session_state.holdings if x["代码"] != h["代码"]]
                _save_holdings(st.session_state.holdings)
                st.rerun()

            st.divider()

    if has_alert:
        sig = (meta["updated"][:10], tuple(sorted(alert_codes)))
        if st.session_state.get("_beep_sig") != sig:
            st.session_state["_beep_sig"] = sig
            st.markdown(_beep_html(), unsafe_allow_html=True)
        st.caption("🔔 已触发卖出提示音（浏览器可能拦截自动播放，如无声请点一下页面再刷新；同一批提示每日只响一次）")

    # 添加持仓（任意 A 股，不限于监控池）
    with st.expander("➕ 添加持仓"):
        code = st.text_input("股票代码", placeholder="例如 301568")
        cost = st.number_input("成本价", min_value=0.0, value=50.0)
        qty = st.number_input("数量", min_value=100, value=1000, step=100)
        if st.button("确认添加"):
            code = code.strip()
            if not (code.isdigit() and len(code) == 6):
                st.error("请输入 6 位股票代码，例如 301568")
            elif any(x["代码"] == code for x in st.session_state.holdings):
                st.warning("该股票已在持仓列表中")
            else:
                name = None
                if code in df["代码"].values:
                    name = df[df["代码"] == code]["名称"].values[0]
                else:
                    m = _monitor(code)
                    name = m.get("name") if m else None
                st.session_state.holdings.append({
                    "代码": code, "名称": name or "未知",
                    "成本价": cost, "数量": qty,
                })
                _save_holdings(st.session_state.holdings)
                st.rerun()

# ==================== 个股详情 ====================
elif page == "个股详情":
    st.title("个股详情")
    code = st.selectbox("选择股票", df["代码"].tolist(),
                        format_func=lambda x: f"{x} {df[df['代码'] == x]['名称'].values[0]}")

    stock = df[df["代码"] == code].iloc[0]

    col1, col2, col3 = st.columns(3)
    col1.metric("现价", stock["现价"], f"{stock['涨跌幅']}%")
    col2.metric("短线分", stock["短线分"])
    col3.metric("持续流入天数", stock["持续流入天数"])

    _tag = f"  {stock['打标']}" if stock["打标"] else ""
    st.write(f"中线分（仅供参考）：{_fmt_score(stock['中线分'])}{_tag}"
             f"  ｜  辅助参考分：{_fmt_score(stock['辅助参考分'])}")

    st.subheader("主力资金潜伏监测")
    st.write(f"首次明显流入时间：{stock['首次流入日期']}")
    st.write(f"已持续净流入：{stock['持续流入天数']} 天")
    st.write(f"累计净流入：{stock['累计净流入亿']} 亿元")
    rel_num = stock["相对大盘数值"]
    rel_suffix = (f"（20日相对沪深300 {rel_num:+.2f}%）"
                  if pd.notna(rel_num) else "")
    st.write(f"相对大盘：{stock['相对大盘']}{rel_suffix}")

    st.subheader("卖出建议")
    st.warning(f"建议卖出价格区间：{stock['建议卖出价']} 元")
    st.write("触发条件：主力连续3天净流出 / 跌破关键支撑 / 相对大盘转弱")

    # 真实图表：股价 vs 主力资金累积（东财口径，失败则用模拟）
    flow = fetch_fund_flow(code)
    hist = fetch_history(code)
    chart_real = False
    chart_note = ""
    if flow is not None and hist is not None and len(hist) >= 30:
        fdf = flow["flow_df"].copy()
        fdf["cum_flow"] = fdf["主力净流入-净额"].cumsum() / 1e8  # 亿元
        merged = pd.merge(hist[["日期", "收盘"]], fdf[["日期", "cum_flow"]],
                          on="日期", how="inner")
        if len(merged) >= 30:
            chart_real = True
            dates, price, fund = merged["日期"], merged["收盘"], merged["cum_flow"]

    if not chart_real and flow is not None and len(flow["flow_df"]) >= 30:
        # K 线取不到时，用资金流里的收盘价画股价线（仍是真实收盘价）
        fdf = flow["flow_df"].copy()
        fdf["cum_flow"] = fdf["主力净流入-净额"].cumsum() / 1e8
        chart_real = True
        chart_note = "（快照数据）" if flow.get("snapshot") else "（资金流收盘价）"
        dates, price, fund = fdf["日期"], fdf["收盘价"], fdf["cum_flow"]

    if not chart_real:
        dates = pd.date_range(end=datetime.now(), periods=60)
        price = np.cumsum(np.random.randn(60)) + stock["现价"] - 30
        fund = np.cumsum(np.random.randn(60) * 0.5)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=price, name="股价", line=dict(color="orange")))
    fig.add_trace(go.Scatter(x=dates, y=fund, name="累积资金（亿）", yaxis="y2",
                             line=dict(color="blue")))
    fig.update_layout(
        title="股价 vs 主力资金累积" + ("（真实数据）" if chart_real else "（模拟）") + chart_note,
        yaxis2=dict(overlaying="y", side="right"))
    st.plotly_chart(fig, width="stretch")
    if not chart_real:
        st.caption("⚠️ 资金流或 K 线暂取不到，已用模拟图表代替。")

# ==================== 简单回测 ====================
elif page == "简单回测":
    st.title("简单回测（潜伏信号后表现）")
    st.markdown("用快照约 121 个交易日的真实资金流与收盘价：当连续净流入首次达到 N 天，"
                "在信号日收盘买入、持有 M 个交易日。只作历史统计，唔系买卖建议。")
    name_map = {r["代码"]: r["名称"] for _, r in df.iterrows()}
    for c, n in [("301568", "思泰克"), ("688362", "甬矽电子"),
                 ("688400", "凌云光"), ("603203", "快克智能")]:
        name_map.setdefault(c, n)
    code = st.selectbox("选择股票", sorted(name_map),
                        format_func=lambda x: f"{x} {name_map[x]}")
    streak_n = st.slider("连续流入达到几天算信号", 2, 5, 3)
    fwd = st.slider("持有多少个交易日", 5, 20, 10)
    if st.button("开始回测", type="primary"):
        res = _backtest(code, streak_n, fwd)
        if res is None:
            st.warning("该股快照数据不足，无法回测")
        elif res["n"] == 0:
            st.warning(f"约 {res['rows']} 个交易日里无连续流入达到 {streak_n} 天的信号")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("信号次数", str(res["n"]))
            c2.metric("胜率", f"{res['win_rate']}%")
            c3.metric("平均涨幅", f"{res['avg_ret']}%")
            st.dataframe(pd.DataFrame(res["signals"]), width="stretch")
            st.caption(f"数据截至快照日 {res['as_of']}；信号日收盘买入，持有 {fwd} 个交易日。")

# ==================== 设置 ====================
elif page == "设置":
    st.title("设置")
    st.session_state.outflow_days_alert = st.slider(
        "连续净流出几天触发卖出提示", 2, 7, st.session_state.outflow_days_alert)
    st.session_state.stall_days_alert = st.slider(
        "流入停滞几天触发提示", 3, 10, st.session_state.stall_days_alert)
    st.checkbox("卖出提示时推送通知", value=True)
    st.checkbox("必须结合大盘转弱才提示", value=False)

    st.markdown("---")
    st.subheader("数据源")
    st.write(f"行情：{meta['quote_source']}")
    st.write(f"资金流：{meta['flow_source']}（东财口径）")
    st.write(f"更新时间：{meta['updated']}")
    with st.expander("🔍 取数诊断（云端取不到数时看这里）"):
        errs = meta.get("errors") or []
        if errs:
            for e in errs:
                st.write("- " + e)
        else:
            st.write("暂无错误：本次全部取数成功。")
    if st.button("🔄 立即刷新数据"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.subheader("接同花顺官方行情")
    st.write("1. 用同花顺账号登录 https://fuyao.aicubes.cn/admin ，创建一个 API Key（免费，每日 1000 次调用）。")
    st.write("2. 在 Streamlit Cloud 打开本应用 → 右上角 ⋮ → Settings → Secrets，加入一行：")
    st.code('HITHINK_FINANCE_API_KEY = "你的 Key"')
    st.write("3. 保存后应用自动重启，行情即改由同花顺官方接口提供。")
    st.write("注意：资金流接口官方不对外开放，资金流继续用 akshare（东财口径）。")

    st.markdown("---")
    st.subheader("本机数据备份（持仓 + 手动监控池）")
    st.write("导出本机持仓与手动添加的监控池股票为 JSON 文件；导入会覆盖当前文件，重启后仍然保留。")
    _exp_holdings = _load_holdings() or []
    _exp_pool = load_pool_additions()
    _export_data = {"holdings": _exp_holdings, "pool_additions": _exp_pool}
    st.download_button(
        label="下载备份文件",
        data=json.dumps(_export_data, ensure_ascii=False, indent=2),
        file_name="stock_backup.json",
        mime="application/json",
        key="download_backup",
    )
    _uploaded = st.file_uploader("导入备份文件", type=["json"], key="backup_uploader")
    if _uploaded is not None:
        _imp_data = None
        try:
            _imp_data = json.load(_uploaded)
        except Exception as _e:
            st.error(f"导入失败：文件读不到（{_e}）")
        if _imp_data is not None:
            _imp_holdings = _imp_data.get("holdings")
            _imp_pool = _imp_data.get("pool_additions")
            _valid = (
                isinstance(_imp_data, dict)
                and isinstance(_imp_holdings, list)
                and isinstance(_imp_pool, list)
                and all(isinstance(h, dict) and h.get("代码") for h in _imp_holdings)
                and all(isinstance(a, dict) and a.get("代码") for a in _imp_pool)
            )
            if not _valid:
                st.error("导入失败：文件格式唔啱，要有 holdings 同 pool_additions 两个清单，每项要有股票代码。")
            elif st.button("确认导入并写入文件", type="primary", key="confirm_import_backup"):
                _save_holdings(_imp_holdings)
                save_pool_additions(_imp_pool)
                st.session_state.holdings = list(_imp_holdings)
                st.cache_data.clear()
                st.success("导入成功！数据已写入文件。")
                st.rerun()

    st.success("设置已保存")

st.sidebar.markdown("---")
st.sidebar.caption("原型版本 v0.2 | 真实数据：同花顺行情（需 Key）/ 新浪 / akshare 资金流 / 快照，失败时自动用模拟兜底")
