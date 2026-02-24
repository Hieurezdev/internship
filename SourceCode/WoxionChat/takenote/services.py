from .models import Notetaking
from datetime import datetime, timezone

def create_note(user, title, content, is_pinned=False):
    note = Notetaking(user=user, title=title, content=content, is_pinned=is_pinned)
    note.save()
    return note

def get_notes_by_user(user):
    return Notetaking.objects(user=user).order_by('-is_pinned','-created_at')

def get_note_by_id(note_id):
    return Notetaking.objects(id=note_id).first()

def update_note(note_id, title=None, content=None, is_pinned=None):
    note = Notetaking.objects(id=note_id).first()
    if note:
        if title is not None:
            note.title = title
        if content is not None:
            note.content = content
        if is_pinned is not None: 
            note.is_pinned = is_pinned
        note.updated_at = datetime.now(timezone.utc)
        note.save()
    return note

def delete_note(note_id):
    note = Notetaking.objects(id=note_id).first()
    if note:
        note.delete()
        return True
    return False