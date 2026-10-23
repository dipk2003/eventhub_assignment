import logging
import time

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.perf_counter()
        response = self.get_response(request)
        duration = time.perf_counter() - start_time
        logger.info(
            "%s %s - %s - %.2fs",
            request.method, request.path, response.status_code, duration,
        )
        return response
