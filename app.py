import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import akshare as ak
import time

st.set_page_config(page_title="连板回调交易策略", layout="wide")

st.title("📈 连板回调交易策略 - 全市场扫描")
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
    if 'ST' in stock_name or 'st' in stock_name:
        return False
    
    if stock_code.startswith('8') or stock_code.startswith('4'):
        return False
    
    if not (stock_code.startswith('6') or stock_code.startswith('0') or stock_code.startswith('3')):
        return False
    
    return True

def get_stock_data(stock_code, days=100):
    """获取股票数据"""
    try:
        df = ak.stock_zh_a_hist(symbol=stock_code, period="daily", adjust="qfq")
        
        if df is None or len(df) == 0:
            return None
        
        df = df.tail(days)
        
        df = df.rename(columns={
            '日期': '日期',
            '收盘': '收盘价'
        })
        
        df = df[['日期', '收盘价']].copy()
        
        return df
    except Exception as e:
        return None

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
        
        if stage == 0:
            day_count += 1
            if day_count >= 14:
                signal = '买入'
                position = '持有'
                entry_price = row['收盘价']
                stage = 1
                red_count = 0
                
        elif stage == 1 and position == '持有':
            if row['红绿'] == '红':
                red_count += 1
                if red_count >= 3:
                    signal = '卖出'
                    position = None
                    stage = 2
                    green_count = 0
            else:
                red_count = 0
                
        elif stage == 2 and position is None:
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
                
        elif stage == 3 and position == '持有':
            if row['红绿'] == '红':
                red_count += 1
                if red_count >= 3:
                    signal = '卖出'
                    position = None
                    stage = 4
                    green_count = 0
            else:
                red_count = 0
                
        elif stage == 4 and position is None:
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
                
        elif stage == 5 and position == '持有':
            if row['红绿'] == '红':
                red_count += 1
                if red_count >= 7:
                    signal = '卖出'
                    position = None
                    stage = 6
                    green_count = 0
            else:
                red_count = 0
                
        elif stage == 6 and position is None:
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
            '阶段': stage,
            '红线计数': red_count,
            '绿线计数': green_count
        })
    
    return pd.DataFrame(signals)

def generate_prediction(result_df):
    """生成预测和建议"""
    last_row = result_df.iloc[-1]
    current_stage = last_row['阶段']
    current_position = last_row['持仓']
    red_count = last_row['红线计数']
    green_count = last_row['绿线计数']
    current_color = last_row['红绿']
    
    prediction = {
        'stage': current_stage,
        'position': current_position,
        'action': '',
        'reason': '',
        'next_signal': '',
        'countdown': 0,
        'risk_level': ''
    }
    
    if current_stage == 0:
        days_passed = len(result_df)
        days_left = max(0, 14 - days_passed)
        prediction['action'] = '等待观察'
        prediction['reason'] = f'还需等待{days_left}天'
        prediction['next_signal'] = '首次买入'
        prediction['countdown'] = days_left
        prediction['risk_level'] = '低'
        
    elif current_stage == 1 and current_position == '持有':
        needed = 3 - red_count
        if current_color == '红':
            prediction['action'] = '继续持有'
            prediction['reason'] = f'已{red_count}红，再{needed}红卖出'
            prediction['next_signal'] = '卖出'
            prediction['countdown'] = needed
            prediction['risk_level'] = '中' if red_count >= 2 else '低'
        else:
            prediction['action'] = '继续持有'
            prediction['reason'] = '等待3红卖出'
            prediction['next_signal'] = '卖出'
            prediction['countdown'] = 3
            prediction['risk_level'] = '低'
            
    elif current_stage == 2 and current_position == '空仓':
        needed = 2 - green_count
        if current_color == '绿':
            prediction['action'] = '准备买入'
            prediction['reason'] = f'已{green_count}阴，再{needed}阴买入'
            prediction['next_signal'] = '买入'
            prediction['countdown'] = needed
            prediction['risk_level'] = '低'
        else:
            prediction['action'] = '等待回调'
            prediction['reason'] = '等待2阴买入'
            prediction['next_signal'] = '买入'
            prediction['countdown'] = 2
            prediction['risk_level'] = '低'
            
    elif current_stage == 3 and current_position == '持有':
        needed = 3 - red_count
        if current_color == '红':
            prediction['action'] = '继续持有'
            prediction['reason'] = f'已{red_count}红，再{needed}红卖出'
            prediction['next_signal'] = '卖出'
            prediction['countdown'] = needed
            prediction['risk_level'] = '中' if red_count >= 2 else '低'
        else:
            prediction['action'] = '继续持有'
            prediction['reason'] = '等待3红卖出'
            prediction['next_signal'] = '卖出'
            prediction['countdown'] = 3
            prediction['risk_level'] = '低'
            
    elif current_stage == 4 and current_position == '空仓':
        needed = 7 - green_count
        if current_color == '绿':
            prediction['action'] = '准备买入'
            prediction['reason'] = f'已{green_count}阴，再{needed}阴买入'
            prediction['next_signal'] = '买入'
            prediction['countdown'] = needed
            prediction['risk_level'] = '低'
        else:
            prediction['action'] = '等待回调'
            prediction['reason'] = '等待7阴买入'
            prediction['next_signal'] = '买入'
            prediction['countdown'] = 7
            prediction['risk_level'] = '低'
            
    elif current_stage == 5 and current_position == '持有':
        needed = 7 - red_count
        if current_color == '红':
            prediction['action'] = '继续持有'
            prediction['reason'] = f'已{red_count}阳，再{needed}阳卖出'
            prediction['next_signal'] = '卖出'
            prediction['countdown'] = needed
            prediction['risk_level'] = '高' if red_count >= 5 else '中'
        else:
            prediction['action'] = '继续持有'
            prediction['reason'] = '等待7阳卖出'
            prediction['next_signal'] = '卖出'
            prediction['countdown'] = 7
            prediction['risk_level'] = '中'
            
    elif current_stage == 6 and current_position == '空仓':
        needed = 14 - green_count
        if current_color == '绿':
            prediction['action'] = '准备买入'
            prediction['reason'] = f'已{green_count}阴，再{needed}阴买入'
            prediction['next_signal'] = '最后买入'
            prediction['countdown'] = needed
            prediction['risk_level'] = '低'
        else:
            prediction['action'] = '等待回调'
            prediction['reason'] = '等待14阴买入'
            prediction['next_signal'] = '最后买入'
            prediction['countdown'] = 14
            prediction['risk_level'] = '低'
            
    elif current_stage == 7:
        prediction['action'] = '持有'
        prediction['reason'] = '策略完成'
        prediction['next_signal'] = '无'
        prediction['countdown'] = 0
        prediction['risk_level'] = '自定义'
    
    return prediction

# 主界面
st.subheader("🔍 全市场股票筛选")

col1, col2, col3 = st.columns(3)

with col1:
    days_input = st.number_input("数据天数", min_value=30, max_value=365, value=100)

with col2:
    filter_signal = st.selectbox(
        "筛选条件",
        ["所有符合策略的股票", "即将买入（1-2天内）", "即将卖出（1-2天内）", "当前持有", "当前空仓"]
    )

with col3:
    max_stocks = st.number_input("最大扫描数量", min_value=10, max_value=500, value=100, help="扫描股票数量越多，耗时越长")

# 开始扫描按钮
if st.button("🚀 开始全市场扫描", type="primary"):
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # 获取A股列表
        status_text.text("正在获取A股列表...")
        stock_list = ak.stock_zh_a_spot_em()
        
        # 筛选有效股票
        valid_stocks = []
        for idx, row in stock_list.iterrows():
            code = row['代码']
            name = row['名称']
            if is_valid_stock(code, name):
                valid_stocks.append({'代码': code, '名称': name})
        
        # 限制扫描数量
        valid_stocks = valid_stocks[:max_stocks]
        total_stocks = len(valid_stocks)
        
        status_text.text(f"找到 {total_stocks} 只有效股票，开始分析...")
        
        # 扫描股票
        results = []
        
        for i, stock in enumerate(valid_stocks):
            code = stock['代码']
            name = stock['名称']
            
            progress_bar.progress((i + 1) / total_stocks)
            status_text.text(f"正在分析 {i+1}/{total_stocks}: {code} {name}")
            
            # 获取股票数据
            df_stock = get_stock_data(code, days_input)
            
            if df_stock is not None and len(df_stock) >= 15:
                try:
                    # 分析策略
                    result_df = analyze_strategy(df_stock)
                    prediction = generate_prediction(result_df)
                    
                    # 获取最新价格
                    latest_price = result_df.iloc[-1]['收盘价']
                    latest_date = result_df.iloc[-1]['日期']
                    
                    # 根据筛选条件过滤
                    should_add = False
                    
                    if filter_signal == "所有符合策略的股票":
                        should_add = True
                    elif filter_signal == "即将买入（1-2天内）":
                        if prediction['next_signal'] in ['买入', '首次买入', '最后买入'] and prediction['countdown'] <= 2:
                            should_add = True
                    elif filter_signal == "即将卖出（1-2天内）":
                        if prediction['next_signal'] == '卖出' and prediction['countdown'] <= 2:
                            should_add = True
                    elif filter_signal == "当前持有":
                        if prediction['position'] == '持有':
                            should_add = True
                    elif filter_signal == "当前空仓":
                        if prediction['position'] == '空仓':
                            should_add = True
                    
                    if should_add:
                        results.append({
                            '股票代码': code,
                            '股票名称': name,
                            '最新价格': f"{latest_price:.2f}",
                            '当前状态': prediction['position'],
                            '操作建议': prediction['action'],
                            '下一信号': prediction['next_signal'],
                            '倒计时': f"{prediction['countdown']}天" if prediction['countdown'] > 0 else "已完成",
                            '风险等级': prediction['risk_level'],
                            '策略说明': prediction['reason'],
                            '阶段': prediction['stage'],
                            '更新日期': latest_date
                        })
                except:
                    pass
            
            # 控制请求频率
            time.sleep(0.1)
        
        progress_bar.empty()
        status_text.empty()
        
        # 显示结果
        if len(results) > 0:
            st.success(f"✅ 扫描完成！找到 {len(results)} 只符合条件的股票")
            
            result_df = pd.DataFrame(results)
            
            # 统计信息
            st.subheader("📊 筛选结果统计")
            
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("符合条件股票", len(results))
            with col2:
                hold_count = len(result_df[result_df['当前状态'] == '持有'])
                st.metric("当前持有", hold_count)
            with col3:
                buy_soon = len(result_df[result_df['下一信号'].str.contains('买入')])
                st.metric("即将买入", buy_soon)
            with col4:
                sell_soon = len(result_df[result_df['下一信号'] == '卖出'])
                st.metric("即将卖出", sell_soon)
            
            # 显示结果表格
            st.subheader("📋 股票列表")
            
            # 按风险等级着色
            def highlight_risk(row):
                if row['风险等级'] == '高':
                    return ['background-color: #ffcccc'] * len(row)
                elif row['风险等级'] == '中':
                    return ['background-color: #fff4cc'] * len(row)
                elif row['风险等级'] == '低':
                    return ['background-color: #ccffcc'] * len(row)
                else:
                    return [''] * len(row)
            
            # 显示表格
            display_df = result_df[['股票代码', '股票名称', '最新价格', '当前状态', '操作建议', '下一信号', '倒计时', '风险等级', '策略说明']]
            st.dataframe(display_df, use_container_width=True, height=600)
            
            # 下载按钮
            csv = result_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 下载结果（CSV）",
                data=csv,
                file_name=f"stock_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
            # 详细图表
            with st.expander("📈 查看风险分布"):
                risk_counts = result_df['风险等级'].value_counts()
                fig = go.Figure(data=[go.Pie(labels=risk_counts.index, values=risk_counts.values)])
                fig.update_layout(title="风险等级分布")
                st.plotly_chart(fig, use_container_width=True)
            
        else:
            st.warning("⚠️ 未找到符合条件的股票，请调整筛选条件或增加扫描数量")
            
    except Exception as e:
        st.error(f"❌ 扫描失败: {str(e)}")
        progress_bar.empty()
        status_text.empty()

# 页脚
st.markdown("---")
st.markdown("""
💡 **使用说明**: 
- 选择数据天数和筛选条件
- 点击"开始全市场扫描"自动分析所有A股
- 系统自动剔除ST股票和北交所股票
- 扫描完成后可下载结果CSV文件
- ⚠️ 扫描数量越多耗时越长，建议从100只开始测试
""")