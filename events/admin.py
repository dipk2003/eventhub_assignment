from django.contrib import admin

from .models import Event, Reservation


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "venue", "date", "total_seats", "available_seats", "status"]
    list_filter = ["status", "date"]
    search_fields = ["title", "venue"]


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ["attendee_name", "event", "seats_reserved", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["attendee_name", "attendee_email"]

    # Reservation changes must use the API so inventory is adjusted correctly.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
