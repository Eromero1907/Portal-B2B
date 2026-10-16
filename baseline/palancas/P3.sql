-- P3 · random_page_cost = 1.1 (SSD / base completa en caché): favorece Index Scan ordenado en Q5 con OFFSET profundo
ALTER SYSTEM SET random_page_cost = 1.1;
SELECT pg_reload_conf();
