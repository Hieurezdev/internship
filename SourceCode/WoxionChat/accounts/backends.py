from django.contrib.auth.backends import BaseBackend
from .models import User

class MongoUserBackend(BaseBackend):
    """Custom authentication backend for MongoDB User model"""
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """Authenticate user with username and password"""
        try:
            user = User.objects(username=username).first()
            if user and user.check_password(password):
                return user
        except Exception:
            return None
        return None
    
    def get_user(self, user_id):
        """Get user by ID"""
        try:
            return User.objects(id=user_id).first()
        except Exception:
            return None 