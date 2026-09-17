from django.urls import path
from bop_integration.views import BopEventGatewayView

app_name = "bop_integration"

urlpatterns = [
    path("events/", BopEventGatewayView.as_view(), name="bop_events_gateway"),
]
