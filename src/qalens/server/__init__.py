"""QA Lens web server package.

Provides a FastAPI-based local web UI for browsing test history,
flakiness analysis, failure groups, digest reports, and LLM Q&A.

Usage via CLI::

    qalens serve --port 8080

Usage programmatically::

    from qalens.server.app import create_app
    import uvicorn

    app = create_app(db_path="~/.qalens/qalens.db")
    uvicorn.run(app, host="127.0.0.1", port=8080)
"""
