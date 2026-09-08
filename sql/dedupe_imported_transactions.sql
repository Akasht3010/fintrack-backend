-- One-time cleanup: collapse duplicate imported transactions.
--
-- Before the 10-minute dedup window shipped, one real purchase could land
-- as several rows — the bank alert, the card-network alert, the UPI-app
-- receipt, the merchant receipt — each a distinct Gmail message with a
-- slightly different timestamp, so the old exact-timestamp check missed
-- them. That inflated monthly totals several times over.
--
-- This keeps the earliest row in each (user, amount, 10-minute bucket)
-- cluster of gmail/sms rows and deletes the rest. Manual rows are never
-- touched. Run in pgAdmin's Query Tool against the production DB.

-- 1. Preview the clusters that will be collapsed (run first):
SELECT user_id,
       round(amount::numeric, 2)                        AS amount,
       to_timestamp(floor(extract(epoch from date) / 600) * 600) AS bucket_start,
       count(*)                                         AS rows_in_cluster,
       array_agg(id ORDER BY date, id)                  AS ids,
       array_agg(DISTINCT source)                       AS sources
FROM transactions
WHERE source IN ('gmail', 'sms')
GROUP BY user_id, round(amount::numeric, 2), floor(extract(epoch from date) / 600)
HAVING count(*) > 1
ORDER BY rows_in_cluster DESC;

-- 2. Delete the extras, keeping the earliest row per cluster:
DELETE FROM transactions t
USING (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id,
                            round(amount::numeric, 2),
                            floor(extract(epoch from date) / 600)
               ORDER BY date, id
           ) AS rn
    FROM transactions
    WHERE source IN ('gmail', 'sms')
) d
WHERE t.id = d.id AND d.rn > 1;

-- 3. Re-check the month afterwards:
--   SELECT type, count(*), round(sum(amount)::numeric, 2)
--   FROM transactions
--   WHERE user_id = 6 AND date >= date_trunc('month', now() AT TIME ZONE 'Asia/Kolkata')
--   GROUP BY type;
--
-- Budgets' spent_amount / remaining_amount self-correct on the next
-- GET /api/budgets (i.e. next time the Budget screen loads).
