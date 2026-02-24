from django.urls import path
from . import views

app_name = 'OCRfeature'

urlpatterns = [
    path('', views.ocr_home, name='ocr_home'),
    # File upload
    path('upload/', views.upload_file, name='upload_file'),
    path('files/', views.list_files, name='list_files'),
    path('files/<str:file_id>/', views.file_detail, name='file_detail'),
    path('files/<str:file_id>/download/', views.download_file, name='download_file'),
    path('files/<str:file_id>/delete/', views.delete_file, name='delete_file'),
    
    # OCR processing
    path('process/<str:file_id>/', views.process_ocr, name='process_ocr'),
    path('results/<str:result_id>/', views.ocr_result_detail, name='ocr_result_detail'),
    path('results/<str:result_id>/status/', views.ocr_status, name='ocr_status'),
    
    # API endpoints
    path('api/upload/', views.api_upload_file, name='api_upload_file'),
    path('api/files/<str:file_id>/ocr/', views.api_process_ocr, name='api_process_ocr'),
    path('api/results/<str:result_id>/', views.api_ocr_result, name='api_ocr_result'),
]