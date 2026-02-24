from django.conf import settings
from .models import User, UserSession
from datetime import datetime
import secrets


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def create_user_session(request, user):
    """Create a user session"""
    try:
        session_key = secrets.token_urlsafe(32)
        
        # Store session in database
        user_session = UserSession(
            user=user.username,
            session_key=session_key,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )
        user_session.save()
        
        # Store in Django session
        request.session['user_id'] = str(user.id)
        request.session['username'] = user.username
        request.session['session_key'] = session_key
        request.session['is_authenticated'] = True
        
        return session_key
    except Exception as e:
        # Handle MongoDB connection issues gracefully
        return None


def get_current_user(request):
    """Get current logged in user"""
    try:
        if not request.session.get('is_authenticated'):
            print("DEBUG: Session not authenticated")
            return None
            
        username = request.session.get('username')
        session_key = request.session.get('session_key')
        
        if not username or not session_key:
            print(f"DEBUG: Missing session data - username: {username}, session_key: {bool(session_key)}")
            return None
        
        # Verify session exists in database
        user_session = UserSession.objects(user=username, session_key=session_key).first()
        if not user_session:
            # Session expired or invalid
            print(f"DEBUG: UserSession not found for user: {username}")
            request.session.flush()
            return None
        
        # Update last activity
        user_session.last_activity = datetime.now()
        user_session.save()
        
        # Get user
        user = User.objects(username=username).first()
        if not user:
            print(f"DEBUG: User not found in database: {username}")
            return None
            
        # Debug user role
        if not user.role:
            print(f"DEBUG: User {username} has no role assigned")
            return user  # Still return user, let view handle the role issue
            
        print(f"DEBUG: User authenticated successfully - username: {user.username}, role: {user.role}")
        return user
        
    except Exception as e:
        # Handle MongoDB connection issues gracefully
        print(f"DEBUG: Error in get_current_user: {str(e)}")
        return None


def logout_user(request):
    """Logout user and cleanup session"""
    username = request.session.get('username')
    session_key = request.session.get('session_key')
    
    if username and session_key:
        try:
            # Remove session from database
            UserSession.objects(user=username, session_key=session_key).delete()
        except Exception:
            pass  # Handle MongoDB connection issues gracefully
    
    # Clear Django session
    request.session.flush() 