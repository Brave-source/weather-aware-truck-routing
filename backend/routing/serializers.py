from rest_framework import serializers
from math import isfinite


class RouteAnalysisRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=300)
    destination = serializers.CharField(max_length=300)
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0)
    checkpoint_interval_miles = serializers.ChoiceField(choices=(10, 25, 50))


class LocationSuggestionRequestSerializer(serializers.Serializer):
    q = serializers.CharField(min_length=3, max_length=256, trim_whitespace=True)


class CorridorForecastRequestSerializer(serializers.Serializer):
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField(min_value=0)
    forecast_offset_hours = serializers.IntegerField(min_value=0, max_value=48)
    checkpoints = serializers.ListField(child=serializers.DictField(), allow_empty=False)

    def validate_checkpoints(self, checkpoints):
        if len(checkpoints) > 2000:
            raise serializers.ValidationError("A corridor forecast is limited to 2,000 checkpoints.")
        route_ids = set()
        for checkpoint in checkpoints:
            route_id = checkpoint.get("route_id")
            if not isinstance(route_id, str) or not route_id:
                raise serializers.ValidationError("Each checkpoint needs a route_id.")
            route_ids.add(route_id)
            try:
                longitude = float(checkpoint["longitude"])
                latitude = float(checkpoint["latitude"])
                mile = float(checkpoint["mile"])
            except (KeyError, TypeError, ValueError):
                raise serializers.ValidationError("Each checkpoint needs numeric mile and coordinates.")
            if not all(isfinite(value) for value in (longitude, latitude, mile)) or mile < 0:
                raise serializers.ValidationError("Checkpoint mile and coordinate values must be finite; mile cannot be negative.")
            if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
                raise serializers.ValidationError("Checkpoint coordinates are outside valid bounds.")
        if len(route_ids) > 3:
            raise serializers.ValidationError("At most three routes can be analyzed at once.")
        return checkpoints
