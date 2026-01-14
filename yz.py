# -*- coding: utf-8 -*-
"""
游资突击扫描器 - 2025/2026主流短线思路框架（方案2版本）
避免使用全局变量，日期作为参数传递

功能：
1. 三重连阳累计涨幅限制
2. 多线程扫描（默认最大20，可配置）
3. 进度条
4. 可选板块过滤（使用akshare行业分类）
5. 游资席位 + 量价 + 形态综合打分

使用前请：
pip install akshare pandas tqdm pyyaml
"""

import akshare as ak
import pandas as pd
import yaml
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import argparse
from pathlib import Path
import warnings

warnings.filterwarnings("ignore")


# ===================== 配置读取 =====================
try:
    with open("config.yaml", encoding="utf-8") as f:
        CONFIG = yaml.safe_load(f)
except FileNotFoundError:
    print("未找到 config.yaml，请创建配置文件")
    exit(1)

MIN_SCORE = CONFIG.get("min_score", 65)
MAX_WORKERS = CONFIG.get("max_workers", 20)
USE_SECTOR_FILTER = CONFIG.get("sector_filter", {}).get("enable", False)
INCLUDE_SECTORS = CONFIG.get("sector_filter", {}).get("include", [])
EXCLUDE_SECTORS = CONFIG.get("sector_filter", {}).get("exclude", [])


# ===================== 游资席位池（示例，可自行维护） =====================
YOUZI_CORE = {  # 核心席位 - 高权重
    "机构专用", "中国银河证券绍兴", "华泰证券深圳益田路", "东方财富拉萨团结路",
    "中信证券上海溧阳路", "国泰君安南京太平南路", "中信证券上海分公司",
    # ... 继续补充你认为的核心席位
}

YOUZI_ATTENTION = {  # 关注级 - 中权重
    "国盛证券宁波解放南路", "华鑫证券上海分公司", "财通证券杭州五星路",
    # ...
}

ALL_YOUZI = YOUZI_CORE | YOUZI_ATTENTION


def get_youzi_level(buyers: list) -> str:
    """判断席位强度"""
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


# ===================== 三重连阳限制 =====================
def check_continuous_yang_limit(df: pd.DataFrame) -> tuple[bool, str]:
    """
    三重判定：
    7连阳累计涨幅 ≤ 25%
    6连阳累计涨幅 ≤ 20%
    5连阳累计涨幅 ≤ 15%
    """
    if len(df) < 5:
        return True, "数据不足"

    closes = df['收盘'].values[-10:]  # 取最近10天，够用了
    if len(closes) < 5:
        return True, "数据不足"

    pct_changes = closes[1:] / closes[:-1] - 1

    for days, limit in [(7, 0.25), (6, 0.20), (5, 0.15)]:
        if len(pct_changes) >= days - 1:
            recent_pcts = pct_changes[-(days-1):]
            if all(p > 0 for p in recent_pcts):  # 全阳
                cum_return = (1 + recent_pcts).prod() - 1
                if cum_return > limit:
                    return False, f"{days}连阳涨幅{cum_return:.2%} > {limit:.0%}"

    return True, "连阳限制通过"


# ===================== 主形态判断（示例框架，需自行完善） =====================
def is_youzi_pattern(df: pd.DataFrame, lhb_row, youzi_level: str) -> tuple[int, str]:
    score = 0
    reasons = []

    # 1. 席位强度（权重最高）
    if youzi_level == "核心×2+":
        score += 35
        reasons.append("核心席位×2+")
    elif youzi_level == "核心":
        score += 25
        reasons.append("核心席位")
    elif youzi_level in ["关注×2+", "关注"]:
        score += 15
        reasons.append("关注席位")

    # 2. 涨停/大涨 + 换手
    latest = df.iloc[-1]
    if abs(latest["涨跌幅"]) >= 9.5:
        score += 18
        reasons.append("涨停/接近涨停")
    elif latest["涨跌幅"] >= 7:
        score += 10
        reasons.append("大涨≥7%")

    if latest["换手率"] >= 25:
        score += 18
        reasons.append("换手≥25%")
    elif latest["换手率"] >= 15:
        score += 10
        reasons.append("换手≥15%")

    # 3. 连阳限制
    yang_ok, yang_reason = check_continuous_yang_limit(df)
    if not yang_ok:
        return 0, yang_reason
    else:
        score += 8
        reasons.append("连阳限制通过")

    # 4. 流通市值（越小越好）
    try:
        info = ak.stock_individual_info_em(df['代码'].iloc[0])
        circ_mv = float(info[info['item'] == '流通市值']['value'].iloc[0]) / 1e8  # 亿元
        if circ_mv < 50:
            score += 12
            reasons.append("小市值<50亿")
        elif circ_mv < 100:
            score += 6
            reasons.append("流通市值<100亿")
    except:
        pass

    return score, "；".join(reasons)


# ===================== 单票处理函数 =====================
def process_one_stock(code_name_tuple, scan_date: str) -> dict | None:
    code, name = code_name_tuple

    try:
        # 获取日K
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(datetime.now() - timedelta(days=150)).strftime("%Y%m%d"),
            end_date=scan_date,
            adjust="qfq"
        )

        if df.empty or len(df) < 30:
            return None

        # 获取当天龙虎榜席位（简化版，实际建议缓存全天龙虎榜）
        try:
            lhb = ak.stock_lhb_detail_em(scan_date, scan_date)
            lhb_this = lhb[lhb['代码'] == code]
            if lhb_this.empty:
                return None
            buyers = lhb_this['买入营业部名称'].str.strip().tolist()
        except:
            return None

        youzi_level = get_youzi_level(buyers)
        if youzi_level == "普通":
            return None

        score, reason = is_youzi_pattern(df, lhb_this.iloc[0] if not lhb_this.empty else None, youzi_level)

        if score >= MIN_SCORE:
            latest = df.iloc[-1]
            return {
                "代码": code,
                "名称": name,
                "得分": score,
                "理由": reason,
                "涨幅": f"{latest['涨跌幅']:.2f}%",
                "换手": f"{latest['换手率']:.2f}%",
                "席位": youzi_level,
                "最新收盘": f"{latest['收盘']:.2f}"
            }

        return None

    except Exception as e:
        # print(f"{code} 处理异常: {e}")
        return None


# ===================== 主程序 =====================
def main():
    parser = argparse.ArgumentParser(description="游资突击扫描器")
    parser.add_argument("--date", type=str, 
                        default=datetime.now().strftime("%Y%m%d"),
                        help="指定扫描日期 YYYYMMDD，默认当天")
    args = parser.parse_args()

    scan_date = args.date

    print(f"\n=== 游资突击扫描 {scan_date} 开始 ===\n")

    # 1. 获取当天龙虎榜
    try:
        lhb = ak.stock_lhb_detail_em(scan_date, scan_date)
        print(f"当日龙虎榜记录数：{len(lhb)}")
    except Exception as e:
        print("获取龙虎榜失败", e)
        return

    # 2. 提取所有上榜个股（去重）
    candidates = lhb[['代码', '名称']].drop_duplicates().values.tolist()
    print(f"上榜个股数量：{len(candidates)}")

    # 3. 可选：板块过滤
    if USE_SECTOR_FILTER and (INCLUDE_SECTORS or EXCLUDE_SECTORS):
        print("执行板块过滤...")
        filtered = []
        for code, name in tqdm(candidates, desc="板块过滤"):
            try:
                info = ak.stock_individual_info_em(code)
                industry = info[info['item'] == '行业']['value'].iloc[0]
                if INCLUDE_SECTORS and industry not in INCLUDE_SECTORS:
                    continue
                if any(ex in industry for ex in EXCLUDE_SECTORS):
                    continue
                filtered.append((code, name))
            except:
                continue
        candidates = filtered
        print(f"板块过滤后剩余：{len(candidates)}")

    # 4. 多线程扫描
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_code = {
            executor.submit(process_one_stock, item, scan_date): item
            for item in candidates
        }

        for future in tqdm(as_completed(future_to_code), total=len(candidates), desc="扫描进度"):
            result = future.result()
            if result:
                results.append(result)
                print(f"  发现！ {result['代码']} {result['名称']}  {result['得分']}分")

    # 5. 输出结果
    if not results:
        print("\n今天暂未发现符合条件的游资特征个股...\n")
        return

    df_result = pd.DataFrame(results).sort_values("得分", ascending=False)

    print("\n" + "="*60)
    print("           扫描日期:", scan_date, "   游资突击嫌疑股排行")
    print("="*60)
    print(df_result.to_string(index=False))
    print("="*60 + "\n")

    # 保存结果
    save_path = Path(f"result_{scan_date}.csv")
    df_result.to_csv(save_path, index=False, encoding="utf-8-sig")
    print(f"结果已保存至：{save_path}")


if __name__ == "__main__":
    main()