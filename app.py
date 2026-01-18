import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
import akshare as ak
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

st.set_page_config(page_title="连板回调策略", layout="wide")

st.title("📈 连板回调策略 - 全市场扫描")
st.markdown("---")

# 侧边栏配置
st.sidebar.header("策略说明")
st.sidebar.markdown("""
**策略规则：**

🎯 **核心策略**：筛选出现连板后回调14天的个股

**具体条件：**
1. 历史出现过连板（连续涨停）
2. 从连板高点回调满14个交易日
3. 回调期间未再次涨停

**适用场景：**
- 寻找超跌反弹机会
- 连板股回调后的二次启动
- 短线交易机会
""")

st.sidebar.markdown("---")
st.sidebar.markdown("""
**筛选规则：**
- ✅ 仅A股（沪深市场）
- ❌ 剔除ST股票
- ❌ 剔除北交所股票
""")

st.sidebar.markdown("---")
st.sidebar.info("💡 使用多线程并发处理，大幅提升扫描速度！")

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
            '收盘': '收盘价',
            '开盘': '开盘价',
            '最高': '最高价',
            '最低': '最低价',
            '涨跌幅': '涨跌幅'
        })
        
        # 确保有涨跌幅列
        if '涨跌幅' not in df.columns:
            df['涨跌幅'] = df['收盘价'].pct_change() * 100
        
        return df
    except Exception as e:
        return None

def detect_lianban_callback(df):
    """
    检测连板后回调14天的股票
    返回：(是否符合, 连板天数, 回调天数, 连板日期, 最高价, 当前价, 回调幅度)
    """
    if df is None or len(df) < 20:
        return False, 0, 0, None, 0, 0, 0
    
    df = df.copy()
    
    # 判断涨停（涨幅 >= 9.5%，考虑误差）
    df['是否涨停'] = df['涨跌幅'] >= 9.5
    
    # 寻找连板（至少2个涨停）
    lianban_found = False
    lianban_end_idx = -1
    lianban_days = 0
    lianban_high_price = 0
    lianban_date = None
    
    consecutive_count = 0
    
    for i in range(len(df)):
        if df.iloc[i]['是否涨停']:
            consecutive_count += 1
        else:
            # 连续涨停结束
            if consecutive_count >= 2:  # 至少2个涨停才算连板
                lianban_found = True
                lianban_days = consecutive_count
                lianban_end_idx = i - 1
                lianban_high_price = df.iloc[lianban_end_idx]['收盘价']
                lianban_date = df.iloc[lianban_end_idx]['日期']
                break
            consecutive_count = 0
    
    if not lianban_found:
        return False, 0, 0, None, 0, 0, 0
    
    # 计算从连板结束后的回调天数
    callback_days = len(df) - lianban_end_idx - 1
    
    # 检查回调期间是否再次涨停
    callback_period = df.iloc[lianban_end_idx + 1:]
    has_zhangting_in_callback = callback_period['是否涨停'].any()
    
    # 当前价格
    current_price = df.iloc[-1]['收盘价']
    
    # 计算回调幅度
    callback_rate = ((current_price - lianban_high_price) / lianban_high_price) * 100
    
    # 判断是否符合条件：回调满14天，且回调期间未再涨停
    if callback_days >= 14 and not has_zhangting_in_callback:
        return True, lianban_days, callback_days, lianban_date, lianban_high_price, current_price, callback_rate
    
    return False, lianban_days, callback_days, lianban_date, lianban_high_price, current_price, callback_rate

def process_single_stock(stock_info, days_input):
    """处理单个股票（用于多线程）"""
    code = stock_info['代码']
    name = stock_info['名称']
    
    try:
        # 获取股票数据
        df_stock = get_stock_data(code, days_input)
        
        if df_stock is not None and len(df_stock) >= 20:
            # 检测连板回调
            is_match, lianban_days, callback_days, lianban_date, high_price, current_price, callback_rate = detect_lianban_callback(df_stock)
            
            if is_match:
                latest_date = df_stock.iloc[-1]['日期']
                
                # 计算风险等级
                if callback_rate >= -10:
                    risk = '低'
                elif callback_rate >= -20:
                    risk = '中'
                else:
                    risk = '高'
                
                return {
                    '股票代码': code,
                    '股票名称': name,
                    '连板天数': lianban_days,
                    '连板日期': str(lianban_date)[:10],
                    '连板最高价': f"{high_price:.2f}",
                    '当前价格': f"{current_price:.2f}",
                    '回调天数': callback_days,
                    '回调幅度': f"{callback_rate:.2f}%",
                    '风险等级': risk,
                    '更新日期': str(latest_date)[:10]
                }
    except:
        pass
    
    return None

# 主界面
st.subheader("🔍 全市场股票筛选")

col1, col2, col3 = st.columns(3)

with col1:
    days_input = st.number_input("数据天数", min_value=30, max_value=365, value=100, help="建议100天以上")

with col2:
    max_stocks = st.number_input("最大扫描数量", min_value=10, max_value=2000, value=500, help="扫描股票数量")

with col3:
    thread_count = st.number_input("线程数", min_value=1, max_value=20, value=10, help="线程越多速度越快")

# 开始扫描按钮
if st.button("🚀 开始全市场扫描（多线程加速）", type="primary"):
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    start_time = time.time()
    
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
        
        status_text.text(f"找到 {total_stocks} 只有效股票，使用 {thread_count} 个线程并发分析...")
        
        # 使用多线程处理
        results = []
        completed = 0
        lock = threading.Lock()
        
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            # 提交所有任务
            future_to_stock = {
                executor.submit(process_single_stock, stock, days_input): stock 
                for stock in valid_stocks
            }
            
            # 处理完成的任务
            for future in as_completed(future_to_stock):
                completed += 1
                
                # 更新进度
                progress = completed / total_stocks
                progress_bar.progress(progress)
                status_text.text(f"进度: {completed}/{total_stocks} ({progress*100:.1f}%) - 使用{thread_count}线程并发处理")
                
                # 获取结果
                result = future.result()
                if result is not None:
                    with lock:
                        results.append(result)
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        progress_bar.empty()
        status_text.empty()
        
        # 显示结果
        if len(results) > 0:
            st.success(f"✅ 扫描完成！耗时 {elapsed_time:.1f} 秒，找到 {len(results)} 只连板回调14天的股票（共扫描{total_stocks}只）")
            
            result_df = pd.DataFrame(results)
            
            # 按回调天数排序（刚好14天的排在前面）
            result_df['回调天数_int'] = result_df['回调天数']
            result_df = result_df.sort_values('回调天数_int')
            
            # 统计信息
            st.subheader("📊 筛选结果统计")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("符合条件", len(results))
            with col2:
                avg_callback = result_df['回调天数'].mean()
                st.metric("平均回调天数", f"{avg_callback:.1f}天")
            with col3:
                avg_lianban = result_df['连板天数'].mean()
                st.metric("平均连板天数", f"{avg_lianban:.1f}天")
            with col4:
                low_risk = len(result_df[result_df['风险等级'] == '低'])
                st.metric("低风险股票", low_risk)
            with col5:
                st.metric("扫描耗时", f"{elapsed_time:.1f}秒")
            
            # 显示结果表格
            st.subheader("📋 股票列表（按回调天数排序）")
            
            # 显示表格
            display_df = result_df[['股票代码', '股票名称', '连板天数', '连板日期', '连板最高价', '当前价格', '回调天数', '回调幅度', '风险等级']]
            st.dataframe(display_df, use_container_width=True, height=600)
            
            # 下载按钮
            csv = result_df.to_csv(index=False, encoding='utf-8-sig')
            st.download_button(
                label="📥 下载结果（CSV）",
                data=csv,
                file_name=f"lianban_callback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
            # 详细图表
            col1, col2 = st.columns(2)
            
            with col1:
                with st.expander("📈 回调幅度分布"):
                    # 将回调幅度转换为数字
                    callback_rates = result_df['回调幅度'].str.replace('%', '').astype(float)
                    fig = go.Figure(data=[go.Histogram(x=callback_rates, nbinsx=20)])
                    fig.update_layout(
                        title="回调幅度分布",
                        xaxis_title="回调幅度 (%)",
                        yaxis_title="股票数量"
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                with st.expander("📊 连板天数分布"):
                    lianban_counts = result_df['连板天数'].value_counts().sort_index()
                    fig = go.Figure(data=[go.Bar(x=lianban_counts.index, y=lianban_counts.values)])
                    fig.update_layout(
                        title="连板天数分布",
                        xaxis_title="连板天数",
                        yaxis_title="股票数量"
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            # 重点关注：刚好14-15天的股票
            st.subheader("⭐ 重点关注（回调14-15天）")
            focus_df = result_df[(result_df['回调天数'] >= 14) & (result_df['回调天数'] <= 15)]
            if len(focus_df) > 0:
                st.dataframe(focus_df[['股票代码', '股票名称', '连板天数', '连板日期', '当前价格', '回调幅度', '风险等级']], use_container_width=True)
            else:
                st.info("暂无刚好回调14-15天的股票")
            
        else:
            st.warning(f"⚠️ 未找到符合条件的股票（耗时{elapsed_time:.1f}秒），请增加扫描数量或调整数据天数")
            
    except Exception as e:
        st.error(f"❌ 扫描失败: {str(e)}")
        progress_bar.empty()
        status_text.empty()

# 页脚
st.markdown("---")
st.markdown("""
💡 **使用说明**: 
- **策略核心**：筛选出现连板后回调满14天的个股
- **数据天数**：建议100天以上，以捕捉更多连板机会
- **线程数**：推荐5-10个，线程越多速度越快⚡
- **重点关注**：刚好回调14-15天的股票，可能是最佳介入时机
- **风险提示**：连板股波动较大，注意风险控制

**策略逻辑**：
1. 寻找历史出现过连板（≥2个涨停）的股票
2. 从连板高点回调满14个交易日
3. 回调期间未再次涨停
4. 适合寻找超跌反弹和二次启动机会
""")