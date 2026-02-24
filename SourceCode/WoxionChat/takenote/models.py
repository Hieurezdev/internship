from mongoengine import Document, StringField, DateTimeField, BooleanField
from datetime import datetime, timezone

def get_utc_now():
    return datetime.now(timezone.utc)

class Notetaking(Document):
    meta = {'collection': 'Notetaking'}
    user = StringField(required=True)
    title = StringField(required=True, max_length=200)
    content = StringField()
    is_pinned = BooleanField(default=False)
    created_at = DateTimeField(default=get_utc_now)
    updated_at = DateTimeField(default=get_utc_now)