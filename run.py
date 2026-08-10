if __name__ == "__main__":
    import os
    import uvicorn

    # Hosting platforms (Railway, Render, ...) assign a port dynamically via
    # $PORT rather than letting you pick one; local dev falls back to 8000.
    port = int(os.getenv("PORT", "8000"))
    is_production = os.getenv("ENV") == "production"
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=not is_production)
