"""HTTP smoke checks for locally running API and production dashboard; no browser automation."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def get(url, headers=None, method="GET"):
    try:
        with urlopen(Request(url, headers=headers or {}, method=method), timeout=5) as response:
            return response.status, response.read().decode()
    except HTTPError as error:
        return error.code, error.read().decode()


def main():
    status, body = get("http://127.0.0.1:8765/events")
    assert status == 200 and json.loads(body)["read_only"]
    events = json.loads(body)["events"]
    assert events, "Run the offline demo and select its audit log first"
    assert get("http://127.0.0.1:8765/events", {"Host": "evil.example"})[0] == 403
    assert get("http://127.0.0.1:8765/events", {"Origin": "http://evil.example"})[0] == 403
    assert get("http://127.0.0.1:8765/events", method="POST")[0] == 501
    status, page = get("http://127.0.0.1:3000/")
    assert status == 200
    assert "Event stream" in page and "permission.fetch" in page
    assert "API is unavailable" not in page
    _, page = get("http://127.0.0.1:3000/", {"Host": "evil.example"})
    assert "Local access only" in page and "permission.fetch" not in page
    print(json.dumps({"status": "passed", "mode": "real HTTP; no visual/browser automation", "api_events": len(events),
                      "checks": ["read-only JSON API", "foreign Host/Origin rejected", "POST unsupported", "server-rendered event data", "dashboard foreign Host rejected"]}, indent=2))


if __name__ == "__main__":
    main()
