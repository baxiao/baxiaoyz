import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import akshare as ak

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

st.sidebar.markdown("---")
st.sidebar.markdown("""
**筛选规则：**
- ✅ 仅A股（沪深市场）
- ❌ 剔除ST股票
- ❌ 剔除北交所股票
""")

def is_valid_stock(stock_code, stock_name):
    """检查股票是否符合条件"""
    # 剔除ST股票
    if 'ST' in stock_name or 'st' in stock_name:
        return False, "ST股票"
    
    # 剔除北交所（股票代码以8、4开头）
    if stock_code.startswith('8') or stock_code.startswith('4'):
        return False, "北交所股票"
    
    # 只保留沪深A股（6开头的沪市，0、3开头的深市）
    if not (stock_code.startswith('6') or stock_code.startswith('0') or stock_code.startswith('3')):
        return False, "非A股"
    
    return True, "有效"

def get_stock_data(stock_code, days=100):
    """获取股票数据"""
    try:
        # 使用akshare获取股票数据
        df = ak.stock_zh_a_hist(symbol=stock_code, period="daily", adjust="qfq")
        
        if df is None or len(df) == 0:
            return None, "无法获取数据"
        
        # 只保留最近的天数
        df = df.tail(days)
        
        # 重命名列
        df = df.rename(columns={
            '日期': '日期',
            '收盘': '收盘价'
        })
        
        # 只保留需要的列
        df = df[['日期', '收盘价']].copy()
        
        return df, "成功"
    except Exception as e:
        return None, f"获取失败: {str(e)}"

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
    stage = 0
    
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
                    stage = 7
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

# 主界面 - 股票代码输入
st.subheader("🔍 输入股票代码")

col1, col2 = st.columns([3, 1])

with col1:
    stock_code = st.text_input(
        "股票代码（6位数字）", 
        placeholder="例如: 000001, 600519, 300750",
        help="输入沪深A股代码，自动剔除ST和北交所股票"
    )

with col2:
    days_input = st.number_input("数据天数", min_value=30, max_value=365, value=100)

# 分析按钮
if st.button("🚀 开始分析", type="primary"):
    if stock_code:
        # 验证股票代码格式
        if not stock_code.isdigit() or len(stock_code) != 6:
            st.error("❌ 请输入正确的6位股票代码")
        else:
            with st.spinner("正在获取股票数据..."):
                # 获取股票名称
                try:
                    stock_info = ak.stock_individual_info_em(symbol=stock_code)
                    stock_name = stock_info[stock_info['item'] == '股票简称']['value'].values[0]
                except:
                    stock_name = "未知"
                
                # 验证股票是否符合条件
                is_valid, reason = is_valid_stock(stock_code, stock_name)
                
                if not is_valid:
                    st.error(f"❌ {stock_code} {stock_name} 不符合筛选条件：{reason}")
                else:
                    st.info(f"✅ {stock_code} {stock_name} - 符合条件，正在分析...")
                    
                    # 获取股票数据
                    df_stock, status = get_stock_data(stock_code, days_input)
                    
                    if df_stock is None:
                        st.error(f"❌ 获取股票数据失败: {status}")
                    else:
                        # 分析策略
                        result_df = analyze_strategy(df_stock)
                        
                        st.success(f"✅ 分析完成！股票: {stock_code} {stock_name}")
                        
                        # 显示结果
                        st.subheader("📊 交易信号详情")
                        
                        # 筛选有信号的行
                        signals_only = result_df[result_df['信号'] != '']
                        
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("股票代码", stock_code)
                        with col2:
                            buy_count = len(signals_only[signals_only['信号'] == '买入'])
                            st.metric("买入次数", buy_count)
                        with col3:
                            sell_count = len(signals_only[signals_only['信号'] == '卖出'])
                            st.metric("卖出次数", sell_count)
                        with col4:
                            final_position = result_df.iloc[-1]['持仓']
                            st.metric("当前状态", final_position)
                        
                        # 显示信号表格
                        if len(signals_only) > 0:
                            st.dataframe(signals_only, use_container_width=True)
                        else:
                            st.info("暂无交易信号")
                        
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
                        if len(buy_signals) > 0:
                            fig.add_trace(go.Scatter(
                                x=buy_signals['日期'],
                                y=buy_signals['收盘价'],
                                mode='markers',
                                name='买入',
                                marker=dict(color='green', size=12, symbol='triangle-up')
                            ))
                        
                        # 卖出信号
                        sell_signals = result_df[result_df['信号'] == '卖出']
                        if len(sell_signals) > 0:
                            fig.add_trace(go.Scatter(
                                x=sell_signals['日期'],
                                y=sell_signals['收盘价'],
                                mode='markers',
                                name='卖出',
                                marker=dict(color='red', size=12, symbol='triangle-down')
                            ))
                        
                        fig.update_layout(
                            title=f"{stock_code} {stock_name} - 股票价格与交易信号",
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
        st.warning("⚠️ 请输入股票代码")

# 页脚
st.markdown("---")
st.markdown("""
💡 **使用说明**: 
- 输入6位A股股票代码（如000001、600519）
- 系统自动剔除ST股票和北交所股票
- 点击'开始分析'查看交易策略的买卖信号
""")