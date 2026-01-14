# -*- coding: utf-8 -*-
"""
大涨前4信号同时出现扫描器
核心特征：
1. 近期出现涨停（或接近涨停 ≥9.5%）
2. 连续阳线（至少3~5根连续阳线）
3. 存在向上跳空缺口（近10~20天内）
4. 成交量明显放大（最近一天量比>3 或 近3天平均换手>前10天3倍以上）

2025-2026短线主流思路简化版
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore')


def has_recent_limit_up(df: pd.DataFrame, days=20, threshold=9.5) -> bool:
    """近days天内是否有涨停或接近涨停"""
    recent = df.tail(days)
    return (recent['涨跌幅'] >= threshold).any()


def has_continuous_positive(df: pd.DataFrame, min_days=3) -> tuple[bool, int]:
    """检查是否有连续阳线，最多统计连续几根"""
    df = df.copy()
    df['is_positive'] = df['涨跌幅'] > 0
    df['group'] = (df['is_positive'] != df['is_positive'].shift()).cumsum()
    consecutive = df[df['is_positive']].groupby('group').size()
    max_consec = consecutive.max() if not consecutive.empty else 0
    return max_consec >= min_days, max_consec


def has_gap_up(df: pd.DataFrame, lookback=30) -> bool:
    """检查近lookback天是否存在向上跳空缺口
    条件：当天最低价 > 前一天最高价
    """
    recent = df.tail(lookback)
    if len(recent) < 2:
        return False
    gap_up = (recent['最低'] > recent['最高'].shift(1))
    return gap_up.any()


def has_volume_explosion(df: pd.DataFrame, lookback=20, vol_ratio_threshold=3.0) -> bool:
    """
    成交量放大判断（两种方式任一满足即可）
    1. 最新一天量比 > vol_ratio_threshold
    2. 最近3天平均成交量 > 前10天平均成交量的 vol_ratio_threshold 倍
    """
    if len(df) < lookback + 3:
        return False

    latest_vol = df['成交量'].iloc[-1]
    recent_3 = df['成交量'].tail(3).mean()
    earlier_10 = df['成交量'].iloc[-13:-3].mean()  # 前10天（不含最近3天）

    # 方式1：当天量比（粗略用成交量/前一天）
    if len(df) >= 2:
        prev_vol = df['成交量'].iloc[-2]
        if prev_vol > 0 and latest_vol / prev_vol >= vol_ratio_threshold:
            return True

    # 方式2：最近3天 vs 前10天
    if earlier_10 > 0 and recent_3 / earlier_10 >= vol_ratio_threshold:
        return True

    return False


def scan_big_rise_pattern(code: str, name: str, end_date: str = None):
    """单只股票扫描4信号是否同时满足"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(datetime.now() - timedelta(days=180)).strftime("%Y%m%d"),
            end_date=end_date,
            adjust="qfq"
        )

        if df.empty or len(df) < 30:
            return None

        signals = {}

        # 1. 近期涨停
        signals['涨停'] = has_recent_limit_up(df, days=20)

        # 2. 连续阳线（至少3根，记录最长连续）
        has_consec, consec_count = has_continuous_positive(df, min_days=3)
        signals['连续阳线'] = has_consec
        signals['连续阳线根数'] = consec_count

        # 3. 向上跳空缺口
        signals['向上缺口'] = has_gap_up(df, lookback=30)

        # 4. 成交量放大
        signals['放巨量'] = has_volume_explosion(df, vol_ratio_threshold=3.0)

        # 判断是否4信号齐全
        all_true = all(signals.values())

        if all_true:
            latest = df.iloc[-1]
            return {
                "代码": code,
                "名称": name,
                "最新收盘": round(latest['收盘'], 2),
                "最新涨幅": f"{latest['涨跌幅']:.2f}%",
                "最新换手": f"{latest['换手率']:.2f}%",
                "连续阳线": f"{consec_count}根",
                "信号日期": latest['日期'],
                "完整信号": "✓✓✓✓ 4信号齐全"
            }

        return None

    except Exception as e:
        # print(f"{code} 处理异常: {e}")
        return None


def main():
    # 示例：扫描当天龙虎榜个股（可改成自选股列表或全市场）
    print("正在获取今日龙虎榜...")
    try:
        today = datetime.now().strftime("%Y%m%d")
        lhb = ak.stock_lhb_detail_em(today, today)
        if lhb.empty:
            print("今日暂无龙虎榜数据")
            return

        candidates = lhb[['代码', '名称']].drop_duplicates()

        print(f"发现 {len(candidates)} 只上榜个股，开始扫描4信号...")

        results = []
        for _, row in candidates.iterrows():
            result = scan_big_rise_pattern(row['代码'], row['名称'])
            if result:
                results.append(result)
                print(f"发现4信号齐全！ {row['代码']} {row['名称']}")

        if results:
            df_result = pd.DataFrame(results)
            print("\n" + "="*60)
            print("今日4大信号齐全个股（大涨前兆概率较高）")
            print("="*60)
            print(df_result.to_string(index=False))
            df_result.to_csv(f"4信号齐全_{today}.csv", index=False, encoding='utf-8-sig')
            print(f"\n结果已保存至：4信号齐全_{today}.csv")
        else:
            print("\n今日暂未发现4信号同时齐全的个股")

    except Exception as e:
        print("主程序异常:", e)


if __name__ == "__main__":
    main()