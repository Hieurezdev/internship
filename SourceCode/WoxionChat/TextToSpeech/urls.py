from django.urls import path
from .views import TextToSpeechAPIView

urlpatterns = [
    path('', TextToSpeechAPIView.as_view(), name = "speech_to_text")
]