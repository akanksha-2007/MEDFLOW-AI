"""Free nearby healthcare search using OpenStreetMap (Overpass + Nominatim).

No API key needed for either piece:
- Nominatim geocodes a text address into lat/lon (fallback when the patient
  hasn't shared GPS location).
- Overpass finds real hospitals/clinics/pharmacies/doctors/labs near a
  lat/lon, filtered by facility_type and/or medical specialty.
"""
from math import asin, cos, radians, sin, sqrt
from typing import Any, Optional
import requests

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "MediFlowHealthcareNavigation/1.0 (contact: mediflow-app)"}

# Maps a simple facility_type the patient/LLM asks for into the OSM tags
# that actually represent it. "any"/None searches every category.
FACILITY_TAG_QUERIES = {
    "hospital": ['nwr["amenity"="hospital"]'],
    "pharmacy": ['nwr["amenity"="pharmacy"]'],
    "clinic": ['nwr["amenity"="clinic"]', 'nwr["healthcare"="clinic"]'],
    "doctor": ['nwr["amenity"="doctors"]', 'nwr["healthcare"="doctor"]'],
    "diagnostic_center": ['nwr["healthcare"="laboratory"]', 'nwr["healthcare"="diagnostic_centre"]'],
}
ALL_FACILITY_QUERIES = [q for group in FACILITY_TAG_QUERIES.values() for q in group]


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 2)


def _coordinates(element: dict) -> tuple:
    if element.get("type") == "node":
        return element.get("lat"), element.get("lon")
    center = element.get("center") or {}
    return center.get("lat"), center.get("lon")


def geocode_address(address: str) -> Optional[dict]:
    """Turn a free-text address into {latitude, longitude, display_name}.
    Returns None if the address couldn't be resolved."""
    if not address or not address.strip():
        return None
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1},
            headers=HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        results = response.json()
        if not results:
            return None
        top = results[0]
        return {
            "latitude": float(top["lat"]),
            "longitude": float(top["lon"]),
            "display_name": top.get("display_name"),
        }
    except (requests.RequestException, KeyError, ValueError, IndexError):
        return None


def _run_overpass_query(query: str) -> Optional[list]:
    for url in OVERPASS_MIRRORS:
        try:
            response = requests.post(url, data={"data": query}, headers=HEADERS, timeout=20)
            response.raise_for_status()
            return response.json().get("elements", [])
        except requests.RequestException:
            continue
    return None


def _build_query(latitude: float, longitude: float, radius_m: int, facility_type: Optional[str]) -> str:
    tag_queries = FACILITY_TAG_QUERIES.get((facility_type or "").lower(), ALL_FACILITY_QUERIES)
    clauses = "\n     ".join(f'{q}(around:{radius_m},{latitude},{longitude});' for q in tag_queries)
    return f'''[out:json][timeout:20];
    ({clauses});
    out center tags;'''


def _elements_to_places(elements: list, latitude: float, longitude: float,
                         specialty_wanted: Optional[str]) -> tuple:
    """Returns (matched_places, all_places). matched_places respects the
    specialty filter; all_places ignores it — fallback so a missing OSM
    tag never means zero results."""
    matched, everything = [], []
    for element in elements:
        tags = element.get("tags", {})
        lat, lon = _coordinates(element)
        if lat is None or lon is None:
            continue

        street = " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")]))
        address = ", ".join(filter(None, [street, tags.get("addr:city"), tags.get("addr:postcode")]))
        place = {
            "name": tags.get("name") or "Unnamed healthcare facility",
            "type": (tags.get("healthcare") or tags.get("amenity") or "healthcare facility").replace("_", " ").title(),
            "specialty": tags.get("healthcare:speciality") or tags.get("speciality"),
            "address": address or None,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "distance_km": _distance_km(latitude, longitude, float(lat), float(lon)),
            "latitude": lat, "longitude": lon,
            "map_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}",
        }
        everything.append(place)

        if specialty_wanted:
            searchable = " ".join(str(tags.get(k, "")) for k in
                                   ("name", "healthcare:speciality", "speciality", "description")).casefold()
            if specialty_wanted in searchable:
                matched.append(place)

    matched.sort(key=lambda p: p["distance_km"])
    everything.sort(key=lambda p: p["distance_km"])
    return matched, everything


def search_nearby_healthcare(latitude: float, longitude: float,
                             specialty: Optional[str] = None,
                             facility_type: Optional[str] = None,
                             radius_km: float = 5, limit: int = 10) -> dict:
    """Return nearby OSM hospitals/clinics/pharmacies/doctors/labs.

    - facility_type narrows by category (hospital, pharmacy, clinic, doctor,
      diagnostic_center). None/"any" searches every category.
    - specialty narrows further by medical specialty text (e.g. "cardiology").
      If nothing matches the specialty tag (common — OSM rarely has it),
      falls back to all nearby facilities of that facility_type with a note,
      rather than returning zero results.
    - Auto-widens the radius once (up to 20km) if literally nothing is found.
    """
    radius_km = max(1, min(float(radius_km), 20))
    wanted_specialty = specialty.casefold().strip() if specialty else None
    facility_type = (facility_type or "").lower().strip() or None
    if facility_type and facility_type not in FACILITY_TAG_QUERIES and facility_type != "any":
        facility_type = None  # unknown value — fall back to searching everything

    elements = _run_overpass_query(_build_query(latitude, longitude, int(radius_km * 1000), facility_type))
    if elements is None:
        return {"error": "Nearby healthcare search is temporarily unavailable. Please try again in a moment.", "places": []}

    matched, everything = _elements_to_places(elements, latitude, longitude, wanted_specialty)

    widened = False
    if not everything and radius_km < 20:
        wider_radius_km = min(radius_km * 3, 20)
        elements = _run_overpass_query(_build_query(latitude, longitude, int(wider_radius_km * 1000), facility_type))
        if elements:
            matched, everything = _elements_to_places(elements, latitude, longitude, wanted_specialty)
            radius_km = wider_radius_km
            widened = True

    if not everything:
        return {
            "radius_km": radius_km,
            "specialty_requested": specialty,
            "facility_type_requested": facility_type,
            "places": [],
            "message": "No healthcare facilities are mapped on OpenStreetMap near this location yet. "
                       "Try a larger radius, a different facility type, or search a nearby town/city name instead.",
        }

    if wanted_specialty and matched:
        result_places, note = matched, None
    elif wanted_specialty and not matched:
        result_places = everything
        note = (f"No listing specifically tagged '{specialty}' was found on OpenStreetMap near you, "
                f"so here are all nearby matches instead — call ahead to confirm they see this specialty.")
    else:
        result_places, note = everything, None

    message = "Confirm availability and emergency suitability directly with the provider."
    if widened:
        message = f"Nothing was found in the original radius, so this list covers {radius_km:.0f} km instead. " + message
    if note:
        message = note + " " + message

    return {
        "radius_km": radius_km,
        "specialty_requested": specialty,
        "facility_type_requested": facility_type,
        "places": result_places[:max(1, min(int(limit), 20))],
        "message": message,
    }