"""Photo prep for bazos-priprava-inzeratu: EXIF/GPS strip, orientation fix,
downscale, JPEG conversion — in place over a prodej/<x>/ folder.

The folder is an export-for-sale copy, not a photo archive: files are
overwritten with their cleaned version (the skill tells users to copy photos
in, not move them). A photo that cannot be opened, or whose metadata survives
a re-save, is EXCLUDED from the ad — renamed out of the image glob with the
``.vyrazeno`` suffix — never silently passed through (home photos carry GPS).

Idempotent: an already-clean JPEG (no metadata, within the size cap) reports
``action: "ok"`` and its bytes are not touched.
"""

import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps

import ad_schema

DEFAULT_MAX_EDGE = 1200
JPEG_QUALITY = 85
EXCLUDED_SUFFIX = ".vyrazeno"  # not an image extension → parse_inzerat skips it


def convert_to_jpeg(src, dst):
    """Convert ``src`` to a JPEG at ``dst`` — sips first (macOS; handles HEIC,
    which stock Pillow cannot open), Pillow otherwise."""
    if shutil.which("sips"):
        subprocess.run(["sips", "-s", "format", "jpeg", src, "--out", dst],
                       check=True, capture_output=True)
        return
    Image.open(src).convert("RGB").save(dst, "JPEG", quality=90)


def _has_metadata(img):
    """EXIF (incl. the GPS IFD), a raw exif/xmp payload, IPTC (Photoshop), or a
    JPEG COM comment segment present?"""
    return len(img.getexif()) > 0 or bool(
        img.info.get("exif") or img.info.get("xmp")
        or img.info.get("photoshop") or img.info.get("comment"))


def process_photo(path, max_edge=DEFAULT_MAX_EDGE):
    """Clean one photo in place; return its report entry.

    Raises on anything that cannot be cleaned — process_folder turns a raise
    into an exclusion. Temp files use non-image suffixes so a crash can never
    leave a stray file that the ad's image glob would pick up.
    """
    name = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    is_jpeg = ext in ad_schema.JPEG_EXTS

    src, tmp_converted = path, None
    if not is_jpeg:  # HEIC/PNG/WebP → JPEG first, then clean like any JPEG
        fd, tmp_converted = tempfile.mkstemp(suffix=".fotky-conv")
        os.close(fd)
        src = tmp_converted
    try:
        if tmp_converted:
            convert_to_jpeg(path, tmp_converted)
        with Image.open(src) as img:
            had_metadata = _has_metadata(img)
            orientation = img.getexif().get(0x0112, 1)
            if is_jpeg and not had_metadata and max(img.size) <= max_edge:
                return {"file": name, "action": "ok"}
            out = ImageOps.exif_transpose(img)
            resized = max(out.size) > max_edge
            if resized:
                out.thumbnail((max_edge, max_edge))
            if out.mode != "RGB":
                out = out.convert("RGB")
            # PIL's JPEG encoder falls back to im.info's comment/photoshop
            # payload when the caller doesn't override it — drop them here or
            # they silently ride along into the "cleaned" file.
            out.info.pop("comment", None)
            out.info.pop("photoshop", None)
            dst = path if is_jpeg else os.path.splitext(path)[0] + ".jpg"
            fd, tmp_out = tempfile.mkstemp(suffix=".fotky-tmp",
                                           dir=os.path.dirname(path) or ".")
            os.close(fd)
            try:
                out.save(tmp_out, "JPEG", quality=JPEG_QUALITY)  # no exif= → dropped
            except Exception:
                os.unlink(tmp_out)
                raise
            size = list(out.size)
    finally:
        if tmp_converted and os.path.exists(tmp_converted):
            os.unlink(tmp_converted)

    with Image.open(tmp_out) as check:  # verify the strip actually took
        if _has_metadata(check):
            os.unlink(tmp_out)
            raise RuntimeError("metadata survived the re-save")

    if dst != path and os.path.exists(dst):
        # a different file already occupies the converted stem (e.g. both
        # photo1.jpg and photo1.png present) — never silently clobber it
        os.unlink(tmp_out)
        raise RuntimeError(
            f"conversion target {os.path.basename(dst)} already exists "
            "(stem collision) — refusing to overwrite it")

    os.replace(tmp_out, dst)
    if dst != path:
        os.remove(path)  # the original non-JPEG, already re-encoded into dst
    return {"file": name, "action": "processed",
            "output": os.path.basename(dst),
            "stripped_metadata": had_metadata,
            "orientation_fixed": orientation != 1,
            "resized_to": size if resized else None,
            "converted": dst != path}


def process_folder(folder, max_edge=DEFAULT_MAX_EDGE):
    """Clean every photo in ``folder`` in place; return the JSON report."""
    names = sorted(
        (n for n in os.listdir(folder)
         if os.path.splitext(n)[1].lower()
         in ad_schema.JPEG_EXTS | ad_schema.CONVERTIBLE_EXTS),
        key=str.lower)
    entries = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            entries.append(process_photo(path, max_edge))
        except Exception as e:  # unopenable / unconvertible / strip failed
            os.replace(path, path + EXCLUDED_SUFFIX)
            entries.append({"file": name, "action": "excluded",
                            "reason": str(e),
                            "moved_to": name + EXCLUDED_SUFFIX})
    return {"folder": folder, "max_edge": max_edge, "photos": entries,
            "excluded": [e["file"] for e in entries if e["action"] == "excluded"]}
