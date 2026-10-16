-- P2 · JIT apagado (consultas de pocos ms no amortizan la compilación)
ALTER SYSTEM SET jit = off;
SELECT pg_reload_conf();
