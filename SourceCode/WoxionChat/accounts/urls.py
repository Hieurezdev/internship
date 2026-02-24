from django.urls import path
from . import views
from agenticRAG import routes

urlpatterns = [
    # Main pages
    path('', views.home_view, name='home'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Role-based Dashboards - simplified to only admin and user
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    
    # User Management
    path('profile/', views.profile_view, name='profile'),
    path('change-password/', views.change_password_view, name='change_password'),
    path('users/', views.users_management_view, name='users_management'),
    path('users/edit/<str:username>/', views.edit_user_view, name='edit_user'),
    
    # Demo Chat Interface - Simple demo chatbot
    path('demo-chat/', views.demo_chat_view, name='demo_chat'),
    path('chat/advanced/', views.chat_advanced_view, name='chat_advanced'),  # Advanced chat demo
    path('chat/test/', views.test_user_database_view, name='test_chat'),  # Test endpoint without auth
    path('chat/', routes.chat, name='normal_chat'),
    
    # APIs
    path('api/users/', views.api_user_list, name='api_user_list'),
    path('api/change-user-role/', views.api_change_user_role, name='api_change_user_role'),
    path('api/toggle-user-status/', views.api_toggle_user_status, name='api_toggle_user_status'),
    path('api/change-password/', views.api_change_password, name='api_change_password'),
    path('api/support/message/', views.api_tech_chat, name='api_tech_chat'),  # Keep for technical support widget
    path('api/system-status/', views.api_system_status, name='api_system_status'),
    path('api/profile/', views.api_profile_update, name='api_profile'),
    
    # Feedback System URLs
    path('feedback/', views.feedback_view, name='feedback'),
    path('api/feedback/submit/', views.api_submit_feedback, name='api_submit_feedback'),
    path('api/feedback/service/', views.api_call_feedback_service, name='api_call_feedback_service'),
    path('admin/feedback/', views.admin_feedback_view, name='admin_feedback'),
    
    # User Database API
    path('api/user-database/', views.UserDatabaseAPIView.as_view(), name='api_user_database'),
]
