import inspect

from fastapi.routing import APIRoute

from app.main import app

# Endpoints that do no blocking I/O and may stay on the event loop.
_ASYNC_ALLOWED = {"health_check"}


def _api_routes(routes):
    # FastAPI >= 0.141 keeps included routers nested (as _IncludedRouter)
    # rather than flattening their routes into app.routes.
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif hasattr(route, "original_router"):
            yield from _api_routes(route.original_router.routes)


def test_api_routes_are_sync_so_blocking_io_runs_in_the_threadpool():
    """Every handler here uses a sync SQLAlchemy Session (plus bcrypt, SMTP,
    Google API calls). As `async def`, those block the single event loop —
    one slow Gmail sync stalled every other request on the instance,
    /health included. Plain `def` makes FastAPI run them in its threadpool."""
    offenders = [
        f"{route.path} -> {route.endpoint.__name__}"
        for route in _api_routes(app.routes)
        if inspect.iscoroutinefunction(route.endpoint)
        and route.endpoint.__name__ not in _ASYNC_ALLOWED
    ]
    assert len(list(_api_routes(app.routes))) > 40  # the walk actually found the routers
    assert offenders == []
