from accounts.models import User
from accounts.utils import create_user_session

# Hàm xử lý sau khi đăng nhập Google: tạo user MongoDB nếu chưa có và đồng bộ session custom

def process_login_gg(strategy, details, backend, user=None, *args, **kwargs):
    email = details.get('email')
    fullname = details.get('fullname') or ''
    first_name = details.get('first_name') or (fullname.split(' ')[0] if fullname else '')
    last_name = details.get('last_name') or (' '.join(fullname.split(' ')[1:]) if fullname else '')
    username = email.split('@')[0] if email else ''
    password = 'google_oauth2_default_password'

    mongo_user = User.objects(email=email).first()
    if not mongo_user and email:
        mongo_user = User(
            username=username,
            email=email,
            first_name=first_name or username,
            last_name=last_name or '',
            is_active=True,
            is_verified=True,
        )
        mongo_user.set_password(password)
        mongo_user.save()

    # Tạo session custom cho user Google
    if mongo_user:
        request = strategy.request
        create_user_session(request, mongo_user)

# Middleware đồng bộ session custom sau khi đăng nhập Google
class SyncCustomSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.session.get('username') and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False) and getattr(request.user, 'email', None):
            mongo_user = User.objects(email=request.user.email).first()
            if mongo_user:
                create_user_session(request, mongo_user)
        return self.get_response(request)
