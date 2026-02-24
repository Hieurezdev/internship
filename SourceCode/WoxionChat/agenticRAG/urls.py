from django.urls import path, re_path
from . import views

app_name = 'agenticRAG'

urlpatterns = [
    # Proxy all requests to the Flask service
    re_path(r'^(?P<path>.*)$', views.proxy_to_flask, name='proxy'),
]
