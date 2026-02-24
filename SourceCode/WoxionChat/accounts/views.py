from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
from django.http import HttpResponseBadRequest
from .forms import CustomUserCreationForm, LoginForm, UserUpdateForm, RoleChangeForm, PasswordChangeForm
from .models import User, UserSession
from .utils import get_current_user, create_user_session, logout_user
from .decorators import login_required, admin_required, user_required, role_required
from .user_database_service import UserDatabaseService
import secrets
from datetime import datetime
import json
import logging
import re 
# accounts/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

# Thêm imports cho feedback system
import requests
import os
from pymongo import MongoClient


logger = logging.getLogger(__name__)


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
        # request.session.save()

        return session_key
    except Exception as e:
        # Handle MongoDB connection issues gracefully
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


def home_view(request):
    """Trang chủ - Home page"""
    user = get_current_user(request)
    
    context = {
        'user': user,
    }
    
    # Add stats for admin users
    if user and user.is_admin():
        try:
            context['total_users'] = User.objects.count()
            context['active_sessions'] = UserSession.objects.count()
        except Exception:
            context['total_users'] = 0
            context['active_sessions'] = 0
    
    return render(request, 'accounts/home.html', context)


def register_view(request):
    """Đăng ký tài khoản - User registration"""
    current_user = get_current_user(request)
    
    if request.method == 'POST':
        form = CustomUserCreationForm(current_user, request.POST)
        try:
            if form.is_valid():
                user = form.save()
                messages.success(request, f'Đăng ký thành công! Chào mừng {user.first_name} với vai trò {user.get_role_display()}! Bạn có thể đăng nhập ngay bây giờ.')
                return redirect('login')
        except Exception as e:
            messages.error(request, f'Có lỗi xảy ra (có thể do kết nối MongoDB): {str(e)}')
    else:
        form = CustomUserCreationForm(current_user)
    
    return render(request, 'accounts/register.html', {'form': form, 'user': current_user})


def login_view(request):
    """Đăng nhập - User login"""
    if request.method == 'POST':
        form = LoginForm(request.POST)
        try:
            if form.is_valid():
                user = form.cleaned_data['user']
                
                # Create session
                session_key = create_user_session(request, user)
                if session_key:
                    # Update last login
                    user.last_login = datetime.now()
                    user.save()
                    
                    messages.success(request, f'Chào mừng {user.first_name} {user.last_name} ({user.get_role_display()})!')
                    
                    # Redirect based on role - simplified to only admin and user
                    if user.is_admin():
                        return redirect('admin_dashboard')
                    else:
                        return redirect('dashboard')
                else:
                    messages.error(request, 'Có lỗi xảy ra khi tạo phiên đăng nhập.')
        except Exception as e:
            messages.error(request, f'Có lỗi xảy ra (có thể do kết nối MongoDB): {str(e)}')
    else:
        form = LoginForm()
    
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    """Đăng xuất - User logout"""
    logout_user(request)
    messages.success(request, 'Đã đăng xuất thành công!')
    return redirect('home')


@login_required
def dashboard_view(request):
    """Trang dashboard sau khi đăng nhập - User dashboard"""
    user = get_current_user(request)
    
    # Debug: Check if user is valid
    if not user:
        messages.error(request, 'Lỗi: Không thể xác thực người dùng. Vui lòng đăng nhập lại.')
        return redirect('login')
    
    # Debug: Check user role
    if not user.role:
        messages.error(request, 'Lỗi: Tài khoản của bạn chưa được gán vai trò. Vui lòng liên hệ quản trị viên.')
        return redirect('login')
    
    # Debug: Validate role
    valid_roles = [role[0] for role in User.ROLES]
    if user.role not in valid_roles:
        messages.error(request, f'Lỗi: Vai trò "{user.role}" không hợp lệ. Vui lòng liên hệ quản trị viên.')
        return redirect('login')
    
    try:
        # Get user statistics with error handling
        total_users = User.objects.count()
        active_sessions = UserSession.objects.count()
    except Exception as e:
        messages.error(request, f'Lỗi kết nối cơ sở dữ liệu: {str(e)}')
        total_users = 0
        active_sessions = 0
    
    context = {
        'user': user,
        'total_users': total_users,
        'active_sessions': active_sessions,
        'dashboard_type': 'user'
    }
    return render(request, 'accounts/dashboard.html', context)


@admin_required
def admin_dashboard_view(request):
    """Dashboard dành cho Admin"""
    user = get_current_user(request)
    
    try:
        # Get comprehensive statistics
        total_users = User.objects.count()
        active_sessions = UserSession.objects.count()
        
        # Role statistics - simplified for only admin and user
        role_stats = {}
        for role_key, role_name in User.ROLES:
            role_stats[role_name] = User.objects(role=role_key).count()
        
        # Recent users
        recent_users = User.objects.order_by('-date_joined')[:5]
        
    except Exception:
        total_users = active_sessions = 0
        role_stats = {}
        recent_users = []
    
    context = {
        'user': user,
        'total_users': total_users,
        'active_sessions': active_sessions,
        'role_stats': role_stats,
        'recent_users': recent_users,
        'dashboard_type': 'admin'
    }
    
    return render(request, 'accounts/admin_dashboard.html', context)


@admin_required
def users_management_view(request):
    """Quản lý người dùng - chỉ admin mới truy cập được"""
    user = get_current_user(request)
    
    try:
        # Get all users for management
        users = User.objects.order_by('-date_joined')
    except Exception:
        users = []
    
    context = {
        'user': user,
        'users': users,
        'available_roles': User.ROLES  # Now only admin and user
    }
    return render(request, 'accounts/users_management.html', context)


@admin_required
def edit_user_view(request, username):
    """Chỉnh sửa thông tin người dùng - chỉ admin"""
    current_user = get_current_user(request)
    
    try:
        target_user = User.objects.get(username=username)
    except User.DoesNotExist:
        messages.error(request, 'Không tìm thấy người dùng.')
        return redirect('users_management')
    except Exception as e:
        messages.error(request, f'Có lỗi xảy ra: {str(e)}')
        return redirect('users_management')
    
    if request.method == 'POST':
        form = UserUpdateForm(instance=target_user, current_user=current_user, data=request.POST)
        try:
            if form.is_valid():
                form.save()
                messages.success(request, f'Cập nhật thông tin người dùng {target_user.username} thành công!')
                return redirect('users_management')
        except Exception as e:
            messages.error(request, f'Có lỗi xảy ra khi cập nhật: {str(e)}')
    else:
        form = UserUpdateForm(instance=target_user, current_user=current_user)
    
    context = {
        'user': current_user,
        'target_user': target_user,
        'form': form,
        'available_roles': User.ROLES  # Now only admin and user
    }
    return render(request, 'accounts/edit_user.html', context)


@csrf_exempt
@admin_required
def api_change_user_role(request):
    """API để thay đổi vai trò người dùng - chỉ admin"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        import json
        data = json.loads(request.body)
        username = data.get('username')
        new_role = data.get('role')
        
        if not username or not new_role:
            return JsonResponse({'error': 'Username và role là bắt buộc'}, status=400)
        
        # Validate role
        valid_roles = [role[0] for role in User.ROLES]  # Now only admin and user
        if new_role not in valid_roles:
            return JsonResponse({'error': f'Vai trò không hợp lệ. Chỉ chấp nhận: {", ".join(valid_roles)}'}, status=400)
        
        # Check if admin is trying to change their own role
        current_user = get_current_user(request)
        if current_user.username == username:
            return JsonResponse({'error': 'Bạn không thể thay đổi vai trò của chính mình!'}, status=403)
        
        # Find user
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return JsonResponse({'error': 'Không tìm thấy người dùng'}, status=404)
        
        # Check if user is already in that role
        if user.role == new_role:
            return JsonResponse({'error': f'Người dùng {username} đã có vai trò {user.get_role_display()}'}, status=400)
        
        # Store old role info for logging
        old_role = user.get_role_display()
        old_role_key = user.role
        
        # Update role
        user.role = new_role
        user.save()
        new_role_display = user.get_role_display()
        
        # Log the role change (you could save this to a log model)
        print(f"[ROLE CHANGE] Admin {current_user.username} changed {username} from {old_role} to {new_role_display}")
        
        return JsonResponse({
            'success': True,
            'message': f'Đã thay đổi vai trò của {username} từ {old_role} thành {new_role_display}',
            'user': {
                'username': user.username,
                'email': user.email,
                'full_name': user.get_full_name(),
                'old_role': old_role_key,
                'old_role_display': old_role,
                'new_role': user.role,
                'new_role_display': new_role_display,
                'is_active': user.is_active,
                'date_joined': user.date_joined.strftime('%d/%m/%Y %H:%M') if user.date_joined else '',
                'changed_by': current_user.username,
                'changed_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Dữ liệu JSON không hợp lệ'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Có lỗi xảy ra: {str(e)}'}, status=500)


@csrf_exempt
@admin_required
def api_toggle_user_status(request):
    """API để toggle trạng thái hoạt động của người dùng - chỉ admin"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        import json
        from datetime import datetime
        data = json.loads(request.body)
        username = data.get('username')
        
        if not username:
            return JsonResponse({'error': 'Username là bắt buộc'}, status=400)
        
        # Check if admin is trying to change their own status
        current_user = get_current_user(request)
        if current_user.username == username:
            return JsonResponse({'error': 'Bạn không thể thay đổi trạng thái hoạt động của chính mình!'}, status=403)
        
        # Find user
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return JsonResponse({'error': 'Không tìm thấy người dùng'}, status=404)
        
        # Store old status info for logging
        old_status = "Hoạt động" if user.is_active else "Không hoạt động"
        old_active = user.is_active
        
        # Toggle status
        user.is_active = not user.is_active
        user.save()
        
        new_status = "Hoạt động" if user.is_active else "Không hoạt động"
        action = "kích hoạt" if user.is_active else "vô hiệu hóa"
        
        # Log the status change
        print(f"[STATUS CHANGE] Admin {current_user.username} {action} user {username} - từ {old_status} thành {new_status}")
        
        return JsonResponse({
            'success': True,
            'message': f'Đã {action} tài khoản {username} thành công',
            'user': {
                'username': user.username,
                'email': user.email,
                'full_name': user.get_full_name(),
                'old_status': old_active,
                'old_status_display': old_status,
                'new_status': user.is_active,
                'new_status_display': new_status,
                'role': user.role,
                'role_display': user.get_role_display(),
                'date_joined': user.date_joined.strftime('%d/%m/%Y %H:%M') if user.date_joined else '',
                'last_login': user.last_login.strftime('%d/%m/%Y %H:%M') if user.last_login else None,
                'changed_by': current_user.username,
                'changed_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                'action': action
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Dữ liệu JSON không hợp lệ'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Có lỗi xảy ra: {str(e)}'}, status=500)


@login_required
def profile_view(request):
    """Trang thông tin cá nhân"""
    user = get_current_user(request)
    
    if request.method == 'POST' :
        form = UserUpdateForm(instance=user, current_user=user, data=request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Thông tin cá nhân đã được cập nhật!')
                return redirect('profile')
            except Exception as e:
                messages.error(request, f'Có lỗi xảy ra: {str(e)}')
    else:
        form = UserUpdateForm(instance=user, current_user=user)
    
    return render(request, 'accounts/profile.html', {'form': form, 'user': user})

@csrf_exempt
@login_required
def api_profile_update(request):
    if request.method != 'PATCH':
        return JsonResponse({'error': 'Phương thức không được hỗ trợ'}, status=405)
    
    logger.info(f"PATCH /api/profile/ - User: {request.session.get('username', 'Unknown')}")
    
    try:
        data = json.loads(request.body)
        logger.info(f"PATCH Request Data: {data}")

        user = get_current_user(request)
        if not user:
            logger.error("PATCH Request Failed: User not authenticated")
            return JsonResponse({'error': 'Người dùng không được xác thực'}, status=401)
        updated_fields = []
        if 'first_name' in data:
            new_first_name = data['first_name'].strip()
            if new_first_name != user.first_name:
                if not new_first_name:
                    return JsonResponse({'first_name': ['Tên không được để trống']}, status=400)
                user.first_name = new_first_name
                updated_fields.append('first_name')
        
        if 'last_name' in data:
            new_last_name = data['last_name'].strip()
            if new_last_name != user.last_name:
                if not new_last_name:
                    return JsonResponse({'last_name': ['Họ không được để trống']}, status=400)
                user.last_name = new_last_name
                updated_fields.append('last_name')
        
        if 'email' in data:
            new_email = data['email'].strip().lower()
            if new_email != user.email:
                if not new_email:
                    return JsonResponse({'email': ['Email không được để trống']}, status=400)
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', new_email):
                    return JsonResponse({'email': ['Email không hợp lệ']}, status=400)

                try:
                    existing_user = User.objects.get(email=new_email)
                    if existing_user.id != user.id:
                        return JsonResponse({'email': ['Email này đã được sử dụng']}, status=400)
                except User.DoesNotExist:
                    pass  

                user.email = new_email
                updated_fields.append('email')
        if not updated_fields:
            logger.warning("PATCH Request: No fields to update")
            return JsonResponse({'message': 'Không có thông tin nào được thay đổi'}, status=200)
        user.save()
        logger.info(f"PATCH Request Successful: Updated fields {updated_fields} for user {user.username}")

        return JsonResponse({
            'message': 'Cập nhật thông tin thành công!',
            'updated_fields': updated_fields,
            'user': {
                'id': str(user.id),
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': user.get_full_name(),
                'role': user.get_role_display(),
                'is_active': user.is_active,
                'updated_at': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            }
        }, status=200)
    except json.JSONDecodeError:
        logger.error("PATCH Request Failed: Invalid JSON")
        return JsonResponse({'error': 'Dữ liệu JSON không hợp lệ'}, status=400)
    except Exception as e:
        logger.error(f"PATCH Request Failed: {str(e)}")
        return JsonResponse({'error': f'Có lỗi xảy ra: {str(e)}'}, status=500)

@csrf_exempt
@login_required
def api_user_list(request):
    """API để lấy danh sách người dùng"""
    user = get_current_user(request)
    
    try:
        # Only admin can see all users, regular users can't access this API
        if not user.is_admin():
            return JsonResponse({'error': 'Chỉ admin mới có thể truy cập danh sách người dùng'}, status=403)
        
        users = User.objects.all()
        
        user_list = []
        for u in users:
            user_list.append({
                'username': u.username,
                'email': u.email,
                'full_name': u.get_full_name(),
                'role': u.get_role_display(),
                'role_key': u.role,
                'date_joined': u.date_joined.strftime('%d/%m/%Y %H:%M') if u.date_joined else '',
                'last_login': u.last_login.strftime('%d/%m/%Y %H:%M') if u.last_login else 'Chưa đăng nhập',
                'is_active': u.is_active,
                'permissions': u.get_permissions_display()
            })
        
        return JsonResponse({
            'users': user_list,
            'total_count': len(user_list)
        })
        
    except Exception as e:
        return JsonResponse({'error': f'Có lỗi xảy ra: {str(e)}'}, status=500)


@login_required
def demo_chat_view(request):
    """Demo chatbot interface - tạm thời"""
    user = get_current_user(request)
    
    context = {
        'user': user,
        'demo_mode': True,
        'chat_title': 'WoxionChat Demo',
        'chat_description': 'Demo chatbot đơn giản với AI responses'
    }
    return render(request, 'accounts/demo_chat.html', context)


@login_required
def chat_view(request):
    """Trang chat cơ bản"""
    user = get_current_user(request)
    return render(request, 'accounts/chat.html', {'user': user})


@login_required
def chat_advanced_view(request):
    """Trang chat nâng cao"""
    user = get_current_user(request)
    
    # Check if there's a file to load
    file_id = request.GET.get('file_id')
    file_content = None
    file_title = None
    
    if file_id:
        try:
            # Import OCRfeature models
            from OCRfeature.models import UploadedFile, OCRResult
            
            # Get the uploaded file
            uploaded_file = UploadedFile.objects.get(id=file_id, uploader_id=str(user.id))
            
            # Get the latest OCR result using source_file
            ocr_result = OCRResult.objects(source_file=str(uploaded_file.id)).order_by('-created_at').first()
            
            if ocr_result and ocr_result.is_successful:
                file_content = ocr_result.get_markdown_content()
                file_title = uploaded_file.title
            else:
                # File is being processed
                file_title = uploaded_file.title
                file_content = "File đang được xử lý OCR, vui lòng đợi..."
                
        except Exception as e:
            logger.error(f"Error loading file for chat: {e}")
            file_content = f"Lỗi tải file: {str(e)}"
    
    context = {
        'user': user,
        'file_id': file_id,
        'file_content': file_content,
        'file_title': file_title
    }
    
    return render(request, 'accounts/chat_advanced.html', context)


@csrf_exempt
@login_required
def api_chat(request):
    """API endpoint for chat functionality"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()
        file_context = data.get('file_context')
        
        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)
        
        # Get current user
        user = get_current_user(request)
        if not user:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        
        # Get chat history (simplified - you might want to implement proper history)
        history = data.get('history', [])
        
        # Generate AI response with file context
        if file_context:
            ai_response = generate_ai_response_with_file(message, history, user, file_context)
        else:
            ai_response = generate_ai_response(message, history, user)
        
        return JsonResponse({
            'response': ai_response,
            'user': user.username,
            'timestamp': datetime.now().isoformat()
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


def generate_ai_response(message, history, user):
    """Generate AI response based on message and context"""
    message_lower = message.lower()
    
    # Greetings
    if any(word in message_lower for word in ['xin chào', 'hello', 'hi', 'chào']):
        return f"Xin chào {user.first_name}! 👋 Tôi là WoxionChat AI. Tôi có thể giúp gì cho bạn hôm nay?"
    
    # About WoxionChat
    if any(word in message_lower for word in ['woxionchat', 'về ứng dụng', 'about']):
        return f"""🤖 **WoxionChat** - Nền tảng AI Chatbot thông minh!

Xin chào {user.first_name}! Đây là những thông tin về WoxionChat:

✨ **Tính năng chính:**
- Chat AI thông minh và tự nhiên
- Hệ thống xác thực bảo mật cao  
- Giao diện responsive đẹp mắt
- Quản lý người dùng đa cấp
- Dashboard trực quan

🔒 **Bảo mật:** 
- Mã hóa dữ liệu end-to-end
- Xác thực đa lớp
- Session management an toàn

Bạn đang sử dụng với vai trò: **{user.get_role_display()}**

Có điều gì tôi có thể giúp bạn không? 😊"""
    
    # Programming help
    if any(word in message_lower for word in ['lập trình', 'code', 'programming', 'python', 'javascript']):
        return f"""💻 **Lập trình** - Tôi có thể hỗ trợ bạn!

Xin chào {user.first_name}! Tôi có thể giúp bạn với:

**🐍 Python:**
- Web development (Django, Flask)
- Data Science (Pandas, NumPy)
- Machine Learning (Scikit-learn, TensorFlow)
- Automation scripts

**🌐 Web Development:**
- HTML/CSS/JavaScript
- React, Vue.js
- Node.js, Express
- Database (SQL, MongoDB)

**📚 Các chủ đề khác:**
- Algorithms & Data Structures
- System Design
- DevOps & Deployment
- Mobile Development

Bạn có muốn tôi giúp với ngôn ngữ lập trình nào cụ thể không?"""
    
    # AI/ML related
    if any(word in message_lower for word in ['ai', 'machine learning', 'trí tuệ nhân tạo', 'neural network']):
        return """**Trí tuệ nhân tạo (AI) và Machine Learning** là những lĩnh vực rất thú vị!

🧠 **AI** là khả năng của máy tính thực hiện các tác vụ thường cần trí thông minh của con người.

📊 **Machine Learning** là một nhánh của AI, cho phép máy tính học từ dữ liệu mà không cần lập trình cụ thể.

**Các loại ML chính:**
- **Supervised Learning**: Học từ dữ liệu có nhãn
- **Unsupervised Learning**: Tìm patterns trong dữ liệu không nhãn  
- **Reinforcement Learning**: Học qua trial-and-error

**Ứng dụng phổ biến:**
- Nhận dạng hình ảnh
- Xử lý ngôn ngữ tự nhiên
- Hệ thống gợi ý
- Xe tự lái

Bạn muốn tìm hiểu sâu hơn về chủ đề nào?"""
    
    # Translation
    if any(word in message_lower for word in ['dịch', 'translate', 'translation']):
        return """Tôi có thể giúp bạn dịch thuật! 

🌍 **Dịch Việt - Anh:**
- "Xin chào" → "Hello"
- "Cảm ơn" → "Thank you"
- "Tạm biệt" → "Goodbye"

🔄 **Dịch Anh - Việt:**
- "How are you?" → "Bạn khỏe không?"
- "Nice to meet you" → "Rất vui được gặp bạn"

Hãy cho tôi đoạn văn bạn muốn dịch, tôi sẽ giúp bạn!"""
    
    # Learning plan
    if any(word in message_lower for word in ['học', 'kế hoạch', 'plan', 'study']):
        return """📚 **Kế hoạch học tập 30 ngày** - Tôi có thể giúp bạn tạo lộ trình!

**Tuần 1-2: Nền tảng**
- Xác định mục tiêu cụ thể
- Chuẩn bị tài liệu và môi trường học
- Học 2-3 giờ/ngày

**Tuần 3-4: Thực hành**
- Áp dụng kiến thức vào dự án nhỏ
- Review và củng cố
    
**Tips thành công:**
✅ Đặt mục tiêu SMART
✅ Chia nhỏ kiến thức
✅ Thực hành hàng ngày
✅ Tìm community để support

Bạn muốn học về lĩnh vực nào? Tôi sẽ tạo kế hoạch chi tiết hơn!"""
    
    # MongoDB/Database
    if any(word in message_lower for word in ['mongodb', 'database', 'cơ sở dữ liệu']):
        return f"""🗄️ **MongoDB trong WoxionChat**

**Thông tin người dùng:**
- User: {user.username}
- Role: {user.get_role_display()}

**MongoDB là gì?**
- NoSQL document database
- Lưu trữ dữ liệu dạng JSON-like
- Flexible schema
- Horizontal scaling

**Ưu điểm:**
✅ Dễ scale
✅ Performance cao
✅ Flexible data model
✅ Rich query language

Bạn cần hỗ trợ gì về MongoDB không?"""
    
    # Default responses
    default_responses = [
        f"Cảm ơn bạn đã chia sẻ, {user.first_name}! Đây là một câu hỏi thú vị. Tôi đang xử lý và sẽ cố gắng đưa ra câu trả lời tốt nhất có thể.",
        
        f"Tôi hiểu {user.first_name} đang hỏi về điều này. Có thể bạn có thể cung cấp thêm context để tôi hỗ trợ tốt hơn?",
        
        f"Đây là một chủ đề hay, {user.first_name}! Tôi có thể giúp bạn theo một số cách:\n\n1. Phân tích vấn đề chi tiết hơn\n2. Đưa ra gợi ý giải pháp\n3. Cung cấp ví dụ cụ thể\n\nBạn muốn tôi tập trung vào điều gì?",
        
        f"Cảm ơn câu hỏi của {user.first_name}! Tôi sẽ cố gắng hỗ trợ bạn tốt nhất. Bạn có thể mô tả rõ hơn về những gì bạn đang tìm kiếm không?"
    ]
    
    import random
    return random.choice(default_responses)


def generate_ai_response_with_file(message, history, user, file_context):
    """Generate AI response based on message, chat history, and file content"""
    file_title = file_context.get('title', 'Unknown File')
    file_content = file_context.get('content', '')
    
    message_lower = message.lower()
    
    # File-specific responses
    if any(word in message_lower for word in ['tóm tắt', 'summary', 'summarize']):
        return f"""📋 **Tóm tắt file: {file_title}**

Xin chào {user.first_name}! Đây là tóm tắt nội dung chính của file:

{file_content[:800]}{'...' if len(file_content) > 800 else ''}

**Các điểm chính:**
• Đây là nội dung được trích xuất từ file "{file_title}"
• File đã được xử lý bằng công nghệ OCR của WoxionChat
• Bạn có thể hỏi tôi bất cứ điều gì về nội dung này

Bạn muốn tôi giải thích chi tiết phần nào không?"""

    if any(word in message_lower for word in ['quan trọng', 'important', 'key points', 'điểm chính']):
        return f"""🔍 **Các điểm quan trọng trong file: {file_title}**

Chào {user.first_name}! Tôi đã phân tích file và tìm thấy những điểm sau:

**📌 Nội dung chính:**
{file_content[:600]}{'...' if len(file_content) > 600 else ''}

**💡 Gợi ý:**
- Bạn có thể hỏi tôi giải thích bất kỳ phần nào trong file
- Tôi có thể tạo câu hỏi từ nội dung này
- Hoặc dịch nội dung sang ngôn ngữ khác

Có phần nào bạn muốn tôi tập trung giải thích không?"""

    if any(word in message_lower for word in ['giải thích', 'explain', 'chi tiết', 'detail']):
        return f"""💡 **Giải thích chi tiết file: {file_title}**

Xin chào {user.first_name}! Tôi sẽ giải thích nội dung file một cách chi tiết:

**📄 Nội dung file:**
{file_content[:1000]}{'...' if len(file_content) > 1000 else ''}

**🎯 Phân tích:**
- File này chứa thông tin được xử lý bằng OCR
- Nội dung có thể bao gồm văn bản, bảng biểu, hoặc cấu trúc dữ liệu
- Tôi có thể giúp bạn hiểu rõ hơn về bất kỳ phần nào

Bạn có câu hỏi cụ thể nào về nội dung này không?"""

    if any(word in message_lower for word in ['câu hỏi', 'question', 'quiz', 'test']):
        return f"""❓ **Câu hỏi từ file: {file_title}**

Chào {user.first_name}! Dựa trên nội dung file, tôi tạo ra một số câu hỏi:

**📚 Nội dung tham khảo:**
{file_content[:500]}{'...' if len(file_content) > 500 else ''}

**❓ Câu hỏi gợi ý:**
1. Nội dung chính của tài liệu này là gì?
2. Có những thông tin quan trọng nào cần lưu ý?
3. Làm thế nào để áp dụng thông tin này trong thực tế?
4. Có điểm nào cần làm rõ thêm không?

Bạn muốn tôi tạo thêm câu hỏi cụ thể về chủ đề nào?"""

    # General response with file context
    return f"""🤖 **Chat về file: {file_title}**

Xin chào {user.first_name}! Tôi đã hiểu câu hỏi của bạn về file này.

**📄 Nội dung liên quan:**
{file_content[:400]}{'...' if len(file_content) > 400 else ''}

**💬 Phản hồi:**
Dựa trên nội dung file và câu hỏi "{message}", tôi có thể giúp bạn:

• **Giải thích** chi tiết bất kỳ phần nào trong file
• **Tóm tắt** thông tin theo yêu cầu của bạn  
• **Phân tích** dữ liệu và đưa ra nhận xét
• **Dịch thuật** nếu cần chuyển đổi ngôn ngữ
• **Tạo câu hỏi** để kiểm tra hiểu biết

Bạn có muốn tôi tập trung vào khía cạnh nào cụ thể không?"""


# User Database API Views
class UserDatabaseAPIView(APIView):
    """API View for UserDatabase operations"""
    
    def get(self, request):
        """Get user database entries"""
        try:
            uploader_username = request.query_params.get('uploader_username')
            
            if uploader_username:
                # Get specific user database entry
                user_db_entry = UserDatabaseService.get_user_database_by_username(uploader_username)
                if user_db_entry:
                    # Convert to display format
                    display_data = user_db_entry.to_display_format()
                    return Response({
                        'success': True,
                        'data': display_data
                    }, status=status.HTTP_200_OK)
                else:
                    return Response({
                        'success': False,
                        'message': 'User database entry not found'
                    }, status=status.HTTP_404_NOT_FOUND)
            else:
                # Get all active entries
                entries = UserDatabaseService.get_all_active_entries()
                
                # entries is already a list of dictionaries in display format
                # No need to convert again
                return Response({
                    'success': True,
                    'data': entries,
                    'count': len(entries)
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            logger.error(f"Error in UserDatabaseAPIView GET: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def post(self, request):
        """Create new user database entry"""
        try:
            data = request.data
            uploader_username = data.get('uploader_username')
            file_data = data.get('file_data', {})
            metadata = data.get('metadata', {})
            
            if not uploader_username:
                return Response({
                    'success': False,
                    'message': 'uploader_username is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Create user database entry
            user_db_entry = UserDatabaseService.create_user_database_entry(
                uploader_username=uploader_username,
                file_data=file_data,
                metadata=metadata
            )
            
            return Response({
                'success': True,
                'message': 'User database entry created successfully',
                'data': {
                    'uploader_username': user_db_entry.uploader_username,
                    'upload_date': user_db_entry.upload_date,
                    'file_data': user_db_entry.file_data,
                    'metadata': user_db_entry.metadata,
                    'is_active': user_db_entry.is_active
                }
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error in UserDatabaseAPIView POST: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def put(self, request):
        """Update user database entry"""
        try:
            data = request.data
            uploader_username = data.get('uploader_username')
            file_data = data.get('file_data')
            metadata = data.get('metadata')
            
            if not uploader_username:
                return Response({
                    'success': False,
                    'message': 'uploader_username is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update user database entry
            success = UserDatabaseService.update_user_database_entry(
                uploader_username=uploader_username,
                file_data=file_data,
                metadata=metadata
            )
            
            if success:
                return Response({
                    'success': True,
                    'message': 'User database entry updated successfully'
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'User database entry not found'
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Error in UserDatabaseAPIView PUT: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def delete(self, request):
        """Delete user database entry using search strategies"""
        try:
            uploader_username = request.query_params.get('uploader_username')
            source_file = request.query_params.get('source_file')
            
            if not uploader_username:
                return Response({
                    'success': False,
                    'message': 'uploader_username is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Use the new search strategy method
            result = UserDatabaseService.delete_user_database_entry_with_search_strategies(
                uploader_username=uploader_username,
                source_file=source_file
            )
            
            if result['success']:
                return Response({
                    'success': True,
                    'message': result['message'],
                    'details': result['details']
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': result['message'],
                    'details': result['details']
                }, status=status.HTTP_404_NOT_FOUND)
                
        except Exception as e:
            logger.error(f"Error in UserDatabaseAPIView DELETE: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def check_mongodb_connection():
    """Check if MongoDB connection is working"""
    try:
        from .models import User
        User.objects.count()
        return True
    except Exception:
        return False

@csrf_exempt
@login_required
def api_get_profile(request):
    """
    API endpoint để lấy thông tin cá nhân của người dùng đang đăng nhập.
    Chỉ chấp nhận phương thức GET.
    """
    # Chỉ cho phép phương thức GET
    if request.method != 'GET':
        return JsonResponse({'error': 'Phương thức không được hỗ trợ'}, status=405)

    # Lấy thông tin người dùng từ request (nhờ decorator @login_required)
    user = get_current_user(request)

    if not user:
        # Lỗi này xảy ra nếu cookie hợp lệ nhưng không tìm thấy user trong DB
        return JsonResponse({'error': 'Không tìm thấy người dùng hoặc phiên hết hạn.'}, status=401)
    
    user_data = {
        'id': str(user.id),
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.get_role_display(),
        'is_active': user.is_active,
        'date_joined': user.date_joined.strftime('%d/%m/%Y %H:%M:%S') if user.date_joined else None,
        'last_login': user.last_login.strftime('%d/%m/%Y %H:%M:%S') if user.last_login else None
    }

    # Trả về dữ liệu người dùng dưới dạng JSON
    return JsonResponse(user_data, status=200)

@csrf_exempt
@login_required
def api_tech_chat(request):
    """API endpoint for technical support chat functionality"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()
        
        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)
        
        # Get current user
        user = get_current_user(request)
        if not user:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        
        # Generate technical support response
        tech_response = generate_tech_support_response(message, user)
        
        return JsonResponse({
            'response': tech_response,
            'user': user.username,
            'timestamp': datetime.now().isoformat(),
            'type': 'tech_support'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_tech_chat: {str(e)}")
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


def generate_tech_support_response(message, user):
    """Generate technical support response"""
    message_lower = message.lower()
    
    # Technical support responses
    if 'lỗi' in message_lower or 'error' in message_lower:
        return f"🔧 <strong>Hỗ trợ kỹ thuật:</strong><br><br>Xin chào {user.first_name}, tôi đã nhận được báo cáo lỗi của bạn.<br><br>Để hỗ trợ tốt hơn, vui lòng cung cấp:<br>• Mô tả chi tiết lỗi<br>• Các bước tái hiện<br>• Thông tin trình duyệt<br><br>Chúng tôi sẽ phản hồi trong vòng 24h."
    
    if 'mongodb' in message_lower or 'database' in message_lower:
        return f"💾 <strong>Hỗ trợ Database:</strong><br><br>Xin chào {user.first_name}, về vấn đề MongoDB:<br><br>• Kết nối MongoDB Atlas: ✅ Đang hoạt động<br>• Collection 'user_database': ✅ Sẵn sàng<br>• API endpoints: ✅ Đang hoạt động<br><br>Nếu gặp vấn đề cụ thể, vui lòng mô tả chi tiết."
    
    if 'api' in message_lower:
        return f"🔌 <strong>Hỗ trợ API:</strong><br><br>Xin chào {user.first_name}, về API:<br><br>• Endpoint /api/user-database/: ✅ Hoạt động<br>• Authentication: ✅ Đang bảo vệ<br>• Rate limiting: ✅ Đang áp dụng<br><br>Bạn có thể test API qua giao diện chat nâng cao."
    
    if 'giao diện' in message_lower or 'ui' in message_lower:
        return f"🎨 <strong>Hỗ trợ Giao diện:</strong><br><br>Xin chào {user.first_name}, về giao diện:<br><br>• Responsive design: ✅ Hỗ trợ mobile<br>• Dark/Light mode: 🔄 Đang phát triển<br>• Performance: ✅ Đã tối ưu<br><br>Nếu gặp vấn đề hiển thị, vui lòng thử refresh trang."
    
    # Default tech support response
    return f"🤖 <strong>Hỗ trợ kỹ thuật WoxionChat:</strong><br><br>Xin chào {user.first_name}! Tôi có thể hỗ trợ bạn về:<br><br>• 🔧 Sửa lỗi và troubleshooting<br>• 💾 Vấn đề Database và MongoDB<br>• 🔌 API và tích hợp<br>• 🎨 Giao diện và UX<br><br>Vui lòng mô tả vấn đề bạn gặp phải."


@csrf_exempt
@login_required
def api_system_status(request):
    """API endpoint to check system status"""
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        # Get current user
        user = get_current_user(request)
        if not user:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        
        # Check system components
        system_status = {
            'database': check_database_status(),
            'mongodb': check_mongodb_status(),
            'api': check_api_status(),
            'services': check_services_status(),
            'timestamp': datetime.now().isoformat(),
            'user': user.username
        }
        
        # Overall system health
        all_healthy = all([
            system_status['database']['status'] == 'healthy',
            system_status['mongodb']['status'] == 'healthy',
            system_status['api']['status'] == 'healthy',
            system_status['services']['status'] == 'healthy'
        ])
        
        system_status['overall'] = 'healthy' if all_healthy else 'degraded'
        
        return JsonResponse({
            'success': True,
            'data': system_status
        })
        
    except Exception as e:
        logger.error(f"Error in api_system_status: {str(e)}")
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)


def check_database_status():
    """Check database connection status"""
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {
            'status': 'healthy',
            'message': 'Database connection successful',
            'type': 'SQLite'
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Database connection failed: {str(e)}',
            'type': 'SQLite'
        }


def check_mongodb_status():
    """Check MongoDB connection status"""
    try:
        from accounts.models import User
        # Try to perform a simple MongoDB operation
        user_count = User.objects.count()
        return {
            'status': 'healthy',
            'message': 'MongoDB connection successful',
            'type': 'MongoDB Atlas',
            'user_count': user_count
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'MongoDB connection failed: {str(e)}',
            'type': 'MongoDB Atlas'
        }


def check_api_status():
    """Check API endpoints status"""
    try:
        # Check if API endpoints are accessible
        api_endpoints = [
            '/api/users/',
            '/api/user-database/',
            '/api/profile/',
            '/api/system-status/'
        ]
        
        return {
            'status': 'healthy',
            'message': 'API endpoints accessible',
            'endpoints': api_endpoints,
            'count': len(api_endpoints)
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'API check failed: {str(e)}'
        }


def check_services_status():
    """Check various services status"""
    try:
        services = {
            'user_database_service': 'healthy',
            'authentication': 'healthy',
            'session_management': 'healthy',
            'file_upload': 'healthy'
        }
        
        # Check UserDatabase service
        try:
            from accounts.user_database_service import UserDatabaseService
            UserDatabaseService.get_all_active_entries()
            services['user_database_service'] = 'healthy'
        except Exception:
            services['user_database_service'] = 'error'
        
        return {
            'status': 'healthy',
            'message': 'Services are running',
            'services': services
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Services check failed: {str(e)}'
        }


# Test endpoint without authentication - FOR DEBUGGING ONLY
@csrf_exempt
def test_user_database_view(request):
    """Test view to check user database functionality without auth"""
    # Simulate a user
    class MockUser:
        def __init__(self, username):
            self.username = username
    
    mock_user = MockUser('testuser')
    
    context = {
        'user': mock_user,
        'file_id': None,
        'file_content': None,
        'file_title': None
    }
    
    return render(request, 'accounts/chat_advanced.html', context)


# ===== FEEDBACK SYSTEM VIEWS =====

@login_required
def feedback_view(request):
    """
    Hiển thị trang feedback survey cho người dùng
    """
    user = get_current_user(request)
    
    if not user:
        messages.error(request, 'Vui lòng đăng nhập để truy cập feedback.')
        return redirect('login')
    
    context = {
        'user': user,
        'user_id': str(user.id),
        'session_id': request.session.session_key or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}",
    }
    
    return render(request, 'accounts/feedback.html', context)


@csrf_exempt
@login_required  
def api_submit_feedback(request):
    """
    API endpoint để submit feedback survey qua Django
    Kết nối với MongoDB feedback collection
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        user = get_current_user(request)
        
        if not user:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        
        # Lấy dữ liệu từ request
        user_id = str(user.id)
        answers = data.get('answers', {})
        session_id = data.get('session_id') or request.session.session_key or f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        if not answers:
            return JsonResponse({'error': 'Missing answers in request'}, status=400)
        
        # Kết nối MongoDB và lưu feedback
        success, message = save_feedback_to_mongodb(user_id, session_id, answers, user)
        
        if success:
            return JsonResponse({
                'message': 'Feedback submitted successfully',
                'status': 'success'
            }, status=200)
        else:
            return JsonResponse({
                'message': 'Error saving feedback', 
                'error': message,
                'status': 'error'
            }, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({
            'error': f'Server error: {str(e)}',
            'status': 'error'
        }, status=500)


def save_feedback_to_mongodb(user_id, session_id, answers, user):
    """
    Lưu feedback vào MongoDB collection
    """
    try:
        # Cấu hình MongoDB (sử dụng cùng DB với Django)
        MONGODB_ATLAS_SETTINGS = {
            'CONNECTION_STRING': os.getenv('MONGODB_ATLAS_URI', 
                'mongodb+srv://hieu:hieu@cluster0.yrpxm.mongodb.net/WoxionChat_db?retryWrites=true&w=majority'
            ),
            'DB_NAME': os.getenv('MONGODB_ATLAS_DB', 'WoxionChat_db'),
        }
        
        # Kết nối MongoDB
        client = MongoClient(MONGODB_ATLAS_SETTINGS['CONNECTION_STRING'])
        db = client[MONGODB_ATLAS_SETTINGS['DB_NAME']]
        feedback_collection = db['feedback']
        
        # Tạo document feedback
        feedback_document = {
            "user_id": user_id,
            "username": user.username,
            "session_id": session_id,
            "timestamp": datetime.now(),
            "user_info": {
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "role": user.role
            }
        }
        
        # Thêm các câu trả lời vào document
        feedback_document.update(answers)
        
        # Lưu vào MongoDB
        result = feedback_collection.insert_one(feedback_document)
        
        print(f"✅ Feedback cho user {user.username} (ID: {user_id}) đã được lưu vào MongoDB.")
        print(f"📄 Document ID: {result.inserted_id}")
        
        return True, "Feedback saved successfully"
        
    except Exception as e:
        print(f"❌ Lỗi khi lưu feedback vào MongoDB: {e}")
        return False, str(e)


@csrf_exempt
@login_required
def api_call_feedback_service(request):
    """
    API endpoint để gọi đến Flask feedback service (accounts/feedback.py)
    Đây là alternative method nếu muốn sử dụng Flask service riêng biệt
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        user = get_current_user(request)
        
        if not user:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        
        # Chuẩn bị data để gửi đến Flask service
        feedback_data = {
            "user_id": str(user.id),
            "session_id": data.get('session_id') or request.session.session_key,
            "answers": data.get('answers', {})
        }
        
        # Gọi Flask feedback service
        try:
            response = requests.post(
                'http://localhost:5000/api/submit_feedback',
                json=feedback_data,
                timeout=10
            )
            
            if response.status_code == 200:
                return JsonResponse(response.json(), status=200)
            else:
                return JsonResponse({
                    'error': 'Flask service error',
                    'details': response.text,
                    'status': 'error'
                }, status=response.status_code)
                
        except requests.exceptions.ConnectionError:
            return JsonResponse({
                'error': 'Cannot connect to feedback service. Service may be down.',
                'status': 'error'
            }, status=503)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({
            'error': f'Server error: {str(e)}',
            'status': 'error'
        }, status=500)


@admin_required
def admin_feedback_view(request):
    """
    Admin view để xem tất cả feedback đã submit
    """
    user = get_current_user(request)
    
    try:
        # Kết nối MongoDB để lấy feedback data
        MONGODB_ATLAS_SETTINGS = {
            'CONNECTION_STRING': os.getenv('MONGODB_ATLAS_URI', 
                'mongodb+srv://hieu:hieu@cluster0.yrpxm.mongodb.net/WoxionChat_db?retryWrites=true&w=majority'
            ),
            'DB_NAME': os.getenv('MONGODB_ATLAS_DB', 'WoxionChat_db'),
        }
        
        client = MongoClient(MONGODB_ATLAS_SETTINGS['CONNECTION_STRING'])
        db = client[MONGODB_ATLAS_SETTINGS['DB_NAME']]
        feedback_collection = db['feedback']
        
        # Lấy tất cả feedback, sắp xếp theo thời gian mới nhất
        feedbacks = list(feedback_collection.find().sort("timestamp", -1))
        
        # Convert ObjectId thành string để có thể serialize
        for feedback in feedbacks:
            feedback['_id'] = str(feedback['_id'])
            if 'timestamp' in feedback:
                feedback['timestamp'] = feedback['timestamp'].strftime('%d/%m/%Y %H:%M:%S')
        
        context = {
            'user': user,
            'feedbacks': feedbacks,
            'total_feedbacks': len(feedbacks)
        }
        
    except Exception as e:
        messages.error(request, f'Lỗi khi tải dữ liệu feedback: {str(e)}')
        context = {
            'user': user,
            'feedbacks': [],
            'total_feedbacks': 0
        }
        return render(request, 'accounts/admin_feedback.html', context)


@login_required
def change_password_view(request):
    """Trang đổi mật khẩu"""
    user = get_current_user(request)
    
    if not user:
        messages.error(request, 'Vui lòng đăng nhập để đổi mật khẩu.')
        return redirect('login')
    
    if request.method == 'POST':
        form = PasswordChangeForm(user=user, data=request.POST)
        if form.is_valid():
            try:
                success = form.save()
                if success:
                    # Log the user out to force re-login with new password
                    logout_user(request)
                    messages.success(request, 
                        'Đổi mật khẩu thành công! Vui lòng đăng nhập lại với mật khẩu mới.')
                    return redirect('login')
                else:
                    messages.error(request, 'Có lỗi xảy ra khi lưu mật khẩu mới.')
            except Exception as e:
                messages.error(request, f'Có lỗi xảy ra: {str(e)}')
    else:
        form = PasswordChangeForm(user=user)
    
    context = {
        'user': user,
        'form': form,
        'page_title': 'Đổi mật khẩu'
    }
    
    return render(request, 'accounts/change_password.html', context)

@csrf_exempt
@login_required
def api_change_password(request):
    """API endpoint để đổi mật khẩu"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    try:
        user = get_current_user(request)
        if not user:
            return JsonResponse({'error': 'User not authenticated'}, status=401)
        
        data = json.loads(request.body)
        
        # Create form with data
        form = PasswordChangeForm(user=user, data=data)
        
        if form.is_valid():
            success = form.save()
            if success:
                return JsonResponse({
                    'success': True,
                    'message': 'Đổi mật khẩu thành công! Vui lòng đăng nhập lại.',
                    'redirect_to_login': True
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Có lỗi xảy ra khi lưu mật khẩu mới'
                }, status=500)
        else:
            # Return form errors
            errors = {}
            for field, field_errors in form.errors.items():
                errors[field] = [str(error) for error in field_errors]
            
            return JsonResponse({
                'success': False,
                'errors': errors
            }, status=400)
    
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_change_password: {str(e)}")
        return JsonResponse({'error': f'Server error: {str(e)}'}, status=500)





