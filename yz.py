import streamlit as st
import pandas as pd
import akshare as ak
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
from datetime import datetime, timedelta, timezone
import plotly.express as px
from functools import lru_cache

# ── 页面基础配置 ──
st.set_page_config(
    page_title="游资核心标的追踪 - 全市场活跃版",
    layout="wide",
    page_icon="🚀",
    initial_sidebar_state="expanded"
)

# ── 密码验证 ──
def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    
    if not st.session_state["password_correct"]:
        st.markdown("### 🔐 访问控制")
        pwd = st.text_input("请输入访问令牌", type="password", key="pwd_input")
        if st.button("验证", use_container_width=True, type="primary"):
            target_pwd = st.secrets.get("ACCESS_PASSWORD", "888888")
            if pwd == target_pwd:
                st.session_state["password_correct"] = True
                st.rerun()
            else:
                st.error("令牌错误，请重试")
        st.stop()
    return True

# ── 北京时间工具 ──
@st.cache_data(ttl=60)
def get_beijing_time():
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

# ── 缓存板块列表 ──
@st.cache_data(ttl=3600)  # 缓存1小时
def get_all_sectors():
    return ak.stock_board_industry_name_em()['板块名称'].tolist()

# ── 单只股票处理逻辑（核心判定） ──
@lru_cache(maxsize=500)
def fetch_stock_hist(code):
    try:
        return ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq").tail(8)
    except:
        return pd.DataFrame()

def process_single_stock(code, name, current_price, turnover_rate, sector_info):
    hist = fetch_stock_hist(code)
    if hist.empty or len(hist) < 5:
        return None

    # 超过7连阳直接剔除
    if len(hist) == 8 and (hist['收盘'] > hist['开盘']).all():
        return None

    hist_7 = hist.tail(7)

    def check_consecutive_positive(data, days, max_gain_pct):
        if len(data) < days:
            return False, 0.0
        sub = data.tail(days)
        is_all_up = (sub['收盘'] > sub['开盘']).all()
        if not is_all_up:
            return False, 0.0
        gain = (sub.iloc[-1]['收盘'] - sub.iloc[0]['开盘']) / sub.iloc[0]['开盘'] * 100
        return gain <= max_gain_pct, round(gain, 2)

    # 三级强度判定
    for days, max_gain, label, emoji in [
        (7, 22.5, "7连阳", "🔥"),
        (6, 17.5, "6连阳", "⭐"),
        (5, 12.5, "5连阳", "⚡")
    ]:
        match, gain = check_consecutive_positive(hist_7, days, max_gain)
        if match:
            return {
                "代码": code,
                "名称": name,
                "现价": round(current_price, 2),
                "换手率": f"{turnover_rate:.2f}%",
                "强度": f"{emoji} {label} ≤{max_gain}%",
                "涨幅": f"{gain}%",
                "板块": sector_info,
                "扫描时间": get_beijing_time()
            }
    return None

# ── 主程序 ──
if check_password():
    # 标题 + 说明
    st.title("🚀 游资核心标的实时追踪")
    st.caption("全市场主板 · 换手率≥5% · 5-7连阳控涨幅 | 数据来源于akshare")

    # 侧边栏控制
    with st.sidebar:
        st.header("扫描控制")
        selected_scope = st.selectbox("查询范围", ["全市场扫描"] + get_all_sectors(), index=0)
        max_threads = st.slider("并发线程数", 5, 40, 20, step=5)
        min_turnover = st.slider("最低换手率(%)", 3.0, 15.0, 5.0, step=0.5)
        st.markdown("---")
        st.info("建议线程数根据你的网络和服务器性能调整，过高可能触发接口限流")

    # ── 扫描按钮 ──
    if st.button("🔥 开始全速扫描", type="primary", use_container_width=True):
        with st.spinner("正在获取活跃标的池..."):
            if selected_scope == "全市场扫描":
                df_pool = ak.stock_zh_a_spot_em()
            else:
                df_pool = ak.stock_board_industry_cons_em(symbol=selected_scope)

            # 核心过滤
            df_pool = df_pool[
                (~df_pool['名称'].str.contains("ST|退市", na=False)) &
                (~df_pool['代码'].str.startswith(("30", "688", "9"))) &
                (df_pool['换手率'] >= min_turnover)
            ].copy()

        stocks = df_pool[['代码', '名称', '最新价', '换手率']].values.tolist()
        total = len(stocks)

        if total == 0:
            st.error("当前筛选条件下无符合标的")
            st.stop()

        st.success(f"找到 {total:,} 只 换手率≥{min_turnover}% 的主板标的，开始判定连阳...")

        # 进度容器
        progress_bar = st.progress(0)
        status = st.empty()
        stats_container = st.empty()
        results = []
        captured_count = 0
        start = time.time()

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {
                executor.submit(process_single_stock, s[0], s[1], s[2], s[3], selected_scope): s
                for s in stocks
            }

            for i, future in enumerate(as_completed(futures)):
                res = future.result()
                if res:
                    results.append(res)
                    captured_count += 1
                    st.toast(f"捕获：{res['名称']} {res['强度']}", icon="✅")

                # 更新进度
                pct = (i + 1) / total
                progress_bar.progress(pct)
                
                # 每10条更新一次状态
                if (i + 1) % 10 == 0 or i == total - 1:
                    elapsed = time.time() - start
                    speed = (i + 1) / elapsed if elapsed > 0 else 0
                    status.markdown(
                        f"**扫描进度**：{i+1:,}/{total:,} | "
                        f"已捕获 **{captured_count}** 只 | "
                        f"速度 ≈ {speed:.1f} 条/秒 | "
                        f"耗时 {elapsed:.1f} 秒"
                    )
                    
                    # 实时统计面板
                    if results:
                        temp_df = pd.DataFrame(results)
                        stats_container.metric("当前捕获数量", captured_count)

        # ── 结果展示 ──
        duration = time.time() - start
        status.success(f"扫描完成！耗时 {duration:.1f} 秒，共捕获 {captured_count} 只核心标的")

        if results:
            df_result = pd.DataFrame(results)
            
            # 排序：强度优先（7>6>5） → 涨幅降序
            df_result['强度排序'] = df_result['强度'].map({
                "🔥 7连阳 ≤22.5%": 3,
                "⭐ 6连阳 ≤17.5%": 2,
                "⚡ 5连阳 ≤12.5%": 1
            }).fillna(0)
            df_result = df_result.sort_values(['强度排序', '涨幅'], ascending=[False, False]).drop(columns='强度排序')

            # 美化展示
            st.subheader(f"捕获结果（{len(df_result)} 只）")

            # 使用aggrid或st.dataframe + 样式
            st.dataframe(
                df_result.style.format({
                    '现价': '{:.2f}',
                    '涨幅': lambda x: f'<span style="color:{ "red" if float(x.rstrip("%")) > 0 else "green"}">{x}</span>'
                }, escape=False),
                use_container_width=True,
                column_config={
                    "代码": st.column_config.TextColumn("代码", width="small"),
                    "名称": st.column_config.TextColumn("名称", width="medium"),
                    "现价": st.column_config.NumberColumn("现价", format="%.2f"),
                    "换手率": st.column_config.TextColumn("换手率"),
                    "强度": st.column_config.TextColumn("强度", width="medium"),
                    "涨幅": st.column_config.TextColumn("涨幅"),
                    "板块": st.column_config.TextColumn("板块", width="medium"),
                }
            )

            # 导出
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name="核心标的")
            st.download_button(
                "📥 下载 Excel 结果",
                output.getvalue(),
                file_name=f"游资核心_{get_beijing_time()[:10]}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        else:
            st.warning("本次扫描未发现符合5-7连阳控涨幅的标的")

    st.divider()
    st.caption("优化版 | 2025 Powered by Streamlit + akshare | 仅供学习交流")
