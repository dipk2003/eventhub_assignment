from django.db import transaction
from django.db.models import F, Sum
from rest_framework import serializers

from .models import Event, Reservation


class EventSerializer(serializers.ModelSerializer):
    reservations_count = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id", "title", "venue", "date", "total_seats", "available_seats",
            "status", "created_at", "reservations_count",
        ]
        read_only_fields = ["created_at"]

    def get_reservations_count(self, obj):
        # Number of bookings, not the sum of the seats they contain.
        return obj.reservations.filter(status="confirmed").count()

    def validate(self, data):
        # PATCH can omit either field; use the saved value in that case.
        total = data.get("total_seats", getattr(self.instance, "total_seats", 0))
        available = data.get("available_seats", getattr(self.instance, "available_seats", 0))
        if available > total:
            raise serializers.ValidationError("available_seats cannot exceed total_seats.")
        if self.instance:
            booked = self.instance.reservations.filter(status="confirmed").aggregate(
                seats=Sum("seats_reserved")
            )["seats"] or 0
            if available + booked > total:
                raise serializers.ValidationError(
                    "Available seats plus confirmed reserved seats cannot exceed total_seats."
                )
        return data


class ReservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reservation
        fields = [
            "id", "event", "attendee_name", "attendee_email",
            "seats_reserved", "status", "created_at",
        ]
        read_only_fields = ["status", "created_at"]

    def validate_seats_reserved(self, value):
        if value < 1:
            raise serializers.ValidationError("Must reserve at least 1 seat.")
        return value

    @staticmethod
    def validate_booking(event, seats):
        if event.status not in ("upcoming", "ongoing"):
            raise serializers.ValidationError(f"Cannot reserve seats for a {event.status} event.")
        if seats > event.available_seats:
            raise serializers.ValidationError(f"Only {event.available_seats} seat(s) available.")

    def validate(self, data):
        if self.instance is None:
            self.validate_booking(data["event"], data["seats_reserved"])
        # Updates must account for the reservation's existing seats in update().
        return data

    @staticmethod
    def deduct_seats(event, seats):
        # Check availability and deduct in ONE SQL UPDATE, using the current DB value.
        updated = Event.objects.filter(
            pk=event.pk,
            status__in=["upcoming", "ongoing"],
            available_seats__gte=seats,
        ).update(available_seats=F("available_seats") - seats)
        if not updated:
            event.refresh_from_db()
            ReservationSerializer.validate_booking(event, seats)
            raise serializers.ValidationError("Event changed. Please try again.")

    @transaction.atomic
    def create(self, validated_data):
        self.deduct_seats(validated_data["event"], validated_data["seats_reserved"])
        return Reservation.objects.create(**validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        # Lock the reservation so an edit and cancellation cannot both change it.
        instance = Reservation.objects.select_for_update().get(pk=instance.pk)
        new_event = validated_data.get("event", instance.event)
        new_seats = validated_data.get("seats_reserved", instance.seats_reserved)
        booking_changed = new_event.pk != instance.event_id or new_seats != instance.seats_reserved

        if booking_changed:
            if instance.status == "cancelled":
                raise serializers.ValidationError(
                    "A cancelled reservation's event and seats cannot be changed. Create a new reservation."
                )
            # Acquire event locks in a consistent order on databases with row locking.
            list(Event.objects.select_for_update().filter(
                pk__in=[instance.event_id, new_event.pk]
            ).order_by("pk"))
            if new_event.pk == instance.event_id:
                difference = new_seats - instance.seats_reserved
                if difference > 0:
                    self.deduct_seats(new_event, difference)
                else:
                    Event.objects.filter(pk=instance.event_id).update(
                        available_seats=F("available_seats") - difference
                    )
            else:
                self.deduct_seats(new_event, new_seats)
                Event.objects.filter(pk=instance.event_id).update(
                    available_seats=F("available_seats") + instance.seats_reserved
                )
        return super().update(instance, validated_data)
