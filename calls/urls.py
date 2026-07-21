from django.urls import path
from . import views, frontend_views

urlpatterns = [
    # JSON API (Vapi)
    path("api/vapi/webhook/", views.vapi_webhook, name="vapi_webhook"),
    path("api/vapi/chat/completions/", views.chat_completions, name="chat_completions"),
    path("api/vapi/chat/completions", views.chat_completions, name="chat_completions_no_slash"),
    # Frontend (HTML)
    path("", frontend_views.landing, name="landing"),
    path("chat/", frontend_views.chat_page, name="chat"),
    path("dashboard/", frontend_views.dashboard, name="dashboard"),
]
