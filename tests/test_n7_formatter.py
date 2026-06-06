from graph.nodes.n7_formatter import format_final_output


def base_state() -> dict:
    return {
        "route": {
            "geojson": {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[76.2673, 9.9312], [76.5696, 10.2859]],
                },
                "properties": {
                    "type": "route",
                    "distance_meters": 82000,
                },
            }
        },
        "timeline": [
            {
                "time": "07:00",
                "label": "Depart Kochi",
                "coords": {"lat": 9.9312, "lng": 76.2673},
                "type": "start",
                "notes": "Start the trip.",
            },
            {
                "time": "08:00",
                "label": "Athirappilly Falls",
                "coords": {"lat": 10.2859, "lng": 76.5696},
                "type": "destination",
                "notes": "Spend 2 hr here.",
            },
            {
                "time": "11:00",
                "label": "Back at Kochi",
                "coords": {"lat": 9.9312, "lng": 76.2673},
                "type": "return",
                "notes": "Trip ends.",
            },
        ],
        "itinerary_draft": "Morning: Leave Kochi at 07:00 and return by 11:00.",
    }


def test_formatter_builds_feature_collection_from_route_and_timeline() -> None:
    result = format_final_output(base_state())

    assert result["final_itinerary"] == (
        "Morning: Leave Kochi at 07:00 and return by 11:00."
    )
    assert result["final_geojson"] == {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[76.2673, 9.9312], [76.5696, 10.2859]],
                },
                "properties": {
                    "type": "route",
                    "distance_meters": 82000,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [76.2673, 9.9312]},
                "properties": {
                    "type": "waypoint",
                    "stop_type": "start",
                    "label": "Depart Kochi",
                    "time": "07:00",
                    "notes": "Start the trip.",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [76.5696, 10.2859]},
                "properties": {
                    "type": "waypoint",
                    "stop_type": "destination",
                    "label": "Athirappilly Falls",
                    "time": "08:00",
                    "notes": "Spend 2 hr here.",
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [76.2673, 9.9312]},
                "properties": {
                    "type": "waypoint",
                    "stop_type": "return",
                    "label": "Back at Kochi",
                    "time": "11:00",
                    "notes": "Trip ends.",
                },
            },
        ],
    }


def test_formatter_skips_invalid_timeline_coords() -> None:
    state = base_state()
    state["timeline"].append(
        {
            "time": "09:00",
            "label": "Invalid stop",
            "coords": {},
            "type": "food",
            "notes": "Missing coordinates.",
        }
    )

    result = format_final_output(state)

    assert len(result["final_geojson"]["features"]) == 4
    assert all(
        feature["properties"].get("label") != "Invalid stop"
        for feature in result["final_geojson"]["features"]
    )


def test_formatter_handles_missing_route_line() -> None:
    state = base_state()
    state["route"] = {}

    result = format_final_output(state)

    assert result["final_geojson"]["type"] == "FeatureCollection"
    assert [feature["geometry"]["type"] for feature in result["final_geojson"]["features"]] == [
        "Point",
        "Point",
        "Point",
    ]


def test_formatter_defaults_empty_itinerary_to_blank_string() -> None:
    state = base_state()
    state["itinerary_draft"] = ""

    result = format_final_output(state)

    assert result["final_itinerary"] == ""
