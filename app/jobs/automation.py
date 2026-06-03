from app import app, logger


@app.on_event("startup")
def _load_automation():
    """Load plugins and rules once the app (and DB) is ready."""
    try:
        from app.plugins import load_plugins

        load_plugins()
    except Exception:
        logger.exception("Failed to load plugins")

    try:
        from app.rules import load_rules

        load_rules()
    except Exception:
        logger.exception("Failed to load rule engine")

    try:
        from app.workflows import load_workflows

        load_workflows()
    except Exception:
        logger.exception("Failed to load workflow engine")
