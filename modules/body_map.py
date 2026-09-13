"""
Interactive body map - REAL click, not a dropdown pretending to be a diagram.

We draw a front-view human silhouette with PIL (fully offline, no external
image download needed) and define exact pixel bounding boxes for each body
region on that same canvas. The Streamlit page uses
`streamlit_image_coordinates` to capture the (x, y) pixel the patient
actually clicks on the image, and `region_at_point()` below maps that click
to a body region. When a region is selected we redraw the image with that
region highlighted, so the patient gets instant visual feedback - the same
way a real anatomy app would work.
"""

from __future__ import annotations
from PIL import Image, ImageDraw

CANVAS_W, CANVAS_H = 340, 560

# Each region: pixel bounding box (x1, y1, x2, y2) used both for drawing
# the shape and for hit-testing clicks. Coordinates assume a front-facing
# view, so "Left" body parts (patient's own left) appear on the RIGHT half
# of the image, and vice versa - same as looking at someone facing you.
REGION_BOXES = {
    "Head":            (140, 8, 200, 68),
    "Neck":            (158, 68, 182, 86),
    "Right Shoulder":  (100, 86, 148, 122),
    "Left Shoulder":   (192, 86, 240, 122),
    "Chest":           (130, 90, 210, 168),
    "Abdomen":         (138, 168, 202, 226),
    "Right Arm":       (95, 122, 132, 258),
    "Left Arm":        (208, 122, 245, 258),
    "Right Hand":      (92, 258, 130, 292),
    "Left Hand":       (210, 258, 248, 292),
    "Right Thigh":     (136, 226, 168, 342),
    "Left Thigh":      (172, 226, 204, 342),
    "Right Knee":      (136, 342, 168, 366),
    "Left Knee":       (172, 342, 204, 366),
    "Right Calf":      (138, 366, 166, 470),
    "Left Calf":       (174, 366, 202, 470),
    "Right Foot":      (128, 470, 168, 500),
    "Left Foot":       (172, 470, 212, 500),
}

# Back/Spine cannot be shown on a front silhouette, so it's offered as a
# separate quick-select button in the UI rather than a click target.
NON_VISUAL_REGIONS = ["Back / Spine"]

REGIONS = list(REGION_BOXES.keys()) + NON_VISUAL_REGIONS

MUSCLES_BY_REGION = {
    "Left Thigh": ["Rectus Femoris", "Vastus Lateralis", "Vastus Medialis", "Vastus Intermedius", "Sartorius", "Hamstrings"],
    "Right Thigh": ["Rectus Femoris", "Vastus Lateralis", "Vastus Medialis", "Vastus Intermedius", "Sartorius", "Hamstrings"],
    "Left Calf": ["Gastrocnemius", "Soleus", "Tibialis Anterior"],
    "Right Calf": ["Gastrocnemius", "Soleus", "Tibialis Anterior"],
    "Left Arm": ["Biceps Brachii", "Triceps Brachii", "Deltoid"],
    "Right Arm": ["Biceps Brachii", "Triceps Brachii", "Deltoid"],
    "Back / Spine": ["Erector Spinae", "Trapezius", "Latissimus Dorsi"],
}

_SKIN = (247, 205, 171)
_OUTLINE = (90, 70, 60)
_SELECTED = (255, 90, 90)
_SELECTED_OUTLINE = (180, 30, 30)
_BG = (240, 246, 250)


def _rounded(draw, box, radius, fill, outline):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def render_body_image(selected_region: str | None = None) -> Image.Image:
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), _BG)
    draw = ImageDraw.Draw(img)

    def color_for(region):
        if region == selected_region:
            return _SELECTED, _SELECTED_OUTLINE
        return _SKIN, _OUTLINE

    fill, outline = color_for("Head")
    draw.ellipse(REGION_BOXES["Head"], fill=fill, outline=outline, width=2)
    if selected_region != "Head":
        hx1, hy1, hx2, hy2 = REGION_BOXES["Head"]
        cx = (hx1 + hx2) // 2
        draw.ellipse([cx - 12, hy1 + 28, cx - 6, hy1 + 34], fill=_OUTLINE)
        draw.ellipse([cx + 6, hy1 + 28, cx + 12, hy1 + 34], fill=_OUTLINE)

    fill, outline = color_for("Neck")
    draw.rectangle(REGION_BOXES["Neck"], fill=fill, outline=outline, width=2)

    for r in ["Right Shoulder", "Left Shoulder"]:
        fill, outline = color_for(r)
        draw.ellipse(REGION_BOXES[r], fill=fill, outline=outline, width=2)

    for r in ["Chest", "Abdomen"]:
        fill, outline = color_for(r)
        _rounded(draw, REGION_BOXES[r], 18, fill, outline)

    for r in ["Right Arm", "Left Arm"]:
        fill, outline = color_for(r)
        _rounded(draw, REGION_BOXES[r], 14, fill, outline)

    for r in ["Right Hand", "Left Hand"]:
        fill, outline = color_for(r)
        draw.ellipse(REGION_BOXES[r], fill=fill, outline=outline, width=2)

    for r in ["Right Thigh", "Left Thigh"]:
        fill, outline = color_for(r)
        _rounded(draw, REGION_BOXES[r], 12, fill, outline)

    for r in ["Right Knee", "Left Knee"]:
        fill, outline = color_for(r)
        draw.ellipse(REGION_BOXES[r], fill=fill, outline=outline, width=2)

    for r in ["Right Calf", "Left Calf"]:
        fill, outline = color_for(r)
        _rounded(draw, REGION_BOXES[r], 10, fill, outline)

    for r in ["Right Foot", "Left Foot"]:
        fill, outline = color_for(r)
        draw.ellipse(REGION_BOXES[r], fill=fill, outline=outline, width=2)

    return img


def region_at_point(x: int, y: int) -> str | None:
    """Map a raw pixel click to the region whose bounding box contains it.
    Falls back to the nearest region center if the click lands in a small
    gap (e.g. armpit), so near-misses still register; a click far from any
    region is ignored."""
    for region, (x1, y1, x2, y2) in REGION_BOXES.items():
        if x1 <= x <= x2 and y1 <= y <= y2:
            return region

    best_region, best_dist = None, float("inf")
    for region, (x1, y1, x2, y2) in REGION_BOXES.items():
        ccx, ccy = (x1 + x2) / 2, (y1 + y2) / 2
        dist = (ccx - x) ** 2 + (ccy - y) ** 2
        if dist < best_dist:
            best_dist, best_region = dist, region
    return best_region if best_dist ** 0.5 < 45 else None
