"""QARA web server package.

Provides a FastAPI-based local web UI for browsing test history,
flakiness analysis, failure groups, digest reports, and LLM Q&A.

Usage via CLI::

    ari serve --port 8080

Usage programmatically::

    from qara.server.app import create_app
    import uvicorn

    app = create_app(db_path="~/.qara/ari.db")
    uvicorn.run(app, host="127.0.0.1", port=8080)
"""
