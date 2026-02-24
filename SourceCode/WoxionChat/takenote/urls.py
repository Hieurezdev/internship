
from django.urls import path
from . import views

urlpatterns = [
    path('notes/', views.list_notes, name='list_notes'),
    path('notes/add/', views.add_note, name='add_note'),
    path('notes/<str:note_id>/edit/', views.edit_note, name='edit_note'),
    path('notes/<str:note_id>/delete/', views.remove_note, name='remove_note'),
]
