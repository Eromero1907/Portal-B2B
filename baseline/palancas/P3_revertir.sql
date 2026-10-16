ALTER SYSTEM RESET random_page_cost;
SELECT pg_reload_conf();
