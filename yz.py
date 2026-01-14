# yp.py
# 游资突击扫描器 - Streamlit 版
# 包含：板块多选 + 线程数调节 + 三重连阳判定逻辑
# 最后更新：2026-01

import sys
import traceback
import warnings
warnings.filterwarnings("ignore")

try:
    import streamlit as st
    import akshare as ak
    import pandas as pd
    from datetime import datetime, timedelta
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path

    # ==================== 配置区 ====================
    CONFIG = {
        "min_score": 65,
        "default_workers": 12,
        "max_possible_workers": 24,
    }

    # 核心游资席位（示例，可自行扩展/更新）
    YOUZI_CORE = {
        "机构专用", "中国银河证券绍兴", "华泰证券深圳益田路", "东方财富拉萨团结路",
        "中信证券上海溧阳路", "国泰君安南京太平南路", "中信证券上海分公司",
    }

    YOUZI_ATTENTION = {
        "国盛证券宁波解放南路", "华鑫证券上海分公司", "财通证券杭州五星路",
    }

    ALL_YOUZI = YOUZI_CORE | YOUZI_ATTENTION

    # ==================== 三重连阳判定 ====================
    def check_three_level_continuous_yang(df: pd.DataFrame) -> tuple[bool, str]:
        """
        三重连阳涨幅限制判定
        规则：
        - 最近7天全是阳线 → 累计涨幅 ≤ 25%
        - 最近6天全是阳线 → 累计涨幅 ≤ 20%
        - 最近5天全是阳线 → 累计涨幅 ≤ 15%
        """
        if len(df) < 5:
            return True, "数据不足5天"

        # 取最近10天数据
        recent = df.tail(10).copy()
        if len(recent) < 5:
            return True, "数据不足"

        # 计算每日涨幅倍数 (1 + 涨幅)
        recent['pct_multiplier'] = recent['涨跌幅'] / 100 + 1

        # 从旧到新排序（方便切片）
        recent = recent.sort_index(ascending=True)
        multipliers = recent['pct_multiplier'].values

        for length, limit in [(7, 0.25), (6, 0.20), (5, 0.15)]:
            if len(multipliers) >= length:
                segment = multipliers[-length:]  # 最后length天
                # 检查是否连续阳线（严格大于1.0）
                if all(x > 1.0 for x in segment):
                    cum_return = segment.prod() - 1
                    if cum_return > limit:
                        return False, f"{length}连阳累计涨幅 {cum_return:.2%} > {limit:.0%}限制"

        return True, "三重连阳判定通过"

    # ==================== 辅助函数 ====================
    def get_youzi_level(buyers):
        core = sum(1 for x in buyers if x in YOUZI_CORE)
        att = sum(1 for x in buyers if x in YOUZI_ATTENTION)
        if core >= 2: return "核心×2+"
        if core >= 1: return "核心"
        if att >= 2: return "关注×2+"
        if att >= 1: return "关注"
        return "普通"

    def is_youzi_pattern(df, youzi_level):
        score = 0
        reasons = []

        # 席位权重
        if youzi_level == "核心×2+": score += 35; reasons.append("核心×2+")
        elif youzi_level == "核心":   score += 25; reasons.append("核心席位")
        elif "关注" in youzi_level:   score += 15; reasons.append("关注席位")

        latest = df.iloc[-1]
        # 涨幅
        if latest["涨跌幅"] >= 9.5:   score += 20; reasons.append("涨停")
        elif latest["涨跌幅"] >= 7:    score += 12; reasons.append("大涨≥7%")
        # 换手
        if latest["换手率"] >= 25:     score += 18; reasons.append("换手≥25%")
        elif latest["换手率"] >= 15:   score += 10; reasons.append("换手≥15%")

        return score, "；".join(reasons)

    # ==================== 数据获取（带缓存） ====================
    @st.cache_data(ttl=1800, show_spinner=False)
    def fetch_kline(code, end_date):
        try:
            return ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=(datetime.now() - timedelta(days=150)).strftime("%Y%m%d"),
                end_date=end_date,
                adjust="qfq"
            )
        except:
            return pd.DataFrame()

    @st.cache_data(ttl=3600, show_spinner=False)
    def get_all_industries():
        try:
            df = ak.stock_board_industry_name_ths()
            return sorted(df['industry'].unique().tolist())
        except:
            return ["获取行业列表失败"]

    # ==================== 单票处理 ====================
    def process_stock(item, scan_date, selected_industries):
        code, name = item
        
        # 板块过滤
        if selected_industries:
            try:
                info = ak.stock_individual_info_em(code)
                industry = info[info['item'] == '行业']['value'].values[0]
                if industry not in selected_industries:
                    return None
            except:
                return None

        try:
            df = fetch_kline(code, scan_date)
            if df.empty or len(df) < 30:
                return None

            # 三重连阳强过滤（放在前面，避免浪费资源）
            pass_yang, yang_msg = check_three_level_continuous_yang(df)
            if not pass_yang:
                return None   # 可改为记录日志或返回调试信息

            lhb = ak.stock_lhb_detail_em(scan_date, scan_date)
            lhb_this = lhb[lhb['代码'] == code]
            if lhb_this.empty:
                return None

            buyers = lhb_this['买入营业部名称'].str.strip().tolist()
            level = get_youzi_level(buyers)
            if level == "普通":
                return None

            score, reason = is_youzi_pattern(df, level)
            if score >= CONFIG["min_score"]:
                latest = df.iloc[-1]
                return {
                    "代码": code,
                    "名称": name,
                    "得分": score,
                    "理由": reason,
                    "涨幅": f"{latest['涨跌幅']:.2f}%",
                    "换手": f"{latest['换手率']:.2f}%",
                    "席位": level,
                    "收盘价": f"{latest['收盘']:.2f}"
                }
        except:
            pass
        return None

    # ==================== Streamlit 主界面 ====================
    def main():
        st.set_page_config(page_title="游资扫描器", layout="wide")
        st.title("游资突击扫描器（含三重连阳过滤）")
        st.caption("数据来源于 akshare，仅供学习交流，不构成投资建议")

        # ------------------- 侧边栏 -------------------
        with st.sidebar:
            st.header("扫描参数")

            scan_date = st.date_input(
                "选择日期",
                value=datetime.now().date(),
                max_value=datetime.now().date()
            ).strftime("%Y%m%d")

            num_workers = st.slider(
                "并发线程数",
                min_value=4,
                max_value=CONFIG["max_possible_workers"],
                value=CONFIG["default_workers"],
                step=2,
                help="建议12~18，过高容易被接口限流"
            )

            st.subheader("板块过滤（可选）")
            all_industries = get_all_industries()
            selected_industries = st.multiselect(
                "只显示以下行业（留空=不过滤）",
                options=all_industries,
                default=[],
                help="可多选，按住 Ctrl 或 Shift"
            )

        # ------------------- 主界面 -------------------
        if st.button("开始扫描", type="primary", use_container_width=True):
            with st.spinner(f"正在扫描 {scan_date} 的龙虎榜..."):
                try:
                    lhb = ak.stock_lhb_detail_em(scan_date, scan_date)
                    if lhb.empty:
                        st.warning("当天无龙虎榜数据")
                        return

                    candidates = lhb[['代码', '名称']].drop_duplicates().values.tolist()
                    st.info(f"上榜个股数量：{len(candidates)}   |   线程：{num_workers}   |   过滤行业：{len(selected_industries)}个")

                    results = []
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    with ThreadPoolExecutor(max_workers=num_workers) as executor:
                        futures = [
                            executor.submit(process_stock, item, scan_date, selected_industries)
                            for item in candidates
                        ]
                        total = len(futures)

                        for i, future in enumerate(as_completed(futures)):
                            result = future.result()
                            if result:
                                results.append(result)
                                st.success(f"发现：{result['代码']} {result['名称']}  {result['得分']}分")
                            progress = (i + 1) / total
                            progress_bar.progress(progress)
                            status_text.text(f"进度：{i+1}/{total}  ({progress:.1%})")

                    if results:
                        df = pd.DataFrame(results).sort_values("得分", ascending=False)
                        st.subheader(f"符合条件结果（共 {len(df)} 只）")
                        st.dataframe(
                            df[['代码', '名称', '得分', '涨幅', '换手', '席位', '理由']],
                            use_container_width=True,
                            hide_index=True
                        )

                        csv = df.to_csv(index=False, encoding='utf-8-sig').encode('utf-8-sig')
                        st.download_button(
                            label="下载完整结果 (CSV)",
                            data=csv,
                            file_name=f"游资扫描_{scan_date}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.info("今天暂未发现符合条件的游资特征个股（或全部被三重连阳过滤）")

                except Exception as e:
                    st.error("扫描过程中发生错误")
                    with st.expander("详细错误信息"):
                        st.code(str(e))
                        st.code(traceback.format_exc())

    if __name__ == "__main__":
        main()

except ImportError as e:
    print("依赖导入失败，请检查是否安装：streamlit, akshare, pandas")
    print("错误：", e)
    sys.exit(1)
except Exception as e:
    print("程序启动异常：")
    print(traceback.format_exc())
    sys.exit(1)