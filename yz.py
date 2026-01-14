# stock_scanner_multi_thread.py
# 适合A股的简易多条件扫股框架（2025-2026版参考写法）
# 依赖: akshare, pandas, tqdm, numpy
# 建议 python 3.9 ~ 3.11
# pip install akshare pandas tqdm numpy

import akshare as ak
import pandas as pd
import numpy as np
from tqdm import tqdm
import threading
import queue
import time
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings("ignore")

# ================== 可调参数区 ==================
MAX_WORKERS = 12              # 线程数建议 8~16，根据你的电脑性能
RECENT_DAYS = 120             # 取多少天历史数据（一般够用）
MIN_PRICE = 3.0               # 最低价过滤（太便宜容易假突破）
MAX_PRICE = 120.0             # 最高价过滤（太贵散户难参与）
VOLUME_RATIO_THRESHOLD = 2.5  # 放量倍数阈值（建议2.0~4.0）
CONSECUTIVE_YANG = 4          # 连续阳线最少要求
GAP_THRESHOLD = 0.015         # 跳空缺口最小幅度 1.5%
NEAR_LIMIT_UP_PCT = 8.5       # 接近涨停判定（小于多少算接近） 创业板/科创板要调高

# 结果保存路径
RESULT_FILE = f"scan_result_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
# ===============================================

result_queue = queue.Queue()
lock = threading.Lock()


def is_yang_line(row):
    """判断是否阳线（收盘>开盘） 考虑很小实体也可接受"""
    return row["close"] > row["open"] and (row["close"] - row["open"]) / row["open"] > 0.002


def is_big_yang(row, prev_close):
    """是否大阳线（相对前收盘）"""
    change = (row["close"] - prev_close) / prev_close
    return change >= 0.06  # ≥6% 可调


def is_near_limit_up(df):
    """接近涨停 or 涨停"""
    last = df.iloc[-1]
    change = (last["close"] - last["pre_close"]) / last["pre_close"] * 100
    
    # 普通股10%，科创/创业20%，这里粗略处理
    if change >= 9.8:
        return True, "涨停"
    elif change >= NEAR_LIMIT_UP_PCT:
        return True, f"接近涨停({change:.2f}%)"
    return False, ""


def has_gap_up(df):
    """检测最近5天是否有向上跳空缺口"""
    for i in range(1, min(6, len(df))):
        today = df.iloc[-i]
        yesterday = df.iloc[-i-1]
        if today["open"] > yesterday["high"] * (1 + GAP_THRESHOLD):
            return True
    return False


def has_continuous_yang(df, n=CONSECUTIVE_YANG):
    """最近n天是否连续阳线"""
    if len(df) < n:
        return False
    recent = df.iloc[-n:]
    return all(is_yang_line(row) for _, row in recent.iterrows())


def has_volume_surge(df, ratio_th=VOLUME_RATIO_THRESHOLD):
    """最近3天是否有明显放量（相对20日均量）"""
    if len(df) < 30:
        return False
        
    vol_ma20 = df["volume"].rolling(20).mean()
    recent_vol = df["volume"].iloc[-3:]
    recent_ma = vol_ma20.iloc[-3:]
    
    # 至少有一天放量达到阈值
    return (recent_vol / recent_ma >= ratio_th).any()


def scan_one_stock(code, name, pbar):
    try:
        # 尝试获取日线数据
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=(datetime.now() - timedelta(days=RECENT_DAYS*1.5)).strftime("%Y%m%d"),
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="qfq"
        )
        
        if df.empty or len(df) < 30:
            return
        
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "昨收": "pre_close"   # 新版本akshare可能会变，注意适配
        })
        
        if "pre_close" not in df.columns:
            df["pre_close"] = df["close"].shift(1)
            df = df.dropna(subset=["pre_close"])
        
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")
        
        last_close = df["close"].iloc[-1]
        if not (MIN_PRICE <= last_close <= MAX_PRICE):
            return
            
        signals = []
        
        # ① 涨停 / 大阳突破
        is_limit, msg = is_near_limit_up(df)
        if is_limit:
            signals.append(f"★{msg}")
        
        # 大阳突破关键位置（这里简单用突破前20日最高）
        if len(df) >= 20:
            prev_high20 = df["high"].iloc[-21:-1].max()
            if df["close"].iloc[-1] > prev_high20 * 1.005 and is_big_yang(df.iloc[-1], df["pre_close"].iloc[-1]):
                signals.append("大阳突破20日高点")
        
        # ② 连续阳线
        if has_continuous_yang(df):
            signals.append(f"连续阳×{CONSECUTIVE_YANG}+")
        
        # ③ 向上跳空缺口
        if has_gap_up(df):
            signals.append("向上跳空缺口")
        
        # ④ 放巨量
        if has_volume_surge(df):
            signals.append(f"放量>{VOLUME_RATIO_THRESHOLD:.1f}倍")
        
        if signals:
            signal_str = " | ".join(signals)
            result_queue.put({
                "code": code,
                "name": name,
                "price": round(last_close, 2),
                "pct": round((df["close"].iloc[-1]/df["pre_close"].iloc[-1]-1)*100, 2),
                "signals": signal_str,
                "date": df["date"].iloc[-1].strftime("%Y-%m-%d")
            })
            
    except Exception as e:
        pass
    finally:
        with lock:
            pbar.update(1)


def worker(task_queue, pbar):
    while True:
        try:
            code, name = task_queue.get_nowait()
        except queue.Empty:
            break
            
        scan_one_stock(code, name, pbar)
        task_queue.task_done()


def main():
    print(f"\n=== A股强势形态扫描启动 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    print(f"参数：连续阳>{CONSECUTIVE_YANG}天 | 放量>{VOLUME_RATIO_THRESHOLD}x | 缺口>{GAP_THRESHOLD*100:.1f}% | 接近涨停>{NEAR_LIMIT_UP_PCT}%\n")
    
    # 获取全市场股票列表（可替换为其他来源）
    try:
        stock_list = ak.stock_zh_a_spot_em()
        stock_list = stock_list[stock_list["代码"].str.startswith(("0","6","3"))]  # 深沪主板+创业
        stock_list = stock_list[["代码", "名称"]]
        stock_list.columns = ["code", "name"]
        # 可进一步过滤ST、退市等
        stock_list = stock_list[~stock_list["name"].str.contains("ST|退市|\*")]
        
        print(f"共获取 {len(stock_list)} 只股票进行扫描...\n")
        
    except Exception as e:
        print("获取股票列表失败！", e)
        return
    
    task_queue = queue.Queue()
    for _, row in stock_list.iterrows():
        task_queue.put((row["code"], row["name"]))
    
    # 进度条
    pbar = tqdm(total=task_queue.qsize(), desc="扫股进度", ncols=100)
    
    threads = []
    for _ in range(min(MAX_WORKERS, len(stock_list))):
        t = threading.Thread(target=worker, args=(task_queue, pbar))
        t.daemon = True
        t.start()
        threads.append(t)
    
    task_queue.join()
    
    # 等待所有线程结束
    for t in threads:
        t.join(timeout=1.0)
    
    pbar.close()
    
    # 收集结果
    results = []
    while not result_queue.empty():
        results.append(result_queue.get())
    
    if not results:
        print("\n很遗憾...本次扫描没有符合条件的股票～\n")
        return
        
    df_result = pd.DataFrame(results)
    df_result = df_result.sort_values(["pct", "price"], ascending=False)
    
    print(f"\n找到 {len(df_result)} 只符合条件的股票！\n")
    print(df_result[["code","name","price","pct","signals"]].to_string(index=False))
    
    # 保存
    try:
        df_result.to_excel(RESULT_FILE, index=False)
        print(f"\n结果已保存至：{RESULT_FILE}\n")
    except Exception as e:
        print("保存Excel失败:", e)


if __name__ == "__main__":
    main()