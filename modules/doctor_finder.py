"""
Real, location-based doctor/clinic finder — no mock lists.

Search order:
  1. If a Google Maps API key (GOOGLE_MAPS_API_KEY) is configured, use
     Google Geocoding + Google Places Text Search (most reliable, worldwide).
  2. Otherwise use the free OpenStreetMap services:
     - Nominatim  -> turns a place name ("Bahawalpur", "Model Town Lahore")
                     into latitude/longitude.
     - Overpass   -> searches OSM for real doctors/clinics/hospitals within
                     a radius, across multiple public mirrors (they are often
                     busy, so we fail over between them).

Results include the real place name, address, straight-line distance, and a
ready-to-open Google Maps directions link.

Both services require internet at RUN TIME; every step degrades gracefully
(empty results + a reason) instead of crashing.
"""

from __future__ import annotations
import math
import os
import time

import requests
import streamlit as st

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"

# Order matters: overpass-api.de gave the best real results in testing.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"          # legacy
GOOGLE_PLACES_NEW_URL = "https://places.googleapis.com/v1/places:searchText"              # Places API (New)
GOOGLE_ORIGIN_HEADERS = {"User-Agent": "NeuroGuardAI/1.0 (contact: dev@neuroguard.ai)"}

HTTP_TIMEOUT = 20          # geocoding
OVERPASS_TIMEOUT = 30      # Overpass queries can be slow — keep sane

NOMINATIM_EMAIL = "dev@neuroguard.ai"


# Map our internal specialty labels to OpenStreetMap healthcare:speciality
# tag values worth trying (best-effort - not every clinic in OSM is tagged
# this precisely, so we fall back to general hospitals/clinics if a
# specialty-tagged search comes back empty).
SPECIALTY_OSM_TAGS = {
    "Neurologist": ["neurology"],
    "Neurologist (Neuromuscular specialist)": ["neurology"],
    "Orthopedic Specialist / Physiotherapist": ["orthopaedics", "orthopedics", "physiotherapy"],
    "Vascular Specialist / General Physician": ["vascular_surgery", "general practitioner", "general"],
    "Emergency Department - go immediately": [],  # handled separately - hospitals only
}

# Same labels -> natural-language query for the optional Google Places branch.
SPECIALTY_GOOGLE_QUERIES = {
    "Neurologist": "neurologist clinic hospital",
    "Neurologist (Neuromuscular specialist)": "neurology specialist clinic",
    "Orthopedic Specialist / Physiotherapist": "orthopedic clinic physiotherapist",
    "Vascular Specialist / General Physician": "vascular doctor clinic",
    "Emergency Department - go immediately": "hospital emergency department",
}
SPECIALTY_GOOGLE_TYPES = {
    "Emergency Department - go immediately": "hospital",
}


def _secret(key: str, default: str = "") -> str:
    try:
        v = st.secrets.get(key)
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(key, default)


def _google_maps_key() -> str:
    # NOTE: the Gemini GEMINI_API_KEY does NOT work for Maps/Places — a
    # separate key with Maps APIs enabled is required for this branch.
    return _secret("GOOGLE_MAPS_API_KEY")


def google_maps_key_configured() -> bool:
    return bool(_google_maps_key())


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ── geocoding ────────────────────────────────────────────────────────────

def _geocode_google(place_text: str, key: str):
    try:
        r = requests.get(
            GOOGLE_GEOCODE_URL,
            params={"address": place_text, "key": key},
            headers=GOOGLE_ORIGIN_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        data = r.json()
        if data.get("status") == "OK" and data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            return float(loc["lat"]), float(loc["lng"]), data["results"][0].get("formatted_address", place_text)
    except Exception:
        pass
    return None


def _geocode_nominatim(place_text: str):
    params = {"q": place_text, "format": "json", "limit": 1, "email": NOMINATIM_EMAIL}
    for attempt in range(2):
        try:
            r = requests.get(NOMINATIM_URL, params=params, timeout=HTTP_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if data:
                    return (
                        float(data[0]["lat"]),
                        float(data[0]["lon"]),
                        data[0].get("display_name", place_text),
                    )
        except requests.RequestException:
            time.sleep(1.5)
    return None


def _geocode_photon(place_text: str):
    """Free key-less geocoder (Komoot Photon).  Used only as a last resort —
    it can pick the wrong country for ambiguous city names, so Nominatim is
    preferred and this fills the gap when Nominatim rate-limits us."""
    try:
        r = requests.get(
            PHOTON_URL,
            params={"q": place_text, "limit": 5},
            headers=GOOGLE_ORIGIN_HEADERS,
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
        features = r.json().get("features", [])
        for f in features:
            props = f.get("properties", {}) or {}
            # skip street-level junk like bus stops / highways
            if props.get("osm_key") in ("highway", "man_made"):
                continue
            coords = f.get("geometry", {}).get("coordinates")
            if not coords:
                continue
            place_parts = [props.get("name"), props.get("city"), props.get("state"), props.get("country")]
            display = ", ".join(p for p in place_parts if p) or place_text
            return float(coords[1]), float(coords[0]), display
        return None
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=3600)
def geocode_location(place_text: str):
    """Returns (lat, lon, display_name) or None if not found / request failed."""
    if not place_text or not place_text.strip():
        return None
    gkey = _google_maps_key()
    if gkey:
        result = _geocode_google(place_text, gkey)
        if result:
            return result
    result = _geocode_nominatim(place_text)
    if result:
        return result
    return _geocode_photon(place_text)


# ── facility search ──────────────────────────────────────────────────────

def _overpass_query(radius_m: int, lat: float, lon: float, extra_filter: str = "") -> str:
    return (
        "[out:json][timeout:25];"
        "("
        f'node["amenity"~"doctors|clinic|hospital"]{extra_filter}(around:{radius_m},{lat},{lon});'
        f'way["amenity"~"doctors|clinic|hospital"]{extra_filter}(around:{radius_m},{lat},{lon});'
        ");"
        "out center 30;"
    )


def _overpass_request(mirror: str, query: str) -> list:
    r = requests.post(
        mirror,
        data={"data": query},
        headers={"User-Agent": "NeuroGuardAI/1.0 (contact: dev@neuroguard.ai)"},
        timeout=OVERPASS_TIMEOUT,
    )
    if r.status_code != 200:
        raise requests.RequestException(f"Overpass HTTP {r.status_code}")
    return r.json().get("elements", [])


def _parse_elements(elements: list, lat: float, lon: float) -> list:
    results = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        if not name:
            continue
        elat = el.get("lat") or (el.get("center") or {}).get("lat")
        elon = el.get("lon") or (el.get("center") or {}).get("lon")
        if elat is None or elon is None:
            continue
        amenity = tags.get("amenity", "clinic")
        addr_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:city"),
        ]
        address = ", ".join(p for p in addr_parts if p) or "Address not listed in OpenStreetMap"
        results.append({
            "name": name,
            "type": amenity.replace("_", " ").title(),
            "address": address,
            "distance_km": round(haversine_km(lat, lon, float(elat), float(elon)), 1),
            "maps_link": f"https://www.google.com/maps/search/?api=1&query={float(elat)},{float(elon)}",
        })
    results.sort(key=lambda r: r["distance_km"])
    return results[:8]


def _search_overpass(lat: float, lon: float, specialty_label: str, radius_km: float) -> dict:
    radius_m = int(radius_km * 1000)
    tags = SPECIALTY_OSM_TAGS.get(specialty_label, [])

    specialty_query = None
    if tags:
        regex = "|".join(tags)
        specialty_query = _overpass_query(
            radius_m, lat, lon,
            f'["healthcare:speciality"~"{regex}",i]',
        )
    general_query = _overpass_query(radius_m, lat, lon)

    responded = 0  # healthy HTTP responses (even if empty)
    last_error = None

    for mirror in OVERPASS_MIRRORS:
        # 1) specialty-tagged search (if applicable)
        if specialty_query:
            try:
                elements = _overpass_request(mirror, specialty_query)
                responded += 1
                parsed = _parse_elements(elements, lat, lon)
                if parsed:
                    return {"results": parsed, "fallback_used": False, "error": None}
            except Exception as e:  # mirror down / overloaded → skip the general pass too
                last_error = e
                continue

        # 2) general clinics/hospitals fallback (only on a healthy mirror)
        try:
            elements = _overpass_request(mirror, general_query)
            responded += 1
            parsed = _parse_elements(elements, lat, lon)
            if parsed:
                return {"results": parsed, "fallback_used": True, "error": None}
        except Exception as e:
            last_error = e

    if responded:
        return {
            "results": [],
            "fallback_used": bool(specialty_query),
            "error": ("No clinics/hospitals found in OpenStreetMap data within this radius. "
                      "Try a larger radius or a more specific location."),
        }
    return {
        "results": [],
        "fallback_used": False,
        "error": (
            "Could not reach the clinic/hospital search services (they can be busy). "
            f"({last_error.__class__.__name__}) — check your internet connection and try again."
        ),
    }


def _search_google_legacy(lat: float, lon: float, specialty_label: str, radius_km: float, key: str) -> dict:
    query_text = SPECIALTY_GOOGLE_QUERIES.get(specialty_label, "doctor clinic hospital")
    params = {
        "query": query_text,
        "location": f"{lat},{lon}",
        "radius": int(radius_km * 1000),
        "key": key,
    }
    if specialty_label in SPECIALTY_GOOGLE_TYPES:
        params["type"] = SPECIALTY_GOOGLE_TYPES[specialty_label]

    try:
        r = requests.get(GOOGLE_PLACES_URL, params=params, headers=GOOGLE_ORIGIN_HEADERS, timeout=HTTP_TIMEOUT)
        data = r.json()
        if data.get("status") != "OK":
            return {"results": [], "fallback_used": False,
                    "error": f"Google Places legacy: {data.get('status')} — {data.get('error_message', '')}".strip()}
        results = []
        for place in data.get("results", []):
            if place.get("business_status") == "CLOSED_PERMANENTLY":
                continue
            glm = place["geometry"]["location"]
            plat, plon = float(glm["lat"]), float(glm["lng"])
            dist = haversine_km(lat, lon, plat, plon)
            if dist > radius_km * 1.25:  # API biases, we keep only genuinely nearby
                continue
            name = place.get("name", "Medical facility")
            results.append({
                "name": name,
                "type": "Clinic / Hospital",
                "address": place.get("formatted_address", "Address unknown"),
                "distance_km": round(dist, 1),
                "maps_link": (
                    f"https://www.google.com/maps/search/?api=1&query={plat},{plon}"
                    + (f"&query_place_id={place['place_id']}" if place.get("place_id") else "")
                ),
            })
        results.sort(key=lambda x: x["distance_km"])
        return {"results": results[:8], "fallback_used": False, "error": None}
    except Exception as e:
        return {"results": [], "fallback_used": False, "error": f"Google Places legacy request failed: {e.__class__.__name__}"}


def _search_google_new(lat: float, lon: float, specialty_label: str, radius_km: float, key: str) -> dict:
    """Places API (New) — the current, non-legacy endpoint.  Uses the
    X-Goog-Api-Key header and POST JSON body (modern auth for AIza keys too)."""
    query_text = SPECIALTY_GOOGLE_QUERIES.get(specialty_label, "doctor clinic hospital")
    body = {
        "textQuery": f"{query_text} near me",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lon},
                "radius": float(radius_km * 1000),
            }
        },
    }
    try:
        r = requests.post(
            GOOGLE_PLACES_NEW_URL,
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,"
                                    "places.location,places.rating,places.businessStatus,places.primaryType",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            msg = ""
            try:
                msg = r.json().get("error", {}).get("message", "")
            except Exception:
                pass
            return {"results": [], "fallback_used": False,
                    "error": f"Google Places (New) HTTP {r.status_code} — {msg}".strip()}
        data = r.json()
        results = []
        for place in data.get("places", []):
            if place.get("businessStatus") == "CLOSED_PERMANENTLY":
                continue
            loc = place.get("location", {})
            plat = float(loc.get("latitude") or loc.get("lat") or 0)
            plon = float(loc.get("longitude") or loc.get("lng") or 0)
            dist = haversine_km(lat, lon, plat, plon)
            if dist > radius_km * 1.25:
                continue
            name = (place.get("displayName") or {}).get("text") or "Medical facility"
            place_id = place.get("id", "")
            results.append({
                "name": name,
                "type": (place.get("primaryType") or "clinic").replace("_", " ").title(),
                "address": place.get("formattedAddress", "Address unknown"),
                "distance_km": round(dist, 1),
                "maps_link": (
                    f"https://www.google.com/maps/search/?api=1&query={plat},{plon}"
                    + (f"&query_place_id={place_id}" if place_id else "")
                ),
            })
        results.sort(key=lambda x: x["distance_km"])
        return {"results": results[:8], "fallback_used": False, "error": None}
    except Exception as e:
        return {"results": [], "fallback_used": False, "error": f"Google Places (New) request failed: {e.__class__.__name__}"}


def _search_google(lat: float, lon: float, specialty_label: str, radius_km: float, key: str) -> dict:
    """Try Places API (New) first, then legacy Text Search.  Returns the first
    successful (error-free) response, even if it has zero results."""
    new_result = _search_google_new(lat, lon, specialty_label, radius_km, key)
    if new_result["error"] is None:
        return new_result
    legacy_result = _search_google_legacy(lat, lon, specialty_label, radius_km, key)
    if legacy_result["error"] is None:
        return legacy_result
    # both failed (e.g. APIs not enabled) — report the more helpful error
    return new_result


@st.cache_data(show_spinner=False, ttl=1800)
def find_nearby_care(lat: float, lon: float, specialty_label: str, radius_km: float = 15) -> dict:
    """Returns {"results": [...], "fallback_used": bool, "error": str|None}."""
    gkey = _google_maps_key()
    if gkey:
        google_result = _search_google(lat, lon, specialty_label, radius_km, gkey)
        if google_result.get("results") or not google_result.get("error"):
            return google_result
        # Google failed → silently fall through to OSM
    return _search_overpass(lat, lon, specialty_label, radius_km)