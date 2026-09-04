"""Meta Graph API — pubblicazione Facebook Page + Instagram Professional
(item 8/9/18/21). Trasporto HTTP sempre mockato, nessuna rete reale."""
import socket

import pytest

from app.integrations.meta import facebook as FB
from app.integrations.meta import instagram as IG
from app.integrations.meta.errors import MetaMediaProcessingError


class _NetworkCallAttempted(Exception):
    pass


@pytest.fixture(autouse=True)
def block_all_real_sockets(monkeypatch):
    def _blocked(*a, **kw):
        raise _NetworkCallAttempted("Tentativo di apertura socket reale bloccato nei test Meta.")
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


class _FakeResponse:
    def __init__(self, status_code, json_body, headers=None):
        self.status_code = status_code
        self._json = json_body
        self.headers = headers or {}

    def json(self):
        return self._json


def _patch_requests(monkeypatch, fn):
    import requests
    monkeypatch.setattr(requests, "request", fn)


# ---------------- Facebook Page ----------------
def test_publish_page_post_ok(monkeypatch):
    def fake(method, url, **kw):
        assert method == "POST"
        assert kw["data"]["message"] == "Ciao Bakery & Coffee!"
        return _FakeResponse(200, {"id": "page1_post1"})
    _patch_requests(monkeypatch, fake)
    r = FB.publish_page_post("tok", "page1", message="Ciao Bakery & Coffee!")
    assert r.external_post_id == "page1_post1"


def test_publish_page_photo_rifiuta_url_non_pubblico():
    # item 10: mai un URL locale/privato passato a Meta (che non potrebbe
    # mai raggiungerlo comunque) — schema non http/https E host locale/
    # privato sono entrambi rifiutati SUBITO, prima di ogni chiamata Graph API.
    for url_non_valido in (
        "http://localhost:8000/img.png", "http://127.0.0.1/img.png",
        "http://192.168.1.5/img.png", "http://10.0.0.4/img.png",
        "file:///tmp/img.png", "", None,
    ):
        with pytest.raises(MetaMediaProcessingError):
            FB.publish_page_photo("tok", "page1", image_url=url_non_valido, caption="x")


def test_publish_page_photo_ok(monkeypatch):
    def fake(method, url, **kw):
        assert kw["data"]["url"] == "https://cdn.example/flyer.png"
        return _FakeResponse(200, {"id": "photo1", "post_id": "page1_post2"})
    _patch_requests(monkeypatch, fake)
    r = FB.publish_page_photo("tok", "page1", image_url="https://cdn.example/flyer.png", caption="Le nostre focaccine")
    assert r.external_post_id == "page1_post2"


def test_publish_page_video_ok(monkeypatch):
    def fake(method, url, **kw):
        assert kw["data"]["file_url"] == "https://cdn.example/reel.mp4"
        return _FakeResponse(200, {"id": "video1"})
    _patch_requests(monkeypatch, fake)
    r = FB.publish_page_video("tok", "page1", video_url="https://cdn.example/reel.mp4", description="Weekend!")
    assert r.external_post_id == "video1"


def test_get_post_insights_mappa_le_metriche_disponibili(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"data": [
            {"name": "post_impressions", "values": [{"value": 500}]},
            {"name": "post_impressions_unique", "values": [{"value": 420}]},
            {"name": "post_reactions_like_total", "values": [{"value": 30}]},
        ]})
    _patch_requests(monkeypatch, fake)
    m = FB.get_post_insights("tok", "post1")
    assert m.data_available is True
    assert m.impressions == 500
    assert m.reach == 420
    assert m.likes == 30
    assert m.comments is None  # non fornita: mai un valore inventato


def test_get_post_insights_nessun_dato_disponibile(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"data": []})
    _patch_requests(monkeypatch, fake)
    m = FB.get_post_insights("tok", "post-nuovo")
    assert m.data_available is False
    assert m.impressions is None


def test_get_post_insights_errore_non_bloccante(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(400, {"error": {"code": 100, "message": "Metric not supported"}})
    _patch_requests(monkeypatch, fake)
    m = FB.get_post_insights("tok", "post1")
    assert m.data_available is False
    assert "non recuperabili" in m.note.lower()


# ---------------- Instagram (container flow) ----------------
def test_create_media_container_richiede_esattamente_uno_tra_image_e_video():
    with pytest.raises(MetaMediaProcessingError):
        IG.create_media_container("tok", "ig1", caption="x")
    with pytest.raises(MetaMediaProcessingError):
        IG.create_media_container("tok", "ig1", caption="x",
                                  image_url="https://cdn.example/a.png", video_url="https://cdn.example/a.mp4")


def test_create_media_container_immagine_ok(monkeypatch):
    def fake(method, url, **kw):
        assert kw["data"]["image_url"] == "https://cdn.example/flyer.png"
        assert "media_type" not in kw["data"]
        return _FakeResponse(200, {"id": "container1"})
    _patch_requests(monkeypatch, fake)
    cid = IG.create_media_container("tok", "ig1", caption="Le focaccine", image_url="https://cdn.example/flyer.png")
    assert cid == "container1"


def test_create_media_container_reel_ok(monkeypatch):
    def fake(method, url, **kw):
        assert kw["data"]["video_url"] == "https://cdn.example/reel.mp4"
        assert kw["data"]["media_type"] == "REELS"
        return _FakeResponse(200, {"id": "container2"})
    _patch_requests(monkeypatch, fake)
    cid = IG.create_media_container("tok", "ig1", caption="Weekend!", video_url="https://cdn.example/reel.mp4", is_reel=True)
    assert cid == "container2"


def test_container_status_flow_in_progress_poi_finished(monkeypatch):
    stati = iter(["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
    def fake(method, url, **kw):
        return _FakeResponse(200, {"status_code": next(stati)})
    _patch_requests(monkeypatch, fake)
    s1 = IG.get_container_status("tok", "container1")
    s2 = IG.get_container_status("tok", "container1")
    s3 = IG.get_container_status("tok", "container1")
    assert [s1.status_code, s2.status_code, s3.status_code] == ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    assert s3.status_code in IG.CONTAINER_STATI_TERMINALI


def test_container_status_error_e_terminale(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"status_code": "ERROR", "status": "Media non valido"})
    _patch_requests(monkeypatch, fake)
    s = IG.get_container_status("tok", "container1")
    assert s.status_code == "ERROR"
    assert s.status_code in IG.CONTAINER_STATI_TERMINALI


def test_publish_container_ok(monkeypatch):
    def fake(method, url, **kw):
        assert kw["data"]["creation_id"] == "container1"
        return _FakeResponse(200, {"id": "media1"})
    _patch_requests(monkeypatch, fake)
    r = IG.publish_container("tok", "ig1", "container1")
    assert r.external_post_id == "media1"


def test_get_media_insights_reel_mappa_plays_come_views(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"data": [
            {"name": "impressions", "values": [{"value": 1000}]},
            {"name": "reach", "values": [{"value": 800}]},
            {"name": "plays", "values": [{"value": 950}]},
            {"name": "likes", "values": [{"value": 75}]},
        ]})
    _patch_requests(monkeypatch, fake)
    m = IG.get_media_insights("tok", "media1")
    assert m.data_available is True
    assert m.views == 950
    assert m.saves is None  # non fornita: mai inventata


def test_get_media_insights_nessun_dato(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"data": []})
    _patch_requests(monkeypatch, fake)
    m = IG.get_media_insights("tok", "media-nuovo")
    assert m.data_available is False


def test_get_media_permalink(monkeypatch):
    def fake(method, url, **kw):
        return _FakeResponse(200, {"permalink": "https://www.instagram.com/p/xyz/"})
    _patch_requests(monkeypatch, fake)
    link = IG.get_media_permalink("tok", "media1")
    assert link == "https://www.instagram.com/p/xyz/"
