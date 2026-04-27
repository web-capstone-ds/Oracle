"""DS Oracle 판정 엔진 엔트리포인트.

O10에서 Graceful Shutdown과 전체 파이프라인 배선이 완성된다.
여기서는 구성 요소가 조립될 뼈대만 제공한다.
"""

from __future__ import annotations

import asyncio
import selectors
asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import signal

from config import settings
from utils.logging_config import configure_logging, get_logger

log = get_logger(__name__)


async def run() -> None:
    configure_logging()
    log.info("oracle_starting", broker=settings.mqtt_broker_host)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_stop(sig: signal.Signals) -> None:
        log.info("signal_received", signal=sig.name)
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _request_stop(s))
        except NotImplementedError:
            # Windows에서는 signal handler 일부 미지원.
            signal.signal(sig, lambda *_a, s=sig: _request_stop(s))

    from app import OracleApp

    app = OracleApp(loop=loop)
    await app.start()

    await stop_event.wait()

    try:
        await asyncio.wait_for(app.stop(), timeout=settings.shutdown_timeout_sec)
    except asyncio.TimeoutError:
        log.error("shutdown_timeout", timeout_sec=settings.shutdown_timeout_sec)

    log.info("oracle_stopped")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
