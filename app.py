import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

st.set_page_config(page_title="主力潜伏选股", page_icon="📈", layout="wide")

# ==================== 模拟数据（后续可替换真实接口） ====================
def get_mock_stock_data():
    data = {
        "代码": ["300604", "688981", "002371", "300750", "600519", "000858", "300014", "601318", "002415"],
        "名称": ["长川科技", "中芯国际", "北方华创", "宁德时代", "贵州茅台", "五粮液", "亿纬锂能", "中国平安", "海康威视"],
        "现价": [178.09, 85.6, 320.5, 198.3, 1650.0, 128.5, 45.2, 48.6, 32.8],
        "潜伏分": [92, 85, 88, 78, 65, 70, 82, 60, 75],
        "质量分": [88, 82, 90, 85, 95, 92, 80, 88, 83],
        "趋势分": [85, 80, 86, 75, 70, 72, 78, 65, 70],
        "综合分": [89, 83, 88, 79, 76, 77, 80, 70, 76],
        "持续流入天数": [47, 32, 28, 15, 5, 8, 22, 3, 12],
        "首次流入日期": ["2025-09-15", "2025-10-08", "2025-10-20", "2025-11-01", "2025-11-10", "2025-11-05", "2025-10-25", "2025-11-15", "2025-11-08"],
        "累计净流入亿": [18.5, 12.3, 15.8, 9.2, 3.1, 4.5, 7.8, 1.2, 5.6],
        "相对大盘": ["强于大盘", "强于大盘", "同步大盘", "同步大盘", "弱于大盘", "同步大盘", "强于大盘", "弱于大盘", "同步大盘"],
        "分类": ["热门赛道+半导体", "热门赛道+半导体", "热门赛道+半导体", "新能源", "大市值蓝筹+消费", "大市值蓝筹+消费", "新能源", "周期金融", "大市值蓝筹"],
        "建议卖出价": ["220-250", "95-110", "360-400", "230-260", "1800-2000", "145-160", "55-65", "55-60", "38-42"]
    }
    return pd.DataFrame(data)

df = get_mock_stock_data()

# ==================== 侧边栏导航 ====================
st.sidebar.title("📈 主力潜伏选股")
page = st.sidebar.radio("功能导航", ["首页", "分类选股", "持股监测", "个股详情", "设置"])

# ==================== 首页 ====================
if page == "首页":
    st.title("主力潜伏选股系统")
    st.markdown("### 大盘环境：上升趋势 ✓")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("监控股票数", "28")
    col2.metric("持续流入中", "9")
    col3.metric("持股预警", "1", delta="需关注")
    col4.metric("今日更新", "刚刚")
    
    st.subheader("今日重点关注")
    top = df.nlargest(3, "综合分")[["代码", "名称", "综合分", "持续流入天数", "相对大盘", "建议卖出价"]]
    st.dataframe(top, use_container_width=True)
    
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
                     use_container_width=True)

# ==================== 持股监测（核心功能） ====================
elif page == "持股监测":
    st.title("持股监测")
    st.markdown("**规则**：主力资金连续≥3天净流出 或 流入停滞≥5天 → 自动提示卖出")
    
    # 模拟持仓
    if "holdings" not in st.session_state:
        st.session_state.holdings = [
            {"代码": "300604", "名称": "长川科技", "成本价": 48.50, "数量": 1000, "持续流入天数": 47, "最近流出天数": 3},
            {"代码": "688981", "名称": "中芯国际", "成本价": 72.0, "数量": 500, "持续流入天数": 32, "最近流出天数": 0},
        ]
    
    for i, h in enumerate(st.session_state.holdings):
        with st.container():
            col1, col2, col3 = st.columns([2, 2, 3])
            current_price = df[df["代码"] == h["代码"]]["现价"].values[0]
            profit = (current_price - h["成本价"]) / h["成本价"] * 100
            
            col1.write(f"**{h['代码']} {h['名称']}**")
            col1.write(f"成本：{h['成本价']} | 现价：{current_price}")
            col1.write(f"盈亏：{profit:.1f}%")
            
            col2.write(f"持续流入：{h['持续流入天数']}天")
            col2.write(f"最近流出：{h['最近流出天数']}天")
            
            # 卖出判断
            if h["最近流出天数"] >= 3:
                col3.error("⚠️ 重要卖出提示")
                col3.write("主力资金已连续流出，建议减仓/清仓")
                col3.write(f"参考卖出价：{df[df['代码']==h['代码']]['建议卖出价'].values[0]}")
            else:
                col3.success("✓ 资金仍在流入，继续持有")
            
            st.divider()
    
    # 添加持仓
    with st.expander("➕ 添加持仓"):
        code = st.text_input("股票代码")
        cost = st.number_input("成本价", min_value=0.0, value=50.0)
        qty = st.number_input("数量", min_value=100, value=1000, step=100)
        if st.button("确认添加"):
            name = df[df["代码"]==code]["名称"].values[0] if code in df["代码"].values else "未知"
            st.session_state.holdings.append({
                "代码": code, "名称": name, "成本价": cost, "数量": qty,
                "持续流入天数": 20, "最近流出天数": 0
            })
            st.success("已添加！请刷新页面查看")

# ==================== 个股详情 ====================
elif page == "个股详情":
    st.title("个股详情")
    code = st.selectbox("选择股票", df["代码"].tolist(), format_func=lambda x: f"{x} {df[df['代码']==x]['名称'].values[0]}")
    
    stock = df[df["代码"] == code].iloc[0]
    
    col1, col2, col3 = st.columns(3)
    col1.metric("现价", stock["现价"])
    col2.metric("综合分", stock["综合分"])
    col3.metric("持续流入天数", stock["持续流入天数"])
    
    st.subheader("主力资金潜伏监测")
    st.write(f"首次明显流入时间：{stock['首次流入日期']}")
    st.write(f"已持续净流入：{stock['持续流入天数']} 天")
    st.write(f"累计净流入：{stock['累计净流入亿']} 亿元")
    st.write(f"相对大盘：{stock['相对大盘']}")
    
    st.subheader("卖出建议")
    st.warning(f"建议卖出价格区间：{stock['建议卖出价']} 元")
    st.write("触发条件：主力连续3天净流出 / 跌破关键支撑 / 相对大盘转弱")
    
    # 简单模拟图表
    dates = pd.date_range(end=datetime.now(), periods=60)
    price = np.cumsum(np.random.randn(60)) + stock["现价"] - 30
    fund = np.cumsum(np.random.randn(60) * 0.5)
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=price, name="股价", line=dict(color="orange")))
    fig.add_trace(go.Scatter(x=dates, y=fund, name="累积资金", yaxis="y2", line=dict(color="blue")))
    fig.update_layout(title="股价 vs 主力资金累积（模拟）", yaxis2=dict(overlaying="y", side="right"))
    st.plotly_chart(fig, use_container_width=True)

# ==================== 设置 ====================
elif page == "设置":
    st.title("设置")
    st.slider("连续净流出几天触发卖出提示", 2, 7, 3)
    st.slider("流入停滞几天触发提示", 3, 10, 5)
    st.checkbox("卖出提示时推送通知", value=True)
    st.checkbox("必须结合大盘转弱才提示", value=False)
    st.success("设置已保存（演示）")

st.sidebar.markdown("---")
st.sidebar.caption("原型版本 v0.1 | 数据为模拟，后续可接真实接口")

