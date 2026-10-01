"""FastAPI entry point: `uvicorn app.main:app --reload` (run from backend/)."""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import Settings, get_settings
from app.geo.rail import SegmentStore
from app.geo.stations import StationIndex
from app.plk.client import PlkAuthError, PlkClient, PlkSource
from app.plk.mock import MockPlkClient
from app.state import LiveState, utcnow
from app.sync.poller import Poller

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ictracker")


def create_app(
    settings: Settings | None = None,
    source: PlkSource | None = None,
    stations: StationIndex | None = None,
    segments: SegmentStore | None = None,
    start_poller: bool = True,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        idx = stations or StationIndex.load(settings.stations_geo_path, settings.overrides_path)
        segs = segments or SegmentStore(settings.segments_path)
        state = LiveState(settings, idx, segs)
        app.state.live = state
        log.info("mode=%s, %d located stations, %d track segments", state.mode, len(idx), len(segs))

        src = source
        if src is None:
            if settings.mock_mode:
                src = MockPlkClient(settings.tz)
            else:
                try:
                    src = PlkClient(settings)
                except PlkAuthError as exc:
                    log.error("%s — set PLK_API_KEY or MOCK_MODE=1 in backend/.env", exc)
                    state.record_error(str(exc), utcnow(), auth=True)
        poller = Poller(settings, src, state) if src is not None else None
        app.state.poller = poller
        task = asyncio.create_task(poller.run()) if poller and start_poller else None
        try:
            yield
        finally:
            if poller:
                poller.stop()
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if src is not None:
                await src.aclose()

    app = FastAPI(title="ICtracker", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
