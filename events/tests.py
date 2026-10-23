from datetime import timedelta
from unittest.mock import patch

from django.db import IntegrityError
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, APITestCase

from .middleware import RequestLoggingMiddleware
from .models import Event, Reservation
from .serializers import ReservationSerializer


class EventHubAPITests(APITestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Python Workshop", venue="Delhi Community Hall",
            date=timezone.localdate() + timedelta(days=30),
            total_seats=10, available_seats=10,
        )
        self.events_url = reverse("event-list")
        self.reservations_url = reverse("reservation-list")

    def booking_data(self, **changes):
        data = {
            "event": self.event.pk, "attendee_name": "Priya Sharma",
            "attendee_email": "priya@example.com", "seats_reserved": 2,
        }
        data.update(changes)
        return data

    def book(self, **changes):
        response = self.client.post(self.reservations_url, self.booking_data(**changes), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data

    def available_seats(self):
        self.event.refresh_from_db()
        return self.event.available_seats

    def test_api_root_and_home(self):
        self.assertEqual(self.client.get("/").url, "/api/")
        self.assertEqual(self.client.get("/api/").status_code, 200)

    def test_create_event(self):
        response = self.client.post(self.events_url, {
            "title": "Music Night", "venue": "Mumbai",
            "date": "2030-12-20", "total_seats": 100, "available_seats": 100,
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["reservations_count"], 0)
        self.assertEqual(response.data["status"], "upcoming")

    def test_event_filters_can_be_combined_and_ignore_venue_case(self):
        Event.objects.create(title="Other", venue="Mumbai", date=self.event.date,
                             total_seats=1, available_seats=1, status="completed")
        self.assertEqual(len(self.client.get(self.events_url).data), 2)
        response = self.client.get(self.events_url, {"status": "upcoming", "venue": "DELHI"})
        self.assertEqual([event["id"] for event in response.data], [self.event.pk])
        self.assertEqual(len(self.client.get(self.events_url, {"status": "completed"}).data), 1)

    def test_event_partial_update_validates_against_saved_values(self):
        url = reverse("event-detail", args=[self.event.pk])
        self.assertEqual(self.client.patch(url, {"title": "New title"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"available_seats": 11}, format="json").status_code, 400)
        self.assertEqual(self.client.patch(url, {"total_seats": 9}, format="json").status_code, 400)

    def test_invalid_event_capacity_is_rejected(self):
        for total, available in [(0, 0), (5, 6), (5, -1)]:
            with self.subTest(total=total, available=available):
                response = self.client.post(self.events_url, {
                    "title": "Invalid", "venue": "Delhi", "date": "2030-12-20",
                    "total_seats": total, "available_seats": available,
                }, format="json")
                self.assertEqual(response.status_code, 400)

    def test_reservation_deducts_seats_and_count_counts_bookings(self):
        self.book(seats_reserved=3, status="cancelled")
        self.assertEqual(self.available_seats(), 7)
        response = self.client.get(reverse("event-detail", args=[self.event.pk]))
        self.assertEqual(response.data["reservations_count"], 1)
        self.assertEqual(Reservation.objects.get().status, "confirmed")

    def test_booking_every_remaining_seat_is_allowed(self):
        self.book(seats_reserved=10)
        self.assertEqual(self.available_seats(), 0)

    def test_overbooking_does_not_change_database(self):
        self.book(seats_reserved=9)
        response = self.client.post(self.reservations_url, self.booking_data(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only 1 seat(s) available.", response.data["non_field_errors"])
        self.assertEqual(self.available_seats(), 1)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_zero_negative_and_invalid_email_are_rejected(self):
        for changes in [{"seats_reserved": 0}, {"seats_reserved": -1}, {"attendee_email": "bad"}]:
            with self.subTest(changes=changes):
                response = self.client.post(self.reservations_url, self.booking_data(**changes), format="json")
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.available_seats(), 10)
        self.assertFalse(Reservation.objects.exists())

    def test_nonexistent_event_and_missing_fields_are_rejected(self):
        self.assertEqual(self.client.post(self.reservations_url, self.booking_data(event=9999), format="json").status_code, 400)
        self.assertEqual(self.client.post(self.reservations_url, {}, format="json").status_code, 400)

    def test_completed_and_cancelled_events_cannot_be_booked(self):
        for event_status in ["completed", "cancelled"]:
            self.event.status = event_status
            self.event.save()
            response = self.client.post(self.reservations_url, self.booking_data(), format="json")
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.available_seats(), 10)

    def test_ongoing_event_can_be_booked(self):
        self.event.status = "ongoing"
        self.event.save()
        self.book()
        self.assertEqual(self.available_seats(), 8)

    def test_cancel_restores_seats_once_and_updates_count(self):
        booking = self.book()
        url = reverse("reservation-cancel", args=[booking["id"]])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(self.available_seats(), 10)
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"error": "Already cancelled."})
        self.assertEqual(self.available_seats(), 10)
        event = self.client.get(reverse("event-detail", args=[self.event.pk])).data
        self.assertEqual(event["reservations_count"], 0)

    def test_missing_records_return_404(self):
        self.assertEqual(self.client.get(reverse("event-detail", args=[9999])).status_code, 404)
        self.assertEqual(self.client.post(reverse("reservation-cancel", args=[9999])).status_code, 404)

    def test_reservation_event_filter_and_invalid_filter(self):
        self.book()
        self.assertEqual(len(self.client.get(self.reservations_url, {"event_id": self.event.pk}).data), 1)
        self.assertEqual(self.client.get(self.reservations_url, {"event_id": 9999}).data, [])
        for event_id in ["abc", "0", "-1", "999999999999999999999999"]:
            self.assertEqual(self.client.get(self.reservations_url, {"event_id": event_id}).status_code, 400)

    def test_attendee_patch_does_not_change_inventory(self):
        booking = self.book()
        response = self.client.patch(reverse("reservation-detail", args=[booking["id"]]),
                                     {"attendee_name": "Updated name"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["attendee_name"], "Updated name")
        self.assertEqual(self.available_seats(), 8)

    def test_booking_seat_updates_adjust_only_the_difference(self):
        booking = self.book()
        url = reverse("reservation-detail", args=[booking["id"]])
        self.assertEqual(self.client.patch(url, {"seats_reserved": 5}, format="json").status_code, 200)
        self.assertEqual(self.available_seats(), 5)
        self.assertEqual(self.client.patch(url, {"seats_reserved": 1}, format="json").status_code, 200)
        self.assertEqual(self.available_seats(), 9)
        self.assertEqual(self.client.patch(url, {"seats_reserved": 11}, format="json").status_code, 400)
        self.assertEqual(self.available_seats(), 9)
        self.assertEqual(Reservation.objects.get().seats_reserved, 1)

    def test_full_reservation_update(self):
        booking = self.book()
        response = self.client.put(reverse("reservation-detail", args=[booking["id"]]),
                                   self.booking_data(seats_reserved=4), format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.available_seats(), 6)

    def test_moving_reservation_restores_old_event_seats(self):
        booking = self.book()
        other = Event.objects.create(title="Other", venue="Goa", date=self.event.date,
                                     total_seats=5, available_seats=5)
        response = self.client.patch(reverse("reservation-detail", args=[booking["id"]]),
                                     {"event": other.pk, "seats_reserved": 3}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.available_seats(), 10)
        other.refresh_from_db()
        self.assertEqual(other.available_seats, 2)

    def test_failed_move_leaves_both_events_and_booking_unchanged(self):
        booking = self.book()
        other = Event.objects.create(title="Small", venue="Goa", date=self.event.date,
                                     total_seats=1, available_seats=1)
        response = self.client.patch(reverse("reservation-detail", args=[booking["id"]]),
                                     {"event": other.pk}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.available_seats(), 8)
        other.refresh_from_db()
        self.assertEqual(other.available_seats, 1)
        self.assertEqual(Reservation.objects.get().event_id, self.event.pk)

    def test_cancelled_booking_cannot_be_reactivated_or_change_seats(self):
        booking = self.book()
        self.client.post(reverse("reservation-cancel", args=[booking["id"]]))
        url = reverse("reservation-detail", args=[booking["id"]])
        self.assertEqual(self.client.patch(url, {"seats_reserved": 3}, format="json").status_code, 400)
        response = self.client.patch(url, {"attendee_name": "Corrected", "status": "confirmed"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")
        self.assertEqual(self.available_seats(), 10)

    def test_delete_confirmed_booking_restores_seats(self):
        booking = self.book()
        response = self.client.delete(reverse("reservation-detail", args=[booking["id"]]))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.available_seats(), 10)
        self.assertFalse(Reservation.objects.exists())

    def test_delete_cancelled_booking_does_not_restore_seats_twice(self):
        booking = self.book()
        self.client.post(reverse("reservation-cancel", args=[booking["id"]]))
        self.client.delete(reverse("reservation-detail", args=[booking["id"]]))
        self.assertEqual(self.available_seats(), 10)

    def test_event_delete_cascades_to_reservations(self):
        self.book()
        self.assertEqual(self.client.delete(reverse("event-detail", args=[self.event.pk])).status_code, 204)
        self.assertFalse(Reservation.objects.exists())

    def test_event_capacity_cannot_exclude_existing_bookings(self):
        self.book(seats_reserved=3)
        url = reverse("event-detail", args=[self.event.pk])
        response = self.client.patch(url, {"available_seats": 10}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.available_seats(), 7)
        self.assertEqual(self.client.patch(url, {"total_seats": 5}, format="json").status_code, 400)

    def test_stale_validated_requests_cannot_oversell(self):
        # Both requests validate before either saves: simulates stale availability.
        first = ReservationSerializer(data=self.booking_data(seats_reserved=6))
        second = ReservationSerializer(data=self.booking_data(seats_reserved=6))
        self.assertTrue(first.is_valid(), first.errors)
        self.assertTrue(second.is_valid(), second.errors)
        first.save()
        with self.assertRaises(serializers.ValidationError):
            second.save()
        self.assertEqual(self.available_seats(), 4)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_status_change_after_validation_is_checked_again(self):
        serializer = ReservationSerializer(data=self.booking_data())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        Event.objects.filter(pk=self.event.pk).update(status="cancelled")
        with self.assertRaises(serializers.ValidationError):
            serializer.save()
        self.assertEqual(self.available_seats(), 10)

    def test_failed_reservation_insert_rolls_back_seat_deduction(self):
        serializer = ReservationSerializer(data=self.booking_data())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with patch("events.serializers.Reservation.objects.create", side_effect=IntegrityError("insert failed")):
            with self.assertRaises(IntegrityError):
                serializer.save()
        self.assertEqual(self.available_seats(), 10)
        self.assertFalse(Reservation.objects.exists())


class RequestLoggingTests(SimpleTestCase):
    def test_logs_method_path_status_and_duration(self):
        middleware = RequestLoggingMiddleware(lambda request: Response(status=201))
        request = APIRequestFactory().post("/api/reservations/")
        with self.assertLogs("events.middleware", level="INFO") as captured:
            response = middleware(request)
        self.assertEqual(response.status_code, 201)
        self.assertRegex(captured.output[0], r"POST /api/reservations/ - 201 - \d+\.\d{2}s")
