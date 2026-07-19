"""Free nearby healthcare search using OpenStreetMap Overpass data."""
from math import asin, cos, radians, sin, sqrt
from typing import Any, Optional
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "MediFlowHealthcareNavigation/1.0"}


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return round(2 * radius * asin(sqrt(a)), 2)


def _coordinates(element: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    if element.get("type") == "node":
        return element.get("lat"), element.get("lon")
    center = element.get("center") or {}
    return center.get("lat"), center.get("lon")


def search_nearby_healthcare(latitude: float, longitude: float,
                             specialty: Optional[str] = None,
                             radius_km: float = 5, limit: int = 10) -> dict[str, Any]:
    """Return nearby OSM doctors, clinics and hospitals. No API key needed."""
    radius_km = max(1, min(float(radius_km), 20))
    radius_m = int(radius_km * 1000)
    query = f'''[out:json][timeout:25];
    (nwr["amenity"="doctors"](around:{radius_m},{latitude},{longitude});
     nwr["amenity"="clinic"](around:{radius_m},{latitude},{longitude});
     nwr["amenity"="hospital"](around:{radius_m},{latitude},{longitude});
     nwr["healthcare"="doctor"](around:{radius_m},{latitude},{longitude});
     nwr["healthcare"="clinic"](around:{radius_m},{latitude},{longitude}););
    out center tags;'''
    try:
        response = requests.post(OVERPASS_URL, data={"data": query}, headers=HEADERS, timeout=35)
        response.raise_for_status()
        elements = response.json().get("elements", [])
    except requests.RequestException as exc:
        return {"error": "Nearby healthcare search is temporarily unavailable.", "detail": str(exc)}

    wanted = specialty.casefold() if specialty else None
    places = []
    for element in elements:
        tags = element.get("tags", {})
        lat, lon = _coordinates(element)
        if lat is None or lon is None:
            continue
        searchable = " ".join(str(tags.get(k, "")) for k in ("name", "healthcare:speciality", "speciality", "description")).casefold()
        if wanted and wanted not in searchable:
            continue
        street = " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")]))
        address = ", ".join(filter(None, [street, tags.get("addr:city"), tags.get("addr:postcode")]))
        places.append({
            "name": tags.get("name") or "Unnamed healthcare facility",
            "type": (tags.get("healthcare") or tags.get("amenity") or "healthcare facility").replace("_", " ").title(),
            "specialty": tags.get("healthcare:speciality") or tags.get("speciality"),
            "address": address or None,
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "website": tags.get("website") or tags.get("contact:website"),
            "distance_km": _distance_km(latitude, longitude, float(lat), float(lon)),
            "latitude": lat, "longitude": lon,
            "map_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}",
        })
    places.sort(key=lambda item: item["distance_km"])
    return {"radius_km": radius_km, "specialty_requested": specialty,
            "places": places[:max(1, min(int(limit), 20))],
            "message": "Confirm availability and emergency suitability directly with the provider."}
