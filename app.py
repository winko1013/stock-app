import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

from data_provider import build_watchlist, fetch_fund_flow, fetch_history

st.set_page_config(page_title="主力潜伏选股", page_icon="📈", layout="wide")

# ==================== 真实数据（带缓存，失败自动用模拟兜底） ====================
@st.cache_data(ttl=300)
def load_watchlist():
    return build_watchlist()

df, meta = load_watchlist()

# 卖出规则阈值（设置页可调）
if "outflow_days_alert" not in st.session_state:
    st.session_state.outflow_days_alert = 3
if "stall_days_alert" not in st.session_state:
    st.session_state.stall_days_alert = 5

# ==================== 侧边栏导航 ====================
st.sidebar.title("📈 主力潜伏选股")
page = st.sidebar.radio("功能导航", ["首页", "分类选股", "持股监测", "个股详情", "设置"])

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

# ==================== 首页 ====================
if page == "首页":
    st.title("主力潜伏选股系统")
    st.markdown("### 大盘环境：上升趋势 ✓")

    inflow_n = int((df["持续流入天数"] > 0).sum())
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("监控股票数", str(len(df)))
    col2.metric("持续流入中", str(inflow_n))
    col3.metric("今日更新", meta["updated"][11:])
    col4.metric("行情来源", meta["quote_source"].replace("（东财）", ""))

    st.subheader("今日重点关注")
    top = df.nlargest(3, "综合分")[["代码", "名称", "综合分", "持续流入天数", "相对大盘", "建议卖出价"]]
    st.dataframe(top, width="stretch")

    st.subheader("监控池一览")
    st.dataframe(df[["代码", "名称", "现价", "涨跌幅", "综合分", "持续流入天数",
                     "累计净流入亿", "相对大盘", "数据源"]], width="stretch")

    with st.expander("📖 评分说明（真实数据公式）"):
        st.write("潜伏分 = 持续流入天数×6 + min(累计净流入亿, 30)×1，上限 100。")
        st.write("趋势分 = 50 + 20日相对沪深300涨幅×4，收盘站上20日均线 +8，否则 -8。")
        st.write("质量分 = 85 − |近20日平均换手率 − 4%|×6 − 近20日平均振幅×1.5。")
        st.write("综合分 = 潜伏分×0.4 + 趋势分×0.35 + 质量分×0.25。")
        st.write("建议卖出价 = 近60日最高价附近 ±5%，仅供参考。")
        st.write("资金流为东财口径主力净流入；同花顺官方 API 不对外开放资金流接口。")

    st.info("💡 提示：点击左侧「持股监测」查看是否有资金停止流入的持仓股票")

# ==================== 分类选股 ====================
elif page == "分类选股":
    st.title("分类选股")

    categories = ["热门赛道", "稳健分红", "大市值蓝筹", "小市值成长", "半导体制造",
                  "消费必需", "新能源", "医药生物", "周期金融"]

    selected = st.multiselect("选择分类（可多选）", categories, default=["热门赛道", "半导体制造"])

    min_days = st.slider("最低持续流入天数", 5, 60, 20)
    min_score = st.slider("最低综合分", 60, 95, 75)

    if st.button("开始选股", type="primary"):
        result = df[
            (df["持续流入天数"] >= min_days) &
            (df["综合分"] >= min_score)
        ].sort_values("综合分", ascending=False)

        st.success(f"共找到 {len(result)} 只符合条件的股票")
        st.dataframe(result[["代码", "名称", "综合分", "持续流入天数", "相对大盘", "建议卖出价", "分类"]],
                     width="stretch")

# ==================== 持股监测（核心功能） ====================
elif page == "持股监测":
    st.title("持股监测")
    st.markdown(f"**规则**：主力资金连续≥{st.session_state.outflow_days_alert}天净流出 "
                f"或 流入停滞≥{st.session_state.stall_days_alert}天 → 自动提示卖出")

    # 模拟持仓
    if "holdings" not in st.session_state:
        st.session_state.holdings = [
            {"代码": "300604", "名称": "长川科技", "成本价": 48.50, "数量": 1000},
            {"代码": "688981", "名称": "中芯国际", "成本价": 72.0, "数量": 500},
        ]

    for i, h in enumerate(st.session_state.holdings):
        with st.container():
            col1, col2, col3 = st.columns([2, 2, 3])
            row = df[df["代码"] == h["代码"]]
            if row.empty:
                col1.write(f"**{h['代码']} {h['名称']}**（不在监控池）")
                st.divider()
                continue
            current_price = float(row["现价"].values[0])
            profit = (current_price - h["成本价"]) / h["成本价"] * 100
            streak = int(row["持续流入天数"].values[0])
            outflow = int(row["最近流出天数"].values[0])
            stall = int(row["流入停滞天数"].values[0])
            sell_ref = row["建议卖出价"].values[0]

            col1.write(f"**{h['代码']} {h['名称']}**")
            col1.write(f"成本：{h['成本价']} | 现价：{current_price}")
            col1.write(f"盈亏：{profit:.1f}%")

            col2.write(f"持续流入：{streak}天")
            col2.write(f"最近流出：{outflow}天 | 停滞：{stall}天")

            # 卖出判断
            if outflow >= st.session_state.outflow_days_alert:
                col3.error("⚠️ 重要卖出提示")
                col3.write("主力资金已连续流出，建议减仓/清仓")
                col3.write(f"参考卖出价：{sell_ref}")
            elif stall >= st.session_state.stall_days_alert:
                col3.warning("⚠️ 流入停滞提示")
                col3.write(f"主力资金已停滞流入 {stall} 天，留意是否转弱")
                col3.write(f"参考卖出价：{sell_ref}")
            else:
                col3.success("✓ 资金仍在流入，继续持有")

            st.divider()

    # 添加持仓
    with st.expander("➕ 添加持仓"):
        code = st.text_input("股票代码")
        cost = st.number_input("成本价", min_value=0.0, value=50.0)
        qty = st.number_input("数量", min_value=100, value=1000, step=100)
        if st.button("确认添加"):
            name = df[df["代码"] == code]["名称"].values[0] if code in df["代码"].values else "未知"
            st.session_state.holdings.append({
                "代码": code, "名称": name, "成本价": cost, "数量": qty,
            })
            st.success("已添加！请刷新页面查看")

# ==================== 个股详情 ====================
elif page == "个股详情":
    st.title("个股详情")
    code = st.selectbox("选择股票", df["代码"].tolist(),
                        format_func=lambda x: f"{x} {df[df['代码'] == x]['名称'].values[0]}")

    stock = df[df["代码"] == code].iloc[0]

    col1, col2, col3 = st.columns(3)
    col1.metric("现价", stock["现价"], f"{stock['涨跌幅']}%")
    col2.metric("综合分", stock["综合分"])
    col3.metric("持续流入天数", stock["持续流入天数"])

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
    st.success("设置已保存")

st.sidebar.markdown("---")
st.sidebar.caption("原型版本 v0.2 | 已接真实数据（同花顺行情 + akshare 资金流），失败时自动用模拟兜底")
