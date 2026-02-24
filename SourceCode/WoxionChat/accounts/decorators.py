from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from .utils import get_current_user


def login_required(view_func):
    """Decorator to require user login"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            messages.error(request, 'Vui lòng đăng nhập để truy cập trang này.')
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    """Decorator to require specific roles"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = get_current_user(request)
            if not user:
                messages.error(request, 'Vui lòng đăng nhập để truy cập trang này.')
                return redirect('login')
            
            if user.role not in allowed_roles:
                messages.error(request, f'Bạn không có quyền truy cập trang này. Cần vai trò: {", ".join(allowed_roles)}')
                return redirect('dashboard')
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def admin_required(view_func):
    """Decorator to require admin role"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            messages.error(request, 'Vui lòng đăng nhập để truy cập trang này.')
            return redirect('login')
        
        if not user.is_admin():
            messages.error(request, 'Chỉ quản trị viên mới có thể truy cập trang này.')
            return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def user_required(view_func):
    """Decorator to require user role (both admin and regular user can access)"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            messages.error(request, 'Vui lòng đăng nhập để truy cập trang này.')
            return redirect('login')
        
        # Both admin and user can access user-level features
        if user.role not in ['admin', 'user']:
            messages.error(request, 'Bạn không có quyền truy cập trang này.')
            return redirect('dashboard')
        
        return view_func(request, *args, **kwargs)
    return wrapper


def permission_required(permission):
    """Decorator to require specific permission"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = get_current_user(request)
            if not user:
                messages.error(request, 'Vui lòng đăng nhập để truy cập trang này.')
                return redirect('login')
            
            if not user.has_permission(permission):
                messages.error(request, f'Bạn không có quyền "{permission}" để truy cập trang này.')
                return redirect('dashboard')
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def api_login_required(view_func):
    """API decorator to require user login"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def api_admin_required(view_func):
    """API decorator to require admin role"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = get_current_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        if not user.is_admin():
            return JsonResponse({
                'error': 'Admin privileges required',
                'user_role': user.role
            }, status=403)
        
        return view_func(request, *args, **kwargs)
    return wrapper


def api_role_required(*allowed_roles):
    """API decorator to require specific roles"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = get_current_user(request)
            if not user:
                return JsonResponse({'error': 'Authentication required'}, status=401)
            
            if user.role not in allowed_roles:
                return JsonResponse({
                    'error': f'Insufficient permissions. Required roles: {", ".join(allowed_roles)}',
                    'user_role': user.role
                }, status=403)
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator 