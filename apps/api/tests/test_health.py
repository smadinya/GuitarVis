"""GET /health names whichever store did not answer."""

from api_fixture import make_api
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.store import InMemoryJobStore


class DownStore(InMemoryJobStore):
    def ping(self) -> None:
        raise ConnectionError("postgres is down")


class DownBlobs(InMemoryBlobStore):
    def ping(self) -> None:
        raise ConnectionError("storage is down")


def test_everything_answers() -> None:
    response = make_api().client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "services": {"postgres": "ok", "redis": "ok", "storage": "ok"},
    }


def test_the_queue_does_not_answer() -> None:
    api = make_api()
    api.queue.down = True

    response = api.client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["services"] == {
        "postgres": "ok",
        "redis": "unreachable",
        "storage": "ok",
    }
    assert body["error"] == {"reason": "internal", "message": "Not answering: redis."}


def test_the_database_and_storage_do_not_answer() -> None:
    response = make_api(store=DownStore(), blobs=DownBlobs()).client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Not answering: postgres, storage."
