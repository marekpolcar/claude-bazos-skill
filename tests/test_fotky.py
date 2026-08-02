"""Offline tests for scripts/fotky.py — all images synthesized at test time
(no committed GPS-tagged binaries; PII stays out of the repo by construction)."""

import os
import shutil
import subprocess
import tempfile

import pytest
from PIL import Image

import fotky
import parse_inzerat


def test_pil_imported_at_module_level():
    # Pillow must be a load-time dependency of fotky.py, not imported lazily
    # inside process_photo — otherwise a missing install surfaces as a
    # ModuleNotFoundError caught by process_folder's per-photo except clause,
    # which mass-renames every photo to .vyrazeno instead of aborting cleanly.
    assert hasattr(fotky, "Image")
    assert hasattr(fotky, "ImageOps")


def _gps_jpeg(path, size=(2000, 1500), orientation=6):
    """A JPEG carrying Orientation, Make and a GPS IFD — the privacy threat model."""
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = orientation      # Orientation
    exif[0x010F] = "TestCam"        # Make
    gps = exif.get_ifd(0x8825)      # GPSInfo IFD
    gps[1] = "N"; gps[2] = (49.0, 12.0, 30.0)
    gps[3] = "E"; gps[4] = (16.0, 40.0, 0.0)
    img.save(str(path), "JPEG", exif=exif)


def test_strip_downscale_orientation(tmp_path):
    p = tmp_path / "IMG_1.jpg"
    _gps_jpeg(p)
    rep = fotky.process_folder(str(tmp_path))
    (act,) = rep["photos"]
    assert act["action"] == "processed"
    assert act["stripped_metadata"] is True
    assert act["orientation_fixed"] is True
    with Image.open(p) as back:
        assert len(back.getexif()) == 0
        assert dict(back.getexif().get_ifd(0x8825)) == {}
        # orientation=6 applied BEFORE resize: 2000x1500 landscape → portrait
        assert back.size == (900, 1200)


def test_jpeg_com_comment_detected_and_stripped(tmp_path):
    """A JPEG with no EXIF but a COM segment (Image.save(..., comment=...)) must
    not take the 'ok' short-circuit — the comment is metadata too."""
    p = tmp_path / "IMG_com.jpg"
    Image.new("RGB", (100, 80), (10, 20, 30)).save(
        str(p), "JPEG", comment=b"private note")
    with Image.open(p) as pre:
        assert pre.info.get("comment") == b"private note"  # sanity: repro is real
        assert len(pre.getexif()) == 0

    rep = fotky.process_folder(str(tmp_path))
    (act,) = rep["photos"]
    assert act["action"] == "processed"
    assert act["stripped_metadata"] is True

    with Image.open(p) as back:
        assert not back.info.get("comment")


def test_idempotent_second_run_touches_nothing(tmp_path):
    p = tmp_path / "IMG_1.jpg"
    _gps_jpeg(p)
    fotky.process_folder(str(tmp_path))
    before = p.read_bytes()
    rep2 = fotky.process_folder(str(tmp_path))
    assert [a["action"] for a in rep2["photos"]] == ["ok"]
    assert p.read_bytes() == before


def test_png_converted_to_jpeg_original_removed(tmp_path):
    Image.new("RGB", (100, 80), (0, 100, 0)).save(str(tmp_path / "cover.png"))
    rep = fotky.process_folder(str(tmp_path))
    (act,) = rep["photos"]
    assert act["action"] == "processed" and act["converted"] is True
    assert not (tmp_path / "cover.png").exists()
    out = tmp_path / "cover.jpg"
    assert out.exists() and out.read_bytes()[:2] == b"\xff\xd8"


def test_unreadable_photo_excluded_from_glob(tmp_path):
    bad = tmp_path / "IMG_bad.jpg"
    bad.write_bytes(b"not a jpeg at all")
    rep = fotky.process_folder(str(tmp_path))
    (act,) = rep["photos"]
    assert act["action"] == "excluded" and act["reason"]
    assert rep["excluded"] == ["IMG_bad.jpg"]
    assert not bad.exists()
    assert (tmp_path / ("IMG_bad.jpg" + fotky.EXCLUDED_SUFFIX)).exists()
    # renamed out of the image glob the parser uses — cannot leak into an ad
    assert parse_inzerat._list_images(str(tmp_path)) == []


def test_stem_collision_does_not_overwrite_existing_jpeg(tmp_path):
    """cover.jpg and cover.png share a stem: converting cover.png to cover.jpg
    must never clobber the real cover.jpg — the PNG is excluded instead."""
    jpg = tmp_path / "cover.jpg"
    Image.new("RGB", (80, 60), (10, 20, 30)).save(str(jpg), "JPEG", quality=90)
    original_bytes = jpg.read_bytes()

    Image.new("RGB", (100, 80), (0, 100, 0)).save(str(tmp_path / "cover.png"))

    rep = fotky.process_folder(str(tmp_path))
    by_file = {a["file"]: a for a in rep["photos"]}

    assert by_file["cover.jpg"]["action"] == "ok"
    assert jpg.read_bytes() == original_bytes  # untouched — never overwritten

    assert by_file["cover.png"]["action"] == "excluded"
    assert rep["excluded"] == ["cover.png"]
    assert not (tmp_path / "cover.png").exists()
    assert (tmp_path / ("cover.png" + fotky.EXCLUDED_SUFFIX)).exists()


def test_conversion_failure_leaves_no_temp_file(tmp_path):
    """A garbage .png that fails conversion must not leak its mkstemp'd
    .fotky-conv scratch file in the system tempdir."""
    tmpdir = tempfile.gettempdir()
    before = {n for n in os.listdir(tmpdir) if n.endswith(".fotky-conv")}

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png at all")
    rep = fotky.process_folder(str(tmp_path))

    after = {n for n in os.listdir(tmpdir) if n.endswith(".fotky-conv")}
    assert after - before == set(), (
        "conversion failure leaked a .fotky-conv temp file: "
        f"{after - before}")

    (act,) = rep["photos"]
    assert act["action"] == "excluded" and act["reason"]
    assert (tmp_path / ("bad.png" + fotky.EXCLUDED_SUFFIX)).exists()


@pytest.mark.skipif(not shutil.which("sips"),
                    reason="HEIC round-trip needs sips (macOS)")
def test_heic_converted_and_stripped(tmp_path):
    src = tmp_path / "IMG_h.jpg"
    _gps_jpeg(src, size=(1600, 1200), orientation=1)
    heic = tmp_path / "IMG_h.heic"
    subprocess.run(["sips", "-s", "format", "heic", str(src), "--out", str(heic)],
                   check=True, capture_output=True)
    src.unlink()
    rep = fotky.process_folder(str(tmp_path))
    (act,) = rep["photos"]
    assert act["action"] == "processed" and act["converted"] is True
    with Image.open(tmp_path / "IMG_h.jpg") as back:
        assert len(back.getexif()) == 0
        assert max(back.size) <= 1200
