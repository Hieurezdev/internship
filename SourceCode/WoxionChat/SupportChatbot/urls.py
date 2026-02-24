from django.urls import path
from .views import SupportChatbotAPIView

urlpatterns = [
    path('message/', SupportChatbotAPIView.as_view(), name = 'customer_support')
]