-- Convenience views for browsing data in pgAdmin without typing UUIDs.
-- Run this once against the database (pgAdmin: right-click the DB -> Query
-- Tool -> paste -> Execute). Safe to re-run any time (CREATE OR REPLACE).
--
-- These are read-only views: they don't change the real tables, primary
-- keys, or foreign keys, so nothing in the app (auth, API, JWTs) is
-- affected. short_id is just the first 8 characters of the UUID, shown
-- for eyeballing in results grids -- to actually filter on it use LIKE
-- 'xxxxxxxx%' since it isn't unique on its own.

CREATE OR REPLACE VIEW v_users AS
SELECT
    LEFT(id, 8) AS short_id,
    id,
    name,
    email,
    phone,
    gmail_connected,
    created_at
FROM users
ORDER BY created_at DESC;

CREATE OR REPLACE VIEW v_transactions AS
SELECT
    LEFT(t.id, 8) AS short_id,
    u.email AS user_email,
    t.merchant,
    t.amount,
    t.type,
    t.category,
    t.date,
    t.source,
    t.created_at,
    t.id AS full_id,
    t.user_id AS full_user_id
FROM transactions t
JOIN users u ON u.id = t.user_id
ORDER BY t.date DESC;

CREATE OR REPLACE VIEW v_accounts AS
SELECT
    LEFT(a.id, 8) AS short_id,
    u.email AS user_email,
    a.name,
    a.type,
    a.opening_balance,
    a.is_archived,
    a.created_at,
    a.id AS full_id
FROM accounts a
JOIN users u ON u.id = a.user_id
ORDER BY a.created_at DESC;

CREATE OR REPLACE VIEW v_budgets AS
SELECT
    LEFT(b.id, 8) AS short_id,
    u.email AS user_email,
    b.category,
    b.limit_amount,
    b.spent_amount,
    b.period,
    b.start_date,
    b.end_date,
    b.created_at,
    b.id AS full_id
FROM budgets b
JOIN users u ON u.id = b.user_id
ORDER BY b.created_at DESC;

-- Example usage after creating these:
--   SELECT * FROM v_users;
--   SELECT * FROM v_transactions WHERE user_email = 'akashthakkar931@gmail.com' LIMIT 50;
--   SELECT * FROM v_transactions WHERE short_id LIKE '6831081d%';
--   SELECT * FROM v_transactions WHERE merchant ILIKE '%swiggy%';
