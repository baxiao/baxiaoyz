import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go

st.set_page_config(page_title="连板回调交易策略", layout="wide")

st.title("📈 连板回调交易策略分析")
st.markdown("---")

# 侧边栏配置
st.sidebar.header("策略参数设置")
st.sidebar.markdown("""
**策略规则：**
1. 14天后首次进场
2. 3红（阳线）后离场
3. 2阴（阴线）后再次进场
4. 3红后离场
5. 7阴后再次进场
6. 7阳后离场
7. 14阴后最后进场
""")

# 数据输入方式选择
input_method = st.sidebar.radio("数据输入方式", ["手动输入", "上传CSV文件"])

def analyze_strategy(df):
    """分析交易策略"""
    df = df.copy()
    df['涨跌'] = df['收盘价'].diff()
    df['红绿'] = df['涨跌'].apply(lambda x: '红' if x > 0 else ('绿' if x < 0 else '平'))
    
    signals = []
    position = None
    entry_price = 0
    day_count = 0
    red_count = 0
    green_count = 0
    stage = 0  # 0: 等待14天, 1: 等待3红, 2: 等待2阴, 3: 等待3红, 4: 等待7阴, 5: 等待7阳, 6: 等待14阴
    
    for idx, row in df.iterrows():
        signal = None
        
        if stage == 0:  # 等待14天后进场
            day_count += 1
            if day_count >= 14:
                signal = '买入'
                position = '持有'
                entry_price = row['收盘价']
                stage = 1
                red_count = 0
                
        elif stage == 1 and position == '持有':  # 等待3红离场
            if row['红绿'] == '红':
                red_count += 1
                if red_count >= 3:
                    signal = '卖出'
                    position = None
                    stage = 2
                    green_count = 0
            else:
                red_count = 0
                
        elif stage == 2 and position is None:  # 等待2阴进场
            if row['红绿'] == '绿':
                green_count += 1
                if green_count >= 2:
                    signal = '买入'
                    position = '持有'
                    entry_price = row['收盘价']
                    stage = 3
                    red_count = 0
            else:
                green_count = 0
                
        elif stage == 3 and position == '持有':  # 等待3红离场
            if row['红绿'] == '红':
                red_count += 1
                if red_count >= 3:
                    signal = '卖出'
                    position = None
                    stage = 4
                    green_count = 0
            else:
                red_count = 0
                
        elif stage == 4 and position is None:  # 等待7阴进场
            if row['红绿'] == '绿':
                green_count += 1
                if green_count >= 7:
                    signal = '买入'
                    position = '持有'
                    entry_price = row['收盘价']
                    stage = 5
                    red_count = 0
            else:
                green_count = 0
                
        elif stage == 5 and position == '持有':  # 等待7阳离场
            if row['红绿'] == '红':
                red_count += 1
                if red_count >= 7:
                    signal = '卖出'
                    position = None
                    stage = 6
                    green_count = 0
            else:
                red_count = 0
                
        elif stage == 6 and position is None:  # 等待14阴进场
            if row['红绿'] == '绿':
                green_count += 1
                if green_count >= 14:
                    signal = '买入'
                    position = '持有'
                    entry_price = row['收盘价']
                    stage = 7  # 策略完成
            else:
                green_count = 0
        
        signals.append({
            '日期': row['日期'],
            '收盘价': row['收盘价'],
            '红绿': row['红绿'],
            '信号': signal if signal else '',
            '持仓': position if position else '空仓',
            '阶段': stage
        })
    
    return pd.DataFrame(signals)

# 数据输入
if input_method == "手动输入":
    st.subheader("📝 手动输入股票数据")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        num_days = st.number_input("输入天数", min_value=20, max_value=200, value=50)
    
    # 创建示例数据
    if 'data' not in st.session_state or st.button("生成随机示例数据"):
        dates = [datetime.now() - timedelta(days=i) for i in range(num_days, 0, -1)]
        prices = [100]
        for _ in range(num_days - 1):
            change = np.random.randn() * 2
            prices.append(max(prices[-1] + change, 1))
        
        st.session_state.data = pd.DataFrame({
            '日期': dates,
            '收盘价': prices
        })
    
    st.dataframe(st.session_state.data, use_container_width=True, height=300)
    
    df_input = st.session_state.data

else:  # CSV上传
    st.subheader("📤 上传CSV文件")
    st.info("CSV文件需要包含'日期'和'收盘价'两列")
    
    uploaded_file = st.file_uploader("选择CSV文件", type=['csv'])
    
    if uploaded_file:
        df_input = pd.read_csv(uploaded_file)
        st.dataframe(df_input.head(10), use_container_width=True)
    else:
        df_input = None

# 分析按钮
if st.button("🚀 开始分析", type="primary"):
    if df_input is not None and len(df_input) > 0:
        with st.spinner("正在分析策略..."):
            result_df = analyze_strategy(df_i