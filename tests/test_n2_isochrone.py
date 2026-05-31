from graph.nodes.n2_isochrone import fetch_isochrone_candidates, route_trip_type


class FakeGMaps:
    def __init__(self) -> None:
        self.nearby_calls = []

    def geocode_location(self, address, *, settings=None):
        assert address == "Kochi"
        return {"lat": 9.9312, "lng": 76.2673, "formatted_address": "Kochi, Kerala"}

    def build_reachable_area_polygon(self, center, radius_km):
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[]]},
            "properties": {"center": center, "radius_km": radius_km},
        }

    def search_destinations_nearby(
        self,
        *,
        center,
        radius_km,
        included_types,
        settings=None,
        max_results=5,
    ):
        self.nearby_calls.append(
            {
                "center": center,
                "radius_km": radius_km,
                "included_types": included_types,
                "max_results": max_results,
            }
        )
        return [
            {
                "place_id": "palace",
                "name": "Mattancherry Palace",
                "coords": {"lat": 9.9576, "lng": 76.2596},
                "rating": 4.4,
                "types": ["tourist_attraction", "museum"],
                "description": "Historic palace.",
            },
            {
                "place_id": "beach",
                "name": "Cherai Beach",
                "coords": {"lat": 10.1412, "lng": 76.1789},
                "rating": 4.3,
                "types": ["natural_feature"],
                "description": "Beach.",
            },
            {
                "place_id": "palace",
                "name": "Mattancherry Palace",
                "coords": {"lat": 9.9576, "lng": 76.2596},
                "rating": 4.4,
                "types": ["tourist_attraction", "museum"],
                "description": "Duplicate palace.",
            },
        ]


def test_route_trip_type_routes_short_and_multiday() -> None:
    assert route_trip_type({"constraints": {"duration_hours": 14}}) == "n2_isochrone"
    assert route_trip_type({"constraints": {"duration_hours": 14.5}}) == "future_multiday"


def test_fetch_isochrone_candidates_calculates_radius_and_ranks_unique_candidates() -> None:
    fake_gmaps = FakeGMaps()

    result = fetch_isochrone_candidates(
        {
            "constraints": {
                "start_location": "Kochi",
                "duration_hours": 8,
                "group_size": 2,
                "vehicle": "car",
                "interests": ["culture", "beach"],
                "budget_feel": "medium",
            }
        },
        gmaps_client=fake_gmaps,
    )

    assert result["isochrone_polygon"]["properties"]["radius_km"] == 195.0
    assert result["candidate_index"] == 0
    assert [candidate["place_id"] for candidate in result["candidates"]] == [
        "palace",
        "beach",
    ]
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]
    assert result["candidates"][0]["distance_km"] > 0
    assert fake_gmaps.nearby_calls == [
        {
            "center": {"lat": 9.9312, "lng": 76.2673},
            "radius_km": 195.0,
            "included_types": ["museum", "place_of_worship", "art_gallery"],
            "max_results": 5,
        },
        {
            "center": {"lat": 9.9312, "lng": 76.2673},
            "radius_km": 195.0,
            "included_types": ["natural_feature"],
            "max_results": 5,
        },
    ]


def test_fetch_isochrone_candidates_uses_default_interest_when_empty() -> None:
    fake_gmaps = FakeGMaps()

    fetch_isochrone_candidates(
        {
            "constraints": {
                "start_location": "Kochi",
                "duration_hours": 4,
                "vehicle": "bike",
                "interests": [],
            }
        },
        gmaps_client=fake_gmaps,
    )

    assert fake_gmaps.nearby_calls[0]["radius_km"] == 45.0
    assert fake_gmaps.nearby_calls[0]["included_types"] == [
        "park",
        "natural_feature",
        "campground",
    ]
