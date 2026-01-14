# yz.py
# 游资突击扫描器 - 简易版（适合本地与 Streamlit Cloud）
# 最后更新日期：2026-01

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
    from tqdm import tqdm
    import yaml
    from pathlib import Path

    # ==================== 配置区 ====================
    CONFIG = {
        "min_score": 65,
        "max_workers": 18,           # 建议不要超过20，避免被限流
        "use_sector_filter": False,
        "include_sectors": [],
        "exclude_sectors": ["ST", "*退"],
    }

    # 核心游资席位（示例，可自行维护/扩展）
    YOUZI_CORE = {
        "机构专用", "中国银河证券绍兴", "华泰证券深圳益田路", "东方财富拉萨团结路",
        "中信证券上海溧阳路", "国泰君安南京太平南路", "中信证券上海分公司",
    }

    YOUZI_ATTENTION = {
        "国盛证券宁波解放南路", "华鑫证券上海分公司", "财通证券杭州五星路",
    }

    ALL_YOUZI = YOUZI_CORE | YOUZI_ATTENTION

    # ==================== 辅助函数 ====================
    def get_youzi_level(buyers):
        core_count = sum(1 for x in buyers if x in YOUZI_CORE)
        att_count = sum(1 for x in buyers if x in YOUZI_ATTENTION)
        if core_count >= 2:
            return "核心×2+"
        if core_count >= 1:
            return "核心"
        if att_count >= 2:
            return "关注×2+"
        if att_count >= 1:
            return "关注"
        return "普通"

    def check_continuous_yang_limit(df):
        if len(df) < 5:
            return True, "数据不足"
        closes = df['收盘'].values[-10:]
        if len(closes) < 5:
            return True, "数据不足"
        pct = closes[1:] / closes[:-1] - 1
        for days, limit in [(7, 0.25), (6, 0.20), (5, 0.15)]:
            if len(pct) >= days-1:
                recent = pct[-(days-1):]
                if all(x > 0 for x in recent):
                    cum = (1 + recent).prod() - 1
                    if cum > limit:
                        return False, f"{days}连阳超限 {cum:.2%}"
        return True, "连阳合格"

    # ==================== 单票核心判断（可大幅扩展） ====================
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
        # 连阳限制
        ok, msg = check_continuous_yang_limit(df)
        if not ok:
            return 0, msg
        score += 8
        reasons.append("连阳合格")

        return score, "；".join(reasons)

    # ==================== 处理单只股票 ====================
    @st.cache_data(ttl=1800)  # 缓存30分钟，避免重复请求
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

    def process_stock(item, scan_date):
        code, name = item
        try:
            df = fetch_kline(code, scan_date)
            if df.empty or len(df) < 30:
                return None

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
        except Exception as e:
            pass  # 静默错误，单个票出错不影响整体
        return None

    # ==================== Streamlit 主界面 ====================
    def main():
        st.set_page_config(page_title="游资扫描", layout="wide")
        st.title("游资突击扫描器（简易版）")
        st.caption("数据来源于akshare，仅供学习交流，不构成投资建议")

        scan_date = st.date_input(
            "选择扫描日期",
            value=datetime.now().date(),
            max_value=datetime.now().date()
        ).strftime("%Y%m%d")

        if st.button("开始扫描", type="primary"):
            with st.spinner(f"正在扫描 {scan_date} 的龙虎榜..."):
                try:
                    lhb = ak.stock_lhb_detail_em(scan_date, scan_date)
                    if lhb.empty:
                        st.warning("当天无龙虎榜数据")
                        return

                    candidates = lhb[['代码', '名称']].drop_duplicates().values.tolist()
                    st.info(f"上榜个股数量：{len(candidates)}")

                    results = []
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
                        futures = [executor.submit(process_stock, item, scan_date) for item in candidates]
                        total = len(futures)

                        for i, future in enumerate(as_completed(futures)):
                            result = future.result()
                            if result:
                                results.append(result)
                                st.success(f"发现！ {result['代码']} {result['名称']}  {result['得分']}分")
                            progress = (i + 1) / total
                            progress_bar.progress(progress)
                            status_text.text(f"进度：{i+1}/{total}  ({progress:.1%})")

                    if results:
                        df = pd.DataFrame(results).sort_values("得分", ascending=False)
                        st.subheader("扫描结果")
                        st.dataframe(df, use_container_width=True)
                        
                        csv = df.to_csv(index=False).encode('utf-8-sig')
                        st.download_button(
                            "下载结果 (CSV)",
                            csv,
                            f"游资扫描_{scan_date}.csv",
                            "text/csv"
                        )
                    else:
                        st.info("今天暂未发现符合条件的游资特征个股")

                except Exception as e:
                    st.error("扫描过程中发生错误")
                    st.code(str(e))

    if __name__ == "__main__":
        main()

except ImportError as e:
    print("依赖导入失败，请检查 requirements.txt 是否包含以下包：")
    print("streamlit  akshare  pandas  pyyaml")
    print("错误信息：", e)
    sys.exit(1)
except Exception as e:
    print("程序启动异常：")
    print(traceback.format_exc())
    sys.exit(1)