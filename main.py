import asyncio
import logging
import os
import sys

from server import WebSocketServer


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def main():
    setup_logging()
    host = os.getenv("WS_HOST", "0.0.0.0")
    port = int(os.getenv("WS_PORT", "8765"))

    server = WebSocketServer(host=host, port=port)
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logging.info("WebSocket server stopped by user.")


if __name__ == "__main__":
    main()
