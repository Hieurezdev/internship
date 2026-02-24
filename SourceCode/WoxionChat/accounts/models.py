# from django.db import models  # Removed - only using MongoDB
from mongoengine import Document, StringField, EmailField, DateTimeField, BooleanField, ListField, DictField, FloatField
from datetime import datetime
from django.contrib.auth.hashers import make_password, check_password
import re

# Create your models here.

class DocumentProcessing(Document):
    """MongoDB model for actual document processing data"""
    
    # New format fields
    source_file = StringField()  # Reference to source file
    uploader_username = StringField(max_length=150, required=True)
    status = StringField(max_length=50, default='completed')  # e.g., 'completed', 'processing', 'error'
    result_data = DictField()  # Processing results
    created_at = DateTimeField(default=datetime.now)
    started_at = DateTimeField()
    completed_at = DateTimeField()
    processing_time_seconds = FloatField()
    error_message = StringField()
    raw_markdown = StringField()  # Raw markdown content
    
    # Legacy format fields (for backward compatibility)
    upload_date = DateTimeField()  # Legacy field
    file_data = DictField()  # Legacy field
    metadata = DictField()  # Legacy field
    is_active = BooleanField(default=True)  # Legacy field
    
    meta = {
        'collection': 'user_database',  # Use the existing collection
        'indexes': ['uploader_username', 'created_at', 'status']
    }
    
    def __str__(self):
        return f"DocumentProcessing: {self.uploader_username} - {self.get_status()}"
    
    def get_status(self):
        """Get status, prioritizing new format over legacy"""
        if self.status:
            return self.status
        return 'completed' if self.is_active else 'inactive'
    
    def get_upload_date(self):
        """Get upload date, prioritizing new format over legacy"""
        return self.created_at or self.upload_date or datetime.now()
    
    def get_filename(self):
        """Get filename from various sources"""
        # Try file_data first (legacy)
        if self.file_data and self.file_data.get('filename'):
            return self.file_data.get('filename')
        # Try result_data (new format)
        if self.result_data and self.result_data.get('filename'):
            return self.result_data.get('filename')
        # Try metadata
        if self.metadata and self.metadata.get('filename'):
            return self.metadata.get('filename')
        # Fallback to source_file or ID
        return self.source_file or f"Document_{str(self.id)[:8]}"
    
    def get_file_size(self):
        """Get file size from various sources"""
        # Try file_data first (legacy)
        if self.file_data and self.file_data.get('size'):
            return self.file_data.get('size')
        # Try result_data (new format)
        if self.result_data and self.result_data.get('file_size'):
            return self.result_data.get('file_size')
        # Calculate from raw_markdown if available
        if self.raw_markdown:
            return len(self.raw_markdown.encode('utf-8'))
        return None
    
    def get_file_type(self):
        """Get file type from various sources"""
        # Try file_data first (legacy)
        if self.file_data and self.file_data.get('type'):
            return self.file_data.get('type')
        # Try result_data (new format)
        if self.result_data and self.result_data.get('file_type'):
            return self.result_data.get('file_type')
        # Try to infer from filename
        filename = self.get_filename()
        if filename:
            if filename.endswith('.pdf'):
                return 'pdf'
            elif filename.endswith('.docx'):
                return 'docx'
            elif filename.endswith('.txt'):
                return 'text'
        return 'unknown'
    
    def get_description(self):
        """Get description from metadata"""
        # Try metadata first
        if self.metadata and self.metadata.get('description'):
            return self.metadata.get('description')
        # Try result_data
        if self.result_data and self.result_data.get('description'):
            return self.result_data.get('description')
        # Generate from filename
        filename = self.get_filename()
        return f"Document: {filename}" if filename else "Document processing entry"
    
    def is_legacy_format(self):
        """Check if this is legacy format data"""
        return bool(self.file_data or self.metadata) and not bool(self.raw_markdown)
    
    @classmethod
    def get_by_uploader_username(cls, username):
        """Get document processing entries by uploader_username"""
        try:
            return cls.objects.filter(uploader_username=username)
        except cls.DoesNotExist:
            return []
    
    @classmethod
    def get_all_active_entries(cls):
        """Get all active document processing entries"""
        return cls.objects.filter(
            uploader_username__exists=True  # Basic filter to get all entries
        ).order_by('-created_at', '-upload_date')
    
    def to_display_format(self):
        """Convert to display format for frontend"""
        if self.is_legacy_format():
            return self._legacy_to_display_format()
        else:
            return self._new_to_display_format()
    
    def _new_to_display_format(self):
        """Convert new format to display"""
        return {
            'uploader_username': self.uploader_username,
            'source_file': self.source_file,  # Add source_file field
            'upload_date': self.get_upload_date().isoformat() if self.get_upload_date() else None,
            'file_data': {
                'filename': self.get_filename(),
                'size': self.get_file_size(),
                'type': self.get_file_type(),
                'status': self.get_status()
            },
            'metadata': {
                'description': self.get_description(),
                'processing_time': self.processing_time_seconds,
                'raw_content_length': len(self.raw_markdown or ''),
                'completed_at': self.completed_at.isoformat() if self.completed_at else None,
                'format': 'new'
            },
            'is_active': self.get_status() == 'completed'
        }
    
    def _legacy_to_display_format(self):
        """Convert legacy format to display"""
        return {
            'uploader_username': self.uploader_username,
            'source_file': self.source_file or str(self.id),  # Use source_file or fallback to ID
            'upload_date': self.get_upload_date().isoformat() if self.get_upload_date() else None,
            'file_data': self.file_data or {},
            'metadata': dict(self.metadata or {}, **{
                'format': 'legacy',
                'processing_time': self.processing_time_seconds,
                'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            }),
            'is_active': self.get_status() == 'completed'
        }
    
    def get_filename(self):
        """Extract filename from raw_markdown, result_data, or file_data"""
        # New format
        if self.raw_markdown and self.raw_markdown.startswith('# PDF:'):
            lines = self.raw_markdown.split('\n')
            if lines:
                header = lines[0]
                if header.startswith('# PDF:'):
                    return header.replace('# PDF:', '').strip()
        
        if self.result_data and 'filename' in self.result_data:
            return self.result_data['filename']
        
        # Legacy format
        if self.file_data and 'filename' in self.file_data:
            return self.file_data['filename']
            
        return f"Document_{self.source_file}" if self.source_file else "Unknown File"
    
    def get_file_size(self):
        """Get file size from result_data, file_data, or estimate from content"""
        # New format
        if self.result_data and 'size' in self.result_data:
            return self.result_data['size']
        
        # Legacy format
        if self.file_data and 'size' in self.file_data:
            return self.file_data['size']
        
        # Estimate size from content length
        if self.raw_markdown:
            return len(self.raw_markdown.encode('utf-8')) // 1024  # KB
        
        return 0
    
    def get_file_type(self):
        """Get file type from filename, result_data, or file_data"""
        filename = self.get_filename()
        if '.' in filename:
            return filename.split('.')[-1].lower()
        
        if self.raw_markdown and self.raw_markdown.startswith('# PDF:'):
            return 'pdf'
        
        # Legacy format
        if self.file_data and 'type' in self.file_data:
            return self.file_data['type']
            
        return 'unknown'
    
    def get_description(self):
        """Generate description from available data"""
        # Legacy format
        if self.is_legacy_format() and self.metadata and 'description' in self.metadata:
            return self.metadata['description']
        
        # New format
        filename = self.get_filename()
        file_type = self.get_file_type().upper()
        
        if self.get_status() == 'completed':
            content_length = len(self.raw_markdown or '')
            return f"{file_type} document ({content_length} characters processed)"
        else:
            return f"{file_type} document - Status: {self.get_status()}"

class UserDatabase(Document):
    """MongoDB model for user_database collection (legacy format)"""
    
    uploader_username = StringField(max_length=150, required=True)  # Removed unique=True to allow multiple entries per user
    upload_date = DateTimeField(default=datetime.now)
    file_data = DictField()  # Store any file-related data
    metadata = DictField()   # Store additional metadata
    is_active = BooleanField(default=True)
    
    meta = {
        'collection': 'user_database_legacy',  # Use different collection for legacy data
        'indexes': ['uploader_username', 'upload_date']
    }
    
    def __str__(self):
        return f"UserDatabase: {self.uploader_username}"
    
    @classmethod
    def get_by_uploader_username(cls, username):
        """Get user database entry by uploader_username"""
        try:
            return cls.objects.get(uploader_username=username)
        except cls.DoesNotExist:
            return None
    
    @classmethod
    def get_all_by_uploader_username(cls, username):
        """Get all user database entries by uploader_username"""
        return cls.objects.filter(uploader_username=username)

class User(Document):
    """MongoDB User model for authentication"""
    # User roles constants - simplified to only admin and user
    ROLES = [
        ('admin', 'Quản trị viên'),
        ('user', 'Người dùng'),
    ]
    
    username = StringField(max_length=150, required=True, unique=True)
    email = EmailField(required=True, unique=True)
    first_name = StringField(max_length=30, required=True)
    last_name = StringField(max_length=30, required=True)
    password = StringField(required=True)
    role = StringField(max_length=20, choices=ROLES, default='user')
    permissions = ListField(StringField(max_length=50), default=list)
    is_active = BooleanField(default=True)
    is_verified = BooleanField(default=False)
    
    # Django compatibility fields
    is_staff = BooleanField(default=False)
    is_superuser = BooleanField(default=False)
    
    
    date_joined = DateTimeField(default=datetime.now)
    last_login = DateTimeField()
    
    meta = {
        'collection': 'users',
        'indexes': ['username', 'email', 'role']
    }

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def set_password(self, raw_password):
        """Hash and set password"""
        self.password = make_password(raw_password)
        
    def check_password(self, raw_password):
        """Check if provided password is correct"""
        return check_password(raw_password, self.password)
    
    def get_full_name(self):
        """Return full name"""
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_short_name(self):
        """Return first name"""
        return self.first_name
    
    def get_role_display(self):
        """Get role display name in Vietnamese"""
        role_dict = dict(self.ROLES)
        return role_dict.get(self.role, self.role)
    
    @classmethod
    def create_user(cls, username, email, first_name, last_name, password, role='user', **extra_fields):
        """Create and save a new user"""
        # Validate input
        if not username or not email or not password:
            raise ValueError("Username, email và password là bắt buộc")
        
        if cls.objects(username=username).first():
            raise ValueError("Tên đăng nhập đã tồn tại")
            
        if cls.objects(email=email).first():
            raise ValueError("Email đã được sử dụng")
        
        # Validate email format
        email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_regex, email):
            raise ValueError("Email không hợp lệ")
        
        # Validate password strength
        if len(password) < 8:
            raise ValueError("Mật khẩu phải có ít nhất 8 ký tự")
        
        # Set Django compatibility fields based on role
        is_staff = role == 'admin'
        is_superuser = role == 'admin'
        
        user = cls(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_staff=is_staff,
            is_superuser=is_superuser,
            **extra_fields
        )
        # Use set_password to properly hash the password
        user.set_password(password)
        user.save()
        return user
    
    @classmethod
    def authenticate(cls, username, password):
        """Authenticate user with username and password"""
        user = cls.objects(username=username).first()
        if user and user.check_password(password):
            # Update last login
            user.last_login = datetime.now()
            user.save()
            return user
        return None

    def is_authenticated(self):
        """Always return True for authenticated users"""
        return True

    def is_anonymous(self):
        """Always return False for real users"""  
        return False

    def has_permission(self, permission):
        """Check if user has specific permission"""
        if self.role == 'admin':
            return True  # Admin has all permissions
        return permission in self.permissions
    
    def has_perm(self, perm, obj=None):
        """Django compatibility method"""
        if self.is_superuser:
            return True
        return self.has_permission(perm)
    
    def has_module_perms(self, app_label):
        """Django compatibility method"""
        if self.is_superuser:
            return True
        return self.role == 'admin'
    
    def is_admin(self):
        """Check if user is admin"""
        return self.role == 'admin'
    
    def is_regular_user(self):
        """Check if user is regular user"""
        return self.role == 'user'
    
    def can_manage_users(self):
        """Check if user can manage other users - only admin"""
        return self.role == 'admin'
    
    def can_access_admin_panel(self):
        """Check if user can access admin panel - only admin"""
        return self.role == 'admin'
    
    def add_permission(self, permission):
        """Add permission to user"""
        if permission not in self.permissions:
            self.permissions.append(permission)
            self.save()
    
    def remove_permission(self, permission):
        """Remove permission from user"""
        if permission in self.permissions:
            self.permissions.remove(permission)
            self.save()
    
    def get_permissions_display(self):
        """Get permissions as comma-separated string"""
        return ', '.join(self.permissions) if self.permissions else 'Không có quyền đặc biệt'

    def save(self, *args, **kwargs):
        """Override save to update Django compatibility fields"""
        # Auto-update is_staff and is_superuser based on role
        self.is_staff = self.role == 'admin'
        self.is_superuser = self.role == 'admin'
        super().save(*args, **kwargs)

class UserSession(Document):
    """User session management"""
    user = StringField(required=True)  # username
    session_key = StringField(required=True, unique=True)
    created_at = DateTimeField(default=datetime.now)
    last_activity = DateTimeField(default=datetime.now)
    ip_address = StringField()
    user_agent = StringField()
    is_active = BooleanField(default=True)
    
    meta = {
        'collection': 'user_sessions',
        'indexes': ['user', 'session_key', 'created_at']
    }
