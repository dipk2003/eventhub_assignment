from django.db import transaction
from django.db.models import F
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Event, Reservation
from .serializers import EventSerializer, ReservationSerializer


class EventViewSet(viewsets.ModelViewSet):
    serializer_class = EventSerializer

    def get_queryset(self):
        queryset = Event.objects.all()
        status_param = self.request.query_params.get("status")
        venue_param = self.request.query_params.get("venue")
        if status_param:
            queryset = queryset.filter(status=status_param)
        if venue_param:
            queryset = queryset.filter(venue__icontains=venue_param)
        return queryset

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        # Capacity edits and booking edits share the same event lock where supported.
        event = Event.objects.select_for_update().get(pk=self.get_object().pk)
        serializer = self.get_serializer(event, data=request.data, partial=kwargs.pop("partial", False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class ReservationViewSet(viewsets.ModelViewSet):
    serializer_class = ReservationSerializer

    def get_queryset(self):
        queryset = Reservation.objects.select_related("event")
        event_id = self.request.query_params.get("event_id")
        if event_id:
            try:
                event_id = int(event_id)
                if not 1 <= event_id <= 9223372036854775807:
                    raise ValueError
            except (ValueError, TypeError):
                raise serializers.ValidationError({"event_id": "Use a positive integer event ID."})
            queryset = queryset.filter(event_id=event_id)
        return queryset

    @staticmethod
    def restore_seats(reservation):
        # Claim the cancellation once. A second cancellation cannot add seats again.
        changed = Reservation.objects.filter(pk=reservation.pk, status="confirmed").update(
            status="cancelled"
        )
        if changed:
            Event.objects.filter(pk=reservation.event_id).update(
                available_seats=F("available_seats") + reservation.seats_reserved
            )
        return changed

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def cancel(self, request, pk=None):
        reservation = Reservation.objects.select_for_update().get(pk=self.get_object().pk)
        if not self.restore_seats(reservation):
            return Response({"error": "Already cancelled."}, status=status.HTTP_400_BAD_REQUEST)
        reservation.refresh_from_db()
        return Response(self.get_serializer(reservation).data)

    @transaction.atomic
    def perform_destroy(self, instance):
        reservation = Reservation.objects.select_for_update().get(pk=instance.pk)
        self.restore_seats(reservation)
        reservation.delete()
