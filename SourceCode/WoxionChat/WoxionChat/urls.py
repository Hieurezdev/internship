from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('accounts.urls')),
    path('ocr/', include('OCRfeature.urls')),
    path('chat/', include('agenticRAG.urls')),
    path('support/', include('SupportChatbot.urls')),
    path('tts/', include('TextToSpeech.urls')),
    path('oauth/', include('social_django.urls', namespace='social')),
    path('chunking/', include('SemanticChunking.urls')),
    path('takenote/', include('takenote.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)