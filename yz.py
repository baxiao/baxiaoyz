import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ====================== 核心参数 ======================
# 连续阳线最少要求几天
CONSECUTIVE_YANG = 3
# 成交量放大倍数（当天量 / 前N日均量）
VOL_MULTIPLIER = 2.0
VOL_PERIOD = 5
# 允许涨停误差（有些软件有价格限制导致不是严格10%）
ZT_THRESHOLD = 0.099
# 筛选最近多少天内出现过涨停
RECENT_DAYS = 10

def is_up_limit(prev_close, today_close):
    """判断是否涨停（主板10%）"""
    if prev_close <= 0:
        return False
    pct = (today_close - prev_close) / prev_close
    return pct >= ZT_THRESHOLD

def has_gap_up(df):
    """检查最近是否有向上跳空缺口"""
    for i in range(1, len(df)):
        if df['low'].iloc[i] > df['high'].iloc[i-1]:
            return True
    return False

def get_main_board_stocks():
    """获取沪深主板股票列表（剔除创业板、科创板、北交所、ST）"""
    stock_list = ak.stock_zh_a_spot_em()
    
    # 剔除ST/*ST/退市
    stock_list = stock_list[~stock_list['名称'].str.contains("ST|退市", na=False)]
    
    # 代码前缀过滤（保留主板 + 中小板）
    # 主板：60/000/001
    # 中小板已并入深主板：002/003
    condition = (
        (stock_list['代码'].str.startswith(('60', '000', '001', '002', '003'))) &
        (~stock_list['代码'].str.startswith(('30', '688', '8', '43')))  # 排除创业、科创、北交
    )
    
    df_main = stock_list[condition].copy()
    df_main['代码'] = df_main['代码'].astype(str).str.zfill(6)  # 补0成6位
    return df_main['代码'].tolist()

def screen_stock(code):
    """对单只股票进行四个特征判断"""
    try:
        # 获取最近15~20天日K线（够用）
        df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                start_date=(datetime.now() - timedelta(days=30)).strftime("%Y%m%d"),  # 往前30天确保数据
                                end_date=datetime.now().strftime("%Y%m%d"),
                                adjust="qfq")
        
        if len(df) < 10:
            return False, None
        
        df = df.tail(15).reset_index(drop=True)  # 取最近部分
        df['close'] = pd.to_numeric(df['收盘'], errors='coerce')
        df['open'] = pd.to_numeric(df['开盘'], errors='coerce')
        df['high'] = pd.to_numeric(df['最高'], errors='coerce')
        df['low'] = pd.to_numeric(df['最低'], errors='coerce')
        df['volume'] = pd.to_numeric(df['成交量'], errors='coerce')
        
        df = df.dropna(subset=['close','open','high','low','volume'])
        if len(df) < VOL_PERIOD + 2:
            return False, None
        
        # ① 最近10天内出现过涨停
        has_zt = False
        zt_date = None
        for i in range(1, min(RECENT_DAYS+1, len(df))):
            if is_up_limit(df['close'].iloc[i-1], df['close'].iloc[i]):
                has_zt = True
                zt_date = df['日期'].iloc[i]
                break
        
        if not has_zt:
            return False, None
        
        # ② 最近连续阳线（最后N天）
        yang_count = 0
        for i in range(1, CONSECUTIVE_YANG + 1):
            if i >= len(df):
                break
            if df['close'].iloc[-i] > df['open'].iloc[-i]:
                yang_count += 1
            else:
                break
        if yang_count < CONSECUTIVE_YANG:
            return False, None
        
        # ③ 最近有向上缺口
        if not has_gap_up(df.tail(8)):
            return False, None
        
        # ④ 最近一天成交量放大
        recent_vol = df['volume'].iloc[-1]
        prev_vol_mean = df['volume'].iloc[-1-VOL_PERIOD:-1].mean()
        if recent_vol < prev_vol_mean * VOL_MULTIPLIER:
            return False, None
        
        # 全部满足！
        return True, {
            '代码': code,
            '名称': ak.stock_individual_info_em(symbol=code)['value'].iloc[0] if 'value' in ak.stock_individual_info_em(symbol=code) else "未知",
            '涨停日期': zt_date,
            '最近阳线数': yang_count,
            '最新收盘': round(df['close'].iloc[-1], 2),
            '最新成交量': int(recent_vol),
            '前均量': round(prev_vol_mean, 0)
        }
    
    except Exception as e:
        # print(f"{code} 获取失败: {e}")
        return False, None

if __name__ == "__main__":
    print("正在获取符合条件的主板股票列表...")
    codes = get_main_board_stocks()
    print(f"共获取 {len(codes)} 只主板非ST股票")

    result_list = []
    print("开始多线程扫描（加速版）...")

    # 多线程加速：最大线程数设为10~20，避免AKShare接口限流
    MAX_THREADS = 15
    lock = threading.Lock()  # 线程安全锁，用于结果追加

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        future_to_code = {executor.submit(screen_stock, code): code for code in codes}
        for future in tqdm(as_completed(future_to_code), total=len(codes)):
            match, info = future.result()
            if match:
                with lock:
                    result_list.append(info)
                    print(f"【命中】 {info['代码']} {info['名称']}")

    if result_list:
        df_result = pd.DataFrame(result_list)
        df_result.to_csv("涨停前四信号股票.csv", index=False, encoding="utf_8_sig")
        print("\n筛选完成！结果已保存到 涨停前四信号股票.csv")
        print(df_result)
    else:
        print("\n今天没有发现同时满足4个特征的股票")
