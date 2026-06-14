from django.urls import path
from .views import AnalyzeMatchView, HealthCheckView

urlpatterns = [
    path('analyze/', AnalyzeMatchView.as_view(), name='analyze-match'),
    path('health/', HealthCheckView.as_view(), name='health-check'),
]
