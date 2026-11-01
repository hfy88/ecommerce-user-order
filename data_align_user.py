# -*- coding: utf-8 -*-
"""
用户表购买字段对齐脚本
========================
背景：data/user.csv 的 total_purchase_times / total_purchase_amount / last_purchase_time
     与订单事实表脱节（4.8 万人无任何订单，却被填了购买次数≥1、金额>0），不可信。
做法：用 orders_clean 的【成交口径 is_closed=1】按 user_id 重算这三个购买字段，
     左连接回用户表，输出 data_clean/user_aligned.csv（保留原始列作对照 + 新增 _real 对齐列）。
口径：成交 = order_status IN ('Delivered','Shipped','Paid')，等价 is_closed=1。
对账：对齐列应与 rpt_rfm 的 F / M / last_order_time 完全一致。
"""
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CLEAN_DIR = BASE_DIR / "data_clean"

print("=" * 60)
print("用户表购买字段对齐")
print("=" * 60)

# 1. 读原始用户表 + 已清洗订单表
user_df = pd.read_csv(DATA_DIR / "user.csv", encoding="utf-8-sig")
orders_df = pd.read_csv(CLEAN_DIR / "orders_clean.csv", encoding="utf-8-sig")
orders_df["order_time"] = pd.to_datetime(orders_df["order_time"])   # 转时间，保证 max 取真实最晚

# 2. 用成交订单(is_closed=1)按用户聚合：次数=去重订单数，金额=成交额，最近=最晚成交时间
agg = (orders_df[orders_df["is_closed"] == 1]
       .groupby("user_id")
       .agg(purchase_times_real=("order_id", "nunique"),
            purchase_amount_real=("amount", "sum"),
            last_purchase_time_real=("order_time", "max"))
       .reset_index())

# 3. 左连接回用户表（未成交用户三个对齐列取默认：0 / 0 / 空）
aligned = user_df.merge(agg, on="user_id", how="left")
aligned["purchase_times_real"] = aligned["purchase_times_real"].fillna(0).astype(int)
aligned["purchase_amount_real"] = aligned["purchase_amount_real"].fillna(0).round(2)
aligned["last_purchase_time_real"] = pd.to_datetime(aligned["last_purchase_time_real"])  # 未成交为 NaT

# 4. 落盘
out_path = CLEAN_DIR / "user_aligned.csv"
aligned.to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"已输出：{out_path}（{aligned.shape[0]} 行 × {aligned.shape[1]} 列）")

# 5. 对账：与 rpt_rfm 的 F / M / last_order_time 比对（应完全一致）
rfm = pd.read_csv(CLEAN_DIR / "rpt_rfm.csv", encoding="utf-8-sig")
rfm["last_order_time"] = pd.to_datetime(rfm["last_order_time"])
check = aligned.merge(rfm[["user_id", "F", "M", "last_order_time"]], on="user_id", how="inner")
diff_cnt = int((check["purchase_times_real"] != check["F"]).sum())
diff_amt = int((abs(check["purchase_amount_real"] - check["M"]) > 0.01).sum())
diff_t   = int((check["last_purchase_time_real"] != check["last_order_time"]).sum())
print(f"[对账] 与 rpt_rfm 比对：次数不一致 {diff_cnt}，金额不一致 {diff_amt}，最近时间不一致 {diff_t}")

# 6. 汇总统计
no_buy = int((aligned["purchase_times_real"] == 0).sum())
print(f"[汇总] 成交用户 {int((aligned['purchase_times_real']>0).sum())} 人；未成交(次数=0) {no_buy} 人")
print(f"[汇总] 对齐后累计成交金额 ¥{aligned['purchase_amount_real'].sum():,.2f}")
