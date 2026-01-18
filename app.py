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
    
    if 'data' in st.session_state:
        st.dataframe(st.session_state.data, use_container_width=True, height=300)
        df_input = st.session_state.data
    else:
        df_input = None

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
            result_df = analyze_strategy(df_input)
            
            st.success("✅ 分析完成！")
            
            # 显示结果
            st.subheader("📊 交易信号详情")
            
            # 筛选有信号的行
            signals_only = result_df[result_df['信号'] != '']
            
            col1, col2, col3 = st.columns(3)
            with col1:
                buy_count = len(signals_only[signals_only['信号'] == '买入'])
                st.metric("买入次数", buy_count)
            with col2:
                sell_count = len(signals_only[signals_only['信号'] == '卖出'])
                st.metric("卖出次数", sell_count)
            with col3:
                final_position = result_df.iloc[-1]['持仓']
                st.metric("当前状态", final_position)
            
            # 显示信号表格
            st.dataframe(signals_only, use_container_width=True)
            
            # 绘制价格走势图
            st.subheader("📈 价格走势与交易信号")
            
            fig = go.Figure()
            
            # 价格曲线
            fig.add_trace(go.Scatter(
                x=result_df['日期'],
                y=result_df['收盘价'],
                mode='lines',
                name='收盘价',
                line=dict(color='blue', width=2)
            ))
            
            # 买入信号
            buy_signals = result_df[result_df['信号'] == '买入']
            fig.add_trace(go.Scatter(
                x=buy_signals['日期'],
                y=buy_signals['收盘价'],
                mode='markers',
                name='买入',
                marker=dict(color='green', size=12, symbol='triangle-up')
            ))
            
            # 卖出信号
            sell_signals = result_df[result_df['信号'] == '卖出']
            fig.add_trace(go.Scatter(
                x=sell_signals['日期'],
                y=sell_signals['收盘价'],
                mode='markers',
                name='卖出',
                marker=dict(color='red', size=12, symbol='triangle-down')
            ))
            
            fig.update_layout(
                title="股票价格与交易信号",
                xaxis_title="日期",
                yaxis_title="价格",
                hovermode='x unified',
                height=500
            )
            
            st.plotly_chart(fig, use_container_width=True)
            
            # 完整数据表
            with st.expander("📋 查看完整数据"):
                st.dataframe(result_df, use_container_width=True)
    else:
        st.warning("⚠️ 请先输入或上传数据")

# 页脚
st.markdown("---")
st.markdown("💡 **使用说明**: 输入股票数据后，点击'开始分析'按钮查看交易策略的买卖信号。")