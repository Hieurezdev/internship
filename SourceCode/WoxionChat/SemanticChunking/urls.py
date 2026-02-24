from django.urls import path
from .views import SemanticChunkingAPIView

urlpatterns = [
    path('documents/', SemanticChunkingAPIView.as_view(), name = 'semantic_chunking')
]