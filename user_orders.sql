USE ecommerce_clean;

-- ============================================================
-- 电商用户/商品业务分析（完整版）
-- 成交口径：order_status IN ('Delivered','Shipped','Paid')
--          （等价 is_closed=1，成交单 68,116 已验证）
-- 参考日 = MAX(order_time) = 2025-01-02 18:30:00
-- DBeaver 提示：1064 是 DBeaver 多语句问题，逐条执行即可
-- ============================================================

-- ① RFM 根因表（从有效订单重算 + R 降序 + 2×2×2 八分群）
DROP TABLE IF EXISTS rpt_rfm;
CREATE TABLE rpt_rfm AS
SELECT user_id, R_days, F, M, last_order_time, first_order_time,
       NTILE(4) OVER (ORDER BY R_days DESC) AS R_score,   -- R 越小越优，降序得高分
       NTILE(4) OVER (ORDER BY F)  AS F_score,
       NTILE(4) OVER (ORDER BY M)  AS M_score
FROM (
    SELECT user_id,
           DATEDIFF('2025-01-02 18:30:00', MAX(order_time)) AS R_days,
           COUNT(DISTINCT order_id) AS F,
           SUM(amount) AS M,
           MAX(order_time) AS last_order_time,
           MIN(order_time) AS first_order_time
    FROM orders_clean
    WHERE order_status IN ('Delivered','Shipped','Paid')
    GROUP BY user_id
) t;

ALTER TABLE rpt_rfm ADD COLUMN segment VARCHAR(20);
UPDATE rpt_rfm SET segment = CASE
    WHEN R_score>=3 AND F_score>=3 AND M_score>=3 THEN '重要价值用户'
    WHEN R_score<=2 AND F_score>=3 AND M_score>=3 THEN '重要保持用户'   -- 高价值流失，最该挽留
    WHEN R_score>=3 AND F_score<=2 AND M_score>=3 THEN '重要发展用户'
    WHEN R_score<=2 AND F_score<=2 AND M_score>=3 THEN '重要挽留用户'
    WHEN R_score>=3 AND F_score>=3 AND M_score<=2 THEN '一般价值用户'
    WHEN R_score<=2 AND F_score>=3 AND M_score<=2 THEN '一般保持用户'
    WHEN R_score>=3 AND F_score<=2 AND M_score<=2 THEN '一般发展用户'
    ELSE '流失风险用户'
END;
ALTER TABLE rpt_rfm ADD PRIMARY KEY (user_id);

-- ② 用户分层名单 + 运营优先级
DROP TABLE IF EXISTS rpt_user_priority;
CREATE TABLE rpt_user_priority AS
SELECT rr.user_id, rr.R_days, rr.F, rr.M, rr.R_score, rr.F_score, rr.M_score,
       rr.last_order_time, rr.first_order_time, rr.segment,
       CASE WHEN rr.segment='重要价值用户' THEN 'P0-重点维护'
            WHEN rr.segment='重要保持用户' THEN 'P1-高价值唤回'
            WHEN rr.segment='重要发展用户' THEN 'P1-重点发展'
            WHEN rr.segment='重要挽留用户' THEN 'P1-挽留唤回'
            WHEN rr.segment='流失风险用户' THEN 'P2-流失唤醒'
            ELSE 'P3-一般运营' END AS priority
FROM rpt_rfm rr;

-- ③ 全量分层名单输出（面试看这张表）
SELECT * FROM rpt_user_priority ORDER BY priority, M DESC;

-- ④ 商品 GMV 聚合
DROP TABLE IF EXISTS rpt_product_gmv;
CREATE TABLE rpt_product_gmv AS
SELECT product_id, MAX(product_name) product_name, MAX(brand) brand, MAX(category) category,
       COUNT(*) orders, SUM(quantity) units, SUM(COALESCE(amount,0)) gmv
FROM orders_clean
WHERE order_status IN ('Delivered','Shipped','Paid')
GROUP BY product_id;

-- ⑤ 商品 ABC 分层（加入前累计占比，防首行跳档；二级排序保证确定）
DROP TABLE IF EXISTS rpt_product_abc;
CREATE TABLE rpt_product_abc AS
SELECT g.product_id, g.product_name, g.brand, g.category, g.orders, g.units, g.gmv,
       SUM(g.gmv) OVER (ORDER BY g.gmv DESC, g.product_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) / SUM(g.gmv) OVER () AS cum_share,
       CASE WHEN (SUM(g.gmv) OVER (ORDER BY g.gmv DESC, g.product_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) - g.gmv)
                    / SUM(g.gmv) OVER () < 0.70 THEN 'A'
            WHEN (SUM(g.gmv) OVER (ORDER BY g.gmv DESC, g.product_id
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) - g.gmv)
                    / SUM(g.gmv) OVER () < 0.90 THEN 'B'
            ELSE 'C' END AS abc_class
FROM rpt_product_gmv g;

-- ⑥ 商品四象限（与 ABC 联合看：明星款=高GMV高销量，A类保供主推）
DROP TABLE IF EXISTS rpt_product_seg;
CREATE TABLE rpt_product_seg AS
SELECT p.*, 
       CASE WHEN p.gmv_half=2 AND p.unit_half=2 THEN '明星款'
            WHEN p.gmv_half=2 AND p.unit_half=1 THEN '利润款'
            WHEN p.gmv_half=1 AND p.unit_half=2 THEN '引流款'
            ELSE '长尾款' END AS quadrant
FROM (
    SELECT a.*, NTILE(2) OVER (ORDER BY gmv) gmv_half,   -- 近似中位切分
               NTILE(2) OVER (ORDER BY units) unit_half
    FROM rpt_product_abc a
) p;
SELECT product_id, product_name, brand, category, ROUND(gmv) gmv, abc_class, quadrant
FROM rpt_product_seg ORDER BY gmv DESC;

-- ⑦ 未购/首单转化名单（预期 0 行：所有注册用户均有成交，单独做首单转化）
SELECT user_id, register_time, register_channel, click_count, cart_count
FROM user_clean u
WHERE NOT EXISTS (SELECT 1 FROM orders_clean o
                  WHERE o.user_id=u.user_id
                    AND o.order_status IN ('Delivered','Shipped','Paid'));

-- ⑧ 区域 GDP × 渗透率（用户维表 × 订单；渗透率高省=低垂果实，先推渠道）
SELECT u.user_province_name AS 省份,
       MAX(u.user_province_gdp) 省份GDP, MAX(u.user_province_population) 人口,
       COUNT(DISTINCT u.user_id) 用户数,
       COUNT(DISTINCT CASE WHEN o.order_status IN ('Delivered','Shipped','Paid') THEN o.user_id END) 购买用户,
       ROUND(COUNT(DISTINCT CASE WHEN o.order_status IN ('Delivered','Shipped','Paid') THEN o.user_id END)
             / NULLIF(COUNT(DISTINCT u.user_id),0),4) 渗透率,
       ROUND(SUM(CASE WHEN o.order_status IN ('Delivered','Shipped','Paid') THEN COALESCE(o.amount,0) ELSE 0 END)
             / NULLIF(COUNT(DISTINCT u.user_id),0),2) 人均GMV,
       ROUND(SUM(CASE WHEN o.order_status IN ('Delivered','Shipped','Paid') THEN COALESCE(o.amount,0) ELSE 0 END)
             / NULLIF(COUNT(DISTINCT CASE WHEN o.order_status IN ('Delivered','Shipped','Paid') THEN o.user_id END),0),2) 购买用户人均GMV
FROM user_clean u LEFT JOIN orders_clean o ON u.user_id=o.user_id
GROUP BY u.user_province_name
HAVING COUNT(DISTINCT u.user_id) >= 30
ORDER BY 渗透率 DESC;

-- ⑨ 流失预警（最该挽留的排最前：重要保持>高额>久未购）
SELECT user_id, R_days, F, M, segment, priority
FROM rpt_user_priority
WHERE segment IN ('流失风险用户','重要保持用户','重要挽留用户') OR R_days >= 60
ORDER BY (segment='重要保持用户') DESC, M DESC, R_days DESC;

-- ⑩ 三类校验
-- 校验A：R 方向（最近购 R_days=0 应 R_score=4）
SELECT user_id, R_days, R_score FROM rpt_rfm ORDER BY R_days ASC LIMIT 5;
-- 校验B：M 同口径（期望 0 行不一致）
SELECT COUNT(*) FROM rpt_rfm r
LEFT JOIN (SELECT user_id, SUM(amount) amt FROM orders_clean
           WHERE order_status IN ('Delivered','Shipped','Paid') GROUP BY user_id) o
  ON r.user_id = o.user_id
WHERE ABS(r.M - o.amt) > 0.01;
-- 校验C：8 分群互斥完备（期望 dup=0、NULL=0）
SELECT COUNT(*) FROM (SELECT user_id FROM rpt_rfm GROUP BY user_id HAVING COUNT(*)>1) t;
SELECT COUNT(*) FROM rpt_rfm WHERE segment IS NULL;

-- ⑪ "不做"的可行性检测（面试当场可跑）
-- 购物篮：同订单多商品（期望空 → 单商品订单，不做捆绑）
SELECT order_id, COUNT(DISTINCT product_id) n FROM orders_clean GROUP BY order_id HAVING n>1 LIMIT 10;
-- 履约时效：占位值检测（期望全量命中 → 无真实履约时长，不做时效分析）
SELECT COUNT(*) 占位数 FROM orders_clean WHERE YEAR(fulfillment_time) = 1970;
