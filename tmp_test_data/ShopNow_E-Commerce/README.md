# ShopNow E-Commerce Demo Dataset

This directory contains a synthetic 50-run Allure-style report history for demo
and local evaluation.

Each `run_###/` directory is one report run and can be ingested independently:

```bash
qalens ingest tmp_test_data/ShopNow_E-Commerce/run_001 --db ./shopnow-demo.db
```

To load the full history:

```bash
rm -f ./shopnow-demo.db
for report in tmp_test_data/ShopNow_E-Commerce/run_*; do
  qalens ingest "$report" --db ./shopnow-demo.db
done
```

Then run analysis or start the web UI:

```bash
qalens analyze --db ./shopnow-demo.db
qalens serve --db ./shopnow-demo.db
```

The local SQLite files (`ari.db`, `ari.db-wal`, `ari.db-shm`) are intentionally
not tracked. Recreate the database from the report folders when needed.
