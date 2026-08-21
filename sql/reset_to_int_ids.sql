-- One-time reset: drop every table so the backend rebuilds them fresh with
-- integer auto-increment primary keys instead of UUID strings.
--
-- DESTRUCTIVE: this deletes all existing data (users, transactions,
-- accounts, budgets, categories, OTP codes). Confirmed OK to do since this
-- is still testing-phase data.
--
-- Run this in pgAdmin's Query Tool against the production DB, THEN redeploy
-- the backend (or wait for the push-triggered redeploy) — the app's
-- startup hook (Base.metadata.create_all + seed_default_categories) will
-- recreate every table from scratch with the new integer-id schema and
-- reseed the default categories.

DROP TABLE IF EXISTS otp_codes CASCADE;
DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS budgets CASCADE;
DROP TABLE IF EXISTS categories CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS users CASCADE;
