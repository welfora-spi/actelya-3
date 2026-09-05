"""Lead Generation — test dello storage file sicuro: hash idempotente,
prevenzione path traversal, isolamento per organizzazione."""
import pytest

from app.domains.leadgen import storage


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    for org in ("org-test-storage-1", "org-test-storage-2"):
        try:
            import shutil
            shutil.rmtree(storage.BASE_UPLOAD_DIR / org, ignore_errors=True)
        except Exception:
            pass


def test_compute_hash_deterministico():
    assert storage.compute_hash(b"contenuto") == storage.compute_hash(b"contenuto")
    assert storage.compute_hash(b"contenuto") != storage.compute_hash(b"altro")


def test_save_and_read_roundtrip():
    percorso = storage.save_file_bytes("org-test-storage-1", "file-abc", b"dati di test")
    assert percorso == "org-test-storage-1/file-abc"
    letto = storage.read_file_bytes("org-test-storage-1", "file-abc")
    assert letto == b"dati di test"


def test_read_file_inesistente_solleva_errore():
    with pytest.raises(FileNotFoundError):
        storage.read_file_bytes("org-test-storage-1", "file-mai-esistito")


def test_delete_file():
    storage.save_file_bytes("org-test-storage-1", "file-da-cancellare", b"x")
    assert storage.delete_file("org-test-storage-1", "file-da-cancellare") is True
    assert storage.delete_file("org-test-storage-1", "file-da-cancellare") is False


def test_isolamento_tra_organizzazioni():
    storage.save_file_bytes("org-test-storage-1", "stesso-id", b"org1")
    storage.save_file_bytes("org-test-storage-2", "stesso-id", b"org2")
    assert storage.read_file_bytes("org-test-storage-1", "stesso-id") == b"org1"
    assert storage.read_file_bytes("org-test-storage-2", "stesso-id") == b"org2"


@pytest.mark.parametrize("file_id_malevolo", ["../../etc/passwd", "..\\..\\windows\\system32", "a/b/c", ""])
def test_path_traversal_prevenuto(file_id_malevolo):
    with pytest.raises((ValueError, FileNotFoundError)):
        storage.read_file_bytes("org-test-storage-1", file_id_malevolo)
