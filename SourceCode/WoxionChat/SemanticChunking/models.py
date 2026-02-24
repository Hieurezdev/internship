from mongoengine import Document,fields
import uuid
import datetime

def get_utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

class AdminDocumentChunking(Document):
    
    chunk_id = fields.UUIDField(binary = False, default = uuid.uuid4, primary_key = False)
    source_file = fields.StringField(max_length= 250)
    content = fields.StringField(required = True)
    uploader_username = fields.StringField(max_length = 150, required = True)
    embedding = fields.ListField(fields.FloatField(), required = True)
    created_at = fields.DateTimeField(default= get_utc_now)
    
    meta = {
        'collection': 'admin_documents_chunking',
        'indexes' : [
            'chunk_id',
            'uploader_username',
            '-created_at'
        ],
        'ordering': ['-created_at']
    }
    
    def save(self, *args, **kwargs):
        self.created_at = get_utc_now()
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        
class UserDocumentChunking(Document):
    
    chunk_id = fields.UUIDField(binary = False, default = uuid.uuid4, primary_key = False)
    source_file = fields.StringField(max_length= 250)
    content = fields.StringField(required = True)
    uploader_username = fields.StringField(max_length = 150, required = True)
    embedding = fields.ListField(fields.FloatField(), required = True)
    created_at = fields.DateTimeField(default= get_utc_now)
    
    meta = {
        'collection': 'user_documents_chunking',
        'indexes' : [
            'chunk_id',
            'uploader_username',
            '-created_at'
        ],
        'ordering': ['-created_at']
    }
    
    def save(self, *args, **kwargs):
        self.created_at = get_utc_now()
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
    