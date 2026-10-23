from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class Event(models.Model):
    STATUS_CHOICES = [
        ("upcoming", "Upcoming"),
        ("ongoing", "Ongoing"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    title = models.CharField(max_length=200)
    venue = models.CharField(max_length=200)
    date = models.DateField()
    total_seats = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    available_seats = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="upcoming")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} at {self.venue}"

    class Meta:
        ordering = ["date", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(total_seats__gte=1), name="event_total_seats_positive"),
            models.CheckConstraint(
                condition=Q(available_seats__lte=F("total_seats")),
                name="event_available_within_total",
            ),
        ]


class Reservation(models.Model):
    STATUS_CHOICES = [("confirmed", "Confirmed"), ("cancelled", "Cancelled")]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="reservations")
    attendee_name = models.CharField(max_length=200)
    attendee_email = models.EmailField()
    seats_reserved = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="confirmed")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.attendee_name} - {self.event.title} ({self.seats_reserved} seats)"

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(seats_reserved__gte=1), name="reservation_seats_positive"
            )
        ]
