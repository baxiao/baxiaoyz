import streamlit as st
import pandas as pd
import akshare as ak
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
from datetime import datetime, timedelta, timezone

# --- 1. 配置与安全 ---
st.set_page_config(page_title="游资核心标的追踪-全市场活跃版", layout="wide")

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        pwd = st.text_input("请输入访问令牌", type="password")
        if st.button("验证登录"):
            target_pwd = st.secrets.get("ACCESS_PASSWORD", "888888")
            if pwd == target_pwd:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("令牌错误")
        return False
    return True

# --- 2. 核心判定逻辑 ---
def get_beijing_time():
    """获取北京时间"""
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

def process_single_stock(code, name, current_price, turnover_rate, sector_info):
    try:
        # 获取判定所需的天数（8天用于判定是否超过7连阳）
        hist = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq").tail(8)
        if hist is None or len(hist) < 5: return None
        
        # --- 封顶剔除逻辑：超过7连阳的剔除 ---
        if len(hist) == 8:
            is_8_positive = (hist['收盘'] > hist['开盘']).all()
            if is_8_positive:
                return None
        
        hist_7 = hist.tail(7)
        
        def check_logic(data, days, max_gain):
            sub_data = data.tail(days)
            if len(sub_data) < days: return False, 0
            is_positive = (sub_data['收盘'] > sub_data['开盘']).all()
            total_gain = (sub_data.iloc[-1]['收盘'] - sub_data.iloc[0]['开盘']) / sub_data.iloc[0]['开盘'] * 100
            return is_positive and total_gain <= max_gain, round(total_gain, 2)
        
        # --- 三重判定逻辑 ---
        match7, gain7 = check_logic(hist_7, 7, 22.5)
        if match7:
            res_type, res_gain = "🔥 7连阳/≤22.5%", gain7
        else:
            match6, gain6 = check_logic(hist_7, 6, 17.5)
            if match6:
                res_type, res_gain = "⭐ 6连阳/≤17.5%", gain6
            else:
                match5, gain5 = check_logic(hist_7, 5, 12.5)
                if match5:
                    res_type, res_gain = "⚡ 5连阳/≤12.5%", gain5
                else:
                    return None
        
        return {
            "代码": code,
            "名称": name,
            "当前价格": current_price,
            "今日换手率": f"{turnover_rate}%",
            "判定强度": res_type,
            "累计涨幅": f"{res_gain}%",
            "所属板块": sector_info,
            "查询时间(北京)": get_beijing_time()
        }
    except:
        return None

# --- 3. 页面渲染 ---
if check_password():
    st.title("🚀 游资核心追踪 (全市场活跃主板版)")
    with st.spinner("同步实时数据..."):
        all_sectors = ak.stock_board_industry_name_em()['板块名称'].tolist()
    selected_sector = st.sidebar.selectbox("选择查询范围", ["全市场扫描"] + all_sectors)
    thread_count = st.sidebar.slider("并发线程数", 1, 30, 20)
    
    if st.button("开启全速扫描"):
        countdown = st.empty()
        for i in range(3, 0, -1):
            countdown.metric("极速引擎正在预热...", f"{i} 秒")
            time.sleep(1)
        countdown.empty()
        with st.spinner("正在筛选活跃主板标的池..."):
            if selected_sector == "全市场扫描":
                df_pool = ak.stock_zh_a_spot_em()
            else:
                df_pool = ak.stock_board_industry_cons_em(symbol=selected_sector)
            # --- 核心筛选与剔除 ---
            # 1. 剔除 ST/退市/非主板
            df_pool = df_pool[~df_pool['名称'].str.contains("ST|退市")]
            df_pool = df_pool[~df_pool['代码'].str.startswith(("30", "688", "9"))]
            
            # 2. 新增：换手率大于或等于 5% (AkShare字段名为'换手率')
            df_pool = df_pool[df_pool['换手率'] >= 5.0]
        stocks_to_check = df_pool[['代码', '名称', '最新价', '换手率']].values.tolist()
        total_stocks = len(stocks_to_check)
        
        st.write(f"📊 主板活跃标的(换手率≥5%)：{total_stocks} 只")
        
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        results = []
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=thread_count) as executor:
            # 传入参数增加换手率 s[3]
            future_to_stock = {executor.submit(process_single_stock, s[0], s[1], s[2], s[3], selected_sector): s for s in stocks_to_check}
            
            for i, future in enumerate(as_completed(future_to_stock)):
                res = future.result()
                if res:
                    results.append(res)
                    st.toast(f"✅ 捕获高活跃股: {res['名称']}")
                
                curr_p = float(min((i + 1) / total_stocks, 1.0))
                progress_bar.progress(curr_p)
                if (i + 1) % 20 == 0:
                    status_text.text(f"🚀 扫描中... 进度: {i+1}/{total_stocks}")
        duration = round(time.time() - start_time, 2)
        status_text.success(f"✨ 扫描完成！耗时 {duration} 秒")
        if results:
            res_df = pd.DataFrame(results)
            # 重新排列列顺序，换手率放在价格后
            cols = ["代码", "名称", "当前价格", "今日换手率", "判定强度", "累计涨幅", "所属板块", "查询时间(北京)"]
            res_df = res_df[cols]
            
            st.dataframe(res_df, use_container_width=True)
            output = io.BytesIO()
            res_df.to_excel(output, index=False)
            st.download_button(
                label="📥 导出活跃结果 (Excel)",
                data=output.getvalue(),
                file_name=f"活跃精选_{get_beijing_time()[:10]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("暂无符合条件的活跃标的。")
    st.divider()
    st.caption("Master Copy | 全市场活跃主板 | 换手率≥5% | 5-7连阳控幅")
