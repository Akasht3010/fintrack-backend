-- One-time cleanup: delete budgets whose period has already ended.
--
-- Why: budgets are one-shot per period (a budget covers exactly the week or
-- month it was created for). Once end_date has passed, list_active_budgets
-- stops returning the row, so it's invisible in the app but still sits in
-- the table. Before the budget_service fix that shipped alongside this
-- script, such a stale row could still overlap the *current* period window
-- and 409 a new budget the user could never see to delete — the "already
-- exists but doesn't show" bug.
--
-- Safe to run repeatedly. Only removes rows that are already dead to the
-- app; nothing currently active is touched.
--
-- Run this in pgAdmin's Query Tool against the production DB.
-- Business timestamps are stored as naive IST wall-clock (see
-- app/utils/timezone.py), so "now" is compared in Asia/Kolkata.

-- 1. Preview what will be deleted (run this first, on its own):
SELECT id, user_id, category, period, start_date, end_date, limit_amount
FROM budgets
WHERE end_date < (now() AT TIME ZONE 'Asia/Kolkata')
ORDER BY user_id, category, start_date;

-- 2. Then delete them:
DELETE FROM budgets
WHERE end_date < (now() AT TIME ZONE 'Asia/Kolkata');
