import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """A provider could not return a usable response."""


def get_json(url: str, *, timeout_seconds: float = 20) -> object:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Routewise/0.1"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read())
    except HTTPError as error:
        try:
            details = error.read().decode("utf-8")[:500]
        except Exception:
            details = ""
        raise ProviderError(f"Provider returned HTTP {error.code}: {details}") from error
    except (URLError, TimeoutError) as error:
        raise ProviderError(f"Could not reach provider: {error}") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProviderError("Provider returned an invalid JSON response") from error
