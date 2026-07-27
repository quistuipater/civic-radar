import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def fetch_url(url: str, timeout: float = 30.0) -> httpx.Response:
    headers = {"User-Agent": settings.http_user_agent}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response
