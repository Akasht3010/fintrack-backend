-- Convenience views for browsing data in pgAdmin.
-- Run this once against the database (pgAdmin: right-click the DB -> Query
-- Tool -> paste -> Execute). Safe to re-run any time (CREATE OR REPLACE).
--
-- These are read-only views: they don't change the real tables or any
-- stored value. Every timestamp column in the actual tables (date,
-- created_at, updated_at, start_date, end_date, ...) is stored as naive
-- IST wall-clock time already -- these views just format it as
-- DD-MM-YYYY HH24:MI:SS for easier reading. No timezone conversion
-- happens here; the raw columns are already correct IST.

CREATE OR REPLACE VIEW v_users AS
SELECT
    id,
    name,
    email,
    phone,
    gmail_connected,
    to_char(created_at, 'DD-MM-YYYY HH24:MI:SS') AS created_at_ist,
    to_char(updated_at, 'DD-MM-YYYY HH24:MI:SS') AS updated_at_ist
FROM users
ORDER BY created_at DESC;

CREATE OR REPLACE VIEW v_transactions AS
SELECT
    t.id,
    u.email AS user_email,
    t.merchant,
    t.amount,
    t.type,
    t.category,
    to_char(t.date, 'DD-MM-YYYY HH24:MI:SS') AS date_ist,
    t.source,
    to_char(t.created_at, 'DD-MM-YYYY HH24:MI:SS') AS created_at_ist,
    t.user_id
FROM transactions t
JOIN users u ON u.id = t.user_id
ORDER BY t.date DESC;

CREATE OR REPLACE VIEW v_accounts AS
SELECT
    a.id,
    u.email AS user_email,
    a.name,
    a.type,
    a.opening_balance,
    a.is_archived,
    to_char(a.created_at, 'DD-MM-YYYY HH24:MI:SS') AS created_at_ist
FROM accounts a
JOIN users u ON u.id = a.user_id
ORDER BY a.created_at DESC;

CREATE OR REPLACE VIEW v_budgets AS
SELECT
    b.id,
    u.email AS user_email,
    b.category,
    b.limit_amount,
    b.spent_amount,
    b.period,
    to_char(b.start_date, 'DD-MM-YYYY HH24:MI:SS') AS start_date_ist,
    to_char(b.end_date, 'DD-MM-YYYY HH24:MI:SS') AS end_date_ist,
    to_char(b.created_at, 'DD-MM-YYYY HH24:MI:SS') AS created_at_ist
FROM budgets b
JOIN users u ON u.id = b.user_id
ORDER BY b.created_at DESC;

-- Example usage after creating these:
--   SELECT * FROM v_users;
--   SELECT * FROM v_transactions WHERE user_email = 'akashthakkar931@gmail.com' LIMIT 50;
--   SELECT * FROM v_transactions WHERE merchant ILIKE '%swiggy%';
