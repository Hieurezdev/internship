from django.db import models 
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import mongoengine as me
import datetime
import os
import logging 

logger = logging.getLogger(__name__)

def validate_file_extension(value):
    allowed_extensions = ['.pdf', '.docx', '.png', '.jpg', '.jpeg', '.txt']
    if hasattr(value, 'filename'):
        filename = value.filename
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f'File extension "{ext}" is not allowed. '
            f'Allowed file extensions: {", ".join(allowed_extensions)}'
        )

def user_upload_path(instance, filename):
    return f'uploads/{instance.uploader.id}/{timezone.now().strftime("%Y-%m-%d")}/{filename}'

def get_utc_now():
    """Get current UTC datetime"""
    return datetime.datetime.now(datetime.timezone.utc)

class UploadedFile(me.Document):
    title = me.StringField(max_length=255, required=True,)
    file = me.FileField(required=True, verbose_name="Attached file")
    uploader_id = me.StringField(required=True)
    uploader_username = me.StringField(max_length=150)
    uploaded_at = me.DateTimeField(default=get_utc_now)
    updated_at = me.DateTimeField(default=get_utc_now)
    file_size = me.IntField(default=0, verbose_name="File size (bytes)")
    mime_type = me.StringField(max_length=100, verbose_name="MIME type")
    original_filename = me.StringField(max_length=255)
    is_active = me.BooleanField(default=True)

    meta = {
        'collection': 'uploaded_files',
        'indexes': [
            '-uploaded_at',
            'uploader_id',
            'is_active',
            '-updated_at',
        ],
        'ordering': ['-uploaded_at']
    }
    
    def save(self, *args, **kwargs):
        logger.info("Saving uploaded file ...")
        self.updated_at = get_utc_now()
        if self.file:
            logger.info("self.file satisfies!")
            if not self.original_filename:
                logger.info("not self.original filename")
                self.original_filename = self.file.filename
            if hasattr(self.file, 'length'):
                logger.info("Hasattr")
                self.file_size = self.file.length
        try:
            super().save(*args, **kwargs)
        except Exception as e:
            logger.error("Cannot save uploaded file")
            raise
        

    def delete(self, *args, **kwargs):
        if self.file:
            self.file.delete()
        super().delete(*args, **kwargs)

    @property
    def filename(self):
        return self.file.filename if self.file else ""
    
    @property
    def extension(self):
        filename = self.filename
        if filename:
            return os.path.splitext(filename)[1].lower()
        return ""

    @property
    def file_size_display(self):
        if not self.file_size:
            return "0 bytes"
        
        size = float(self.file_size)
        for unit in ['bytes', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    @property
    def uploader(self):
        if self.uploader_id:
            try:
                from accounts.models import User  
                return User.objects(id=str(self.uploader_id)).first()
            except Exception:
                return None
        return None

    def set_uploader(self, user):
        self.uploader_id = str(user.id) 
        self.uploader_username = user.username

# Base class cho OCR Results với common fields và methods
class BaseOCRResult(me.Document):
    STATUS_CHOICES = [
        ('pending', 'Đang chờ xử lý'),      
        ('processing', 'Đang xử lý'),   
        ('completed', 'Thành công'),         
        ('failed', 'Thất bại')    
    ]

    source_file = me.StringField(required=True)  
    uploader_username = me.StringField(max_length=150)
    status = me.StringField(max_length=20, choices=STATUS_CHOICES, default='pending')
    result_data = me.DictField()
    raw_markdown = me.StringField()
    error_message = me.StringField()
    created_at = me.DateTimeField(default=get_utc_now)
    started_at = me.DateTimeField(null=True, blank=True)
    completed_at = me.DateTimeField(default=get_utc_now)
    processing_time_seconds = me.FloatField(null=True, blank=True)
    # processing_method = me.StringField()

    meta = {
        'abstract': True, 
        'indexes': [
            '-created_at',
            'status',
            'source_file',  
            'uploader_username'
        ],
        'ordering': ['-created_at']
    }

    @property
    def source_file_object(self):
        """Get source file object from ID"""
        return UploadedFile.objects(id=self.source_file).first()

    def __str__(self):
        source_file_obj = self.source_file_object
        title = source_file_obj.title if source_file_obj else f"File ID: {self.source_file}"
        return f"OCR: {title} - {self.status} ({self.uploader_username})"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
    
    # Status properties
    @property
    def is_completed(self):
        return self.status in ['completed', 'failed']
    
    @property
    def is_successful(self):
        return self.status == 'completed'
    
    @property
    def has_result(self):
        return bool(self.result_data)
    
    # State management methods
    def mark_as_processing(self):
        self.status = 'processing'
        self.started_at = get_utc_now()
        self.error_message = ""
        self.save()
    
    def mark_as_success(self, result_data, raw_markdown=""):
        self.status = 'completed'
        self.result_data = result_data
        self.raw_markdown = raw_markdown
        self.completed_at = get_utc_now()
        self.error_message = ""
        
        # Calculate processing time
        if self.started_at:
            time_diff = self.completed_at - self.started_at
            self.processing_time_seconds = time_diff.total_seconds()
        self.save()
    
    def mark_as_failed(self, error_message):
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = get_utc_now()
        
        # Calculate processing time
        if self.started_at:
            time_diff = self.completed_at - self.created_at
            self.processing_time_seconds = time_diff.total_seconds()
        self.save()
    
    def get_structured_content(self):
        """Get structured content from result_data"""
        return self.result_data.get('structured_content', {})
    
    def get_markdown_content(self):
        """Get markdown content from result_data or raw_markdown field"""
        if self.result_data and 'markdown_content' in self.result_data:
            return self.result_data['markdown_content']
        return self.raw_markdown or ""


# Admin OCR Results - lưu vào admin_database collection
class AdminOCRResult(BaseOCRResult):
    meta = {
        'collection': 'admin_database',
        'indexes': [
            '-created_at',
            'status',
            'source_file'
        ],
        'ordering': ['-created_at']
    }


# User OCR Results - lưu vào user_database collection  
class UserOCRResult(BaseOCRResult):
    meta = {
        'collection': 'user_database',
        'indexes': [
            '-created_at',
            'status',
            'source_file'
        ],
        'ordering': ['-created_at']
    }


# Factory class để tạo OCRResult phù hợp dựa trên user role
class OCRResultFactory:
    @staticmethod
    def create_ocr_result(uploaded_file, **kwargs):
        """
        Tạo OCRResult instance phù hợp dựa trên role của uploader
        """
        uploader = uploaded_file.uploader
        if not uploader:
            raise ValueError("Không thể xác định uploader của file")
        
        # Tự động set uploader_username từ uploaded_file
        kwargs['uploader_username'] = uploaded_file.uploader_username or uploader.username
        
        if uploader.is_admin():
            return AdminOCRResult(source_file=str(uploaded_file.id), **kwargs)
        else:
            return UserOCRResult(source_file=str(uploaded_file.id), **kwargs)
    
    @staticmethod
    def get_results_for_user(user):
        """
        Lấy tất cả OCR results cho một user từ collection phù hợp
        Handles DBRef errors gracefully and skips orphaned results
        """
        results = []
        if user.is_admin():
            # Admin có thể xem tất cả results từ cả 2 collections
            try:
                admin_results = list(AdminOCRResult.objects())
                # Filter out orphaned results
                for result in admin_results:
                    try:
                        # Test if source_file is accessible
                        if result.source_file:
                            results.append(result)
                    except Exception:
                        # Skip orphaned results with broken DBRef
                        continue
                        
                user_results = list(UserOCRResult.objects())
                # Filter out orphaned results
                for result in user_results:
                    try:
                        # Test if source_file is accessible
                        if result.source_file:
                            results.append(result)
                    except Exception:
                        # Skip orphaned results with broken DBRef
                        continue
                        
            except Exception as e:
                logger.warning(f"Error getting admin results: {e}")
                
        else:
            # User thường chỉ xem được results của mình từ user_database
            try:
                user_files = UploadedFile.objects(uploader_id=str(user.id))
                user_results = UserOCRResult.objects(source_file__in=[str(f.id) for f in user_files])
                # Filter out orphaned results
                for result in user_results:
                    try:
                        # Test if source_file is accessible
                        if result.source_file:
                            results.append(result)
                    except Exception:
                        # Skip orphaned results with broken DBRef
                        continue
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Error getting user results: {e}")
                
        return results
    
    @staticmethod
    def get_result_by_id(result_id, user):
        """
        Lấy OCR result theo ID, check permission dựa trên user role
        """
        if user.is_admin():
            # Admin có thể access cả 2 collections
            result = AdminOCRResult.objects(id=result_id).first()
            if not result:
                result = UserOCRResult.objects(id=result_id).first()
            return result
        else:
            # User thường chỉ access được user_database và chỉ file của mình
            result = UserOCRResult.objects(id=result_id).first()
            if result and result.source_file:
                # Check if the source file belongs to this user
                source_file = UploadedFile.objects(id=result.source_file).first()
                if source_file and source_file.uploader_id == str(user.id):
                    return result
            return None


