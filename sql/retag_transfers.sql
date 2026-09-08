-- Retag account-to-account transfers that were imported before the parser
-- tagged them.
--
-- A NEFT / IMPS / RTGS / "fund transfer" is money moving between accounts
-- (usually the user's own) — a debit on one side, a credit on the other,
-- netting to zero. Insights / the Home card / recurring detection now leave
-- `category = 'transfer'` rows out of every spend and income figure, so the
-- inflated monthly totals come right once these rows carry that category.
--
-- The current importer already sets it; this fixes historical rows. Run in
-- pgAdmin's Query Tool against the production DB.

-- 1. Preview:
SELECT id, type, amount, merchant, category, left(description, 80) AS descr
FROM transactions
WHERE source IN ('gmail', 'sms')
  AND category <> 'transfer'
  AND description ~* '(via\s+(NEFT|IMPS|RTGS)|fund\s+transfer)'
ORDER BY amount DESC;

-- 2. Retag:
UPDATE transactions
SET category = 'transfer'
WHERE source IN ('gmail', 'sms')
  AND category <> 'transfer'
  AND description ~* '(via\s+(NEFT|IMPS|RTGS)|fund\s+transfer)';

-- 3. Check the month again (transfers now excluded from the app's totals):
--   SELECT type,
--          round(sum(amount) FILTER (WHERE category <> 'transfer')::numeric, 2) AS spend_or_income,
--          round(sum(amount) FILTER (WHERE category =  'transfer')::numeric, 2) AS transfers
--   FROM transactions
--   WHERE user_id = 6 AND date >= date_trunc('month', now() AT TIME ZONE 'Asia/Kolkata')
--   GROUP BY type;
--
-- UPI payments to a person are left as-is — those are as likely a real
-- expense as a transfer. Recategorise any that were actually transfers to
-- yourself from the app (transaction detail -> category -> Transfer).
