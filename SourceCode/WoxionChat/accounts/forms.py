from django import forms
from django.core.exceptions import ValidationError
from .models import User
import re


class CustomUserCreationForm(forms.Form):
    """Form để đăng ký user với MongoDB"""
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập tên đăng nhập'
        })
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Nhập email của bạn'
        })
    )
    first_name = forms.CharField(
        max_length=100, 
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Nhập tên của bạn'
        })
    )
    last_name = forms.CharField(
        max_length=100, 
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Nhập họ của bạn'
        })
    )
    role = forms.ChoiceField(
        choices=User.ROLES,
        initial='user',
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        help_text='Chọn vai trò cho người dùng'
    )
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập mật khẩu'
        })
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập lại mật khẩu'
        })
    )

    def __init__(self, user=None, *args, **kwargs):
        self.current_user = user
        super().__init__(*args, **kwargs)
        
        # Only show role field if user is admin
        if not self.current_user or not self.current_user.is_admin():
            # Remove role field for regular users, default to 'user'
            del self.fields['role']

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects(username=username).first():
            raise ValidationError("Tên đăng nhập đã tồn tại")
        
        # Validate username format
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise ValidationError("Tên đăng nhập chỉ được chứa chữ cái, số và dấu gạch dưới")
        
        if len(username) < 3:
            raise ValidationError("Tên đăng nhập phải có ít nhất 3 ký tự")
            
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects(email=email).first():
            raise ValidationError("Email này đã được sử dụng")
        return email

    def clean_role(self):
        role = self.cleaned_data.get('role', 'user')
        
        # Only admin can create admin users
        if role == 'admin' and self.current_user and not self.current_user.is_admin():
            raise ValidationError("Chỉ quản trị viên mới có thể tạo tài khoản quản trị viên")
            
        return role

    def clean_password1(self):
        password1 = self.cleaned_data['password1']
        
        # Validate password strength
        if len(password1) < 8:
            raise ValidationError("Mật khẩu phải có ít nhất 8 ký tự")
        
        if not re.search(r'[A-Za-z]', password1):
            raise ValidationError("Mật khẩu phải chứa ít nhất một chữ cái")
        
        if not re.search(r'[0-9]', password1):
            raise ValidationError("Mật khẩu phải chứa ít nhất một chữ số")

        if not re.search(r'[!@#$%^&*()_+{}\[\]:;<>,.?~\\/-]', password1):
            raise ValidationError("Mật khẩu phải chứa ít nhất một ký tự đặc biệt")
        
        if not re.search(r'[A-Z]', password1):
            raise ValidationError("Mật khẩu phải chứa ít nhất một chữ cái viết hoa")
        
        if not re.search(r'[a-z]', password1):
            raise ValidationError("Mật khẩu phải chứa ít nhất một chữ cái viết thường")
            
        return password1

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
        
        if password1 and password2 and password1 != password2:
            raise ValidationError("Mật khẩu xác nhận không khớp")
        
        return password2

    def save(self):
        """Create and save new user"""
        try:
            role = self.cleaned_data.get('role', 'user')
            user = User.create_user(
                username=self.cleaned_data['username'],
                email=self.cleaned_data['email'],
                first_name=self.cleaned_data['first_name'],
                last_name=self.cleaned_data['last_name'],
                password=self.cleaned_data['password1'],
                role=role
            )
            return user
        except ValueError as e:
            raise ValidationError(str(e))


class LoginForm(forms.Form):
    """Form đăng nhập"""
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập tên đăng nhập'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập mật khẩu'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if username and password:
            user = User.authenticate(username, password)
            if not user:
                raise ValidationError("Tên đăng nhập hoặc mật khẩu không đúng")
            cleaned_data['user'] = user
        
        return cleaned_data


class UserUpdateForm(forms.Form):
    """Form cập nhật thông tin user"""
    first_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập tên của bạn'
        })
    )
    last_name = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập họ của bạn'
        })
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập email của bạn'
        })
    )
    role = forms.ChoiceField(
        choices=User.ROLES,
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        required=False
    )
    is_active = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )
    permissions = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Nhập quyền đặc biệt (cách nhau bởi dấu phẩy)'
        }),
        help_text='Quyền đặc biệt (cách nhau bởi dấu phẩy)'
    )

    def __init__(self, instance=None, current_user=None, *args, **kwargs):
        self.instance = instance
        self.current_user = current_user
        super().__init__(*args, **kwargs)
        
        # Set initial values if instance provided
        if instance:
            self.fields['first_name'].initial = instance.first_name
            self.fields['last_name'].initial = instance.last_name
            self.fields['email'].initial = instance.email
            self.fields['role'].initial = instance.role
            self.fields['is_active'].initial = instance.is_active
            self.fields['permissions'].initial = ', '.join(instance.permissions) if instance.permissions else ''
        
        # If current user is not admin, hide admin-only fields
        if not self.current_user or not self.current_user.is_admin():
            if 'role' in self.fields:
                del self.fields['role']
            if 'is_active' in self.fields:
                del self.fields['is_active']
            if 'permissions' in self.fields:
                del self.fields['permissions']

    def clean_email(self):
        email = self.cleaned_data['email']
        # Check if email exists for other users
        existing_user = User.objects(email=email).first()
        if existing_user and existing_user.id != self.instance.id:
            raise ValidationError("Email này đã được sử dụng bởi người dùng khác")
        return email

    def clean_role(self):
        role = self.cleaned_data.get('role')
        
        # Only admin can change roles
        if self.current_user and not self.current_user.is_admin():
            return self.instance.role  # Keep original role
        
        # Only admin can create/assign admin role
        if role == 'admin' and self.current_user and not self.current_user.is_admin():
            raise ValidationError("Chỉ quản trị viên mới có thể gán vai trò quản trị viên")
            
        return role

    def clean_permissions(self):
        permissions = self.cleaned_data.get('permissions', '')
        if permissions:
            # Clean and validate permissions
            perm_list = [p.strip() for p in permissions.split(',') if p.strip()]
            return perm_list
        return []

    def save(self):
        """Save the updated user data"""
        if not self.instance:
            raise ValueError("No instance to update")
        
        # Update basic fields
        self.instance.first_name = self.cleaned_data['first_name']
        self.instance.last_name = self.cleaned_data['last_name']
        self.instance.email = self.cleaned_data['email']
        
        # Update admin-only fields if current user is admin
        if self.current_user and self.current_user.is_admin():
            if 'role' in self.cleaned_data:
                self.instance.role = self.cleaned_data['role']
            if 'is_active' in self.cleaned_data:
                self.instance.is_active = self.cleaned_data['is_active']
            if 'permissions' in self.cleaned_data:
                self.instance.permissions = self.cleaned_data['permissions']
        
        self.instance.save()
        return self.instance


class RoleChangeForm(forms.Form):
    """Form đơn giản để thay đổi role"""
    role = forms.ChoiceField(
        choices=User.ROLES,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )

    def __init__(self, current_user, target_user, *args, **kwargs):
        self.current_user = current_user
        self.target_user = target_user
        super().__init__(*args, **kwargs)

    def clean_role(self):
        role = self.cleaned_data['role']
        
        # Only admin can change roles to admin
        if role == 'admin' and not self.current_user.is_admin():
            raise ValidationError("Chỉ quản trị viên mới có thể gán vai trò quản trị viên")
            
        return role 


class PasswordChangeForm(forms.Form):
    """Form đổi mật khẩu người dùng"""
    current_password = forms.CharField(
        label='Mật khẩu hiện tại',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập mật khẩu hiện tại'
        }),
        help_text='Nhập mật khẩu hiện tại để xác thực'
    )
    
    new_password1 = forms.CharField(
        label='Mật khẩu mới',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập mật khẩu mới'
        }),
        help_text='Mật khẩu phải có ít nhất 8 ký tự, bao gồm chữ và số'
    )
    
    new_password2 = forms.CharField(
        label='Xác nhận mật khẩu mới',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập lại mật khẩu mới'
        }),
        help_text='Nhập lại mật khẩu mới để xác nhận'
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        """Validate current password"""
        current_password = self.cleaned_data.get('current_password')
        
        if not current_password:
            raise ValidationError('Mật khẩu hiện tại là bắt buộc')
        
        # Check if current password is correct
        if not self.user.check_password(current_password):
            raise ValidationError('Mật khẩu hiện tại không đúng')
        
        return current_password
    
    def clean_new_password1(self):
        """Validate new password strength"""
        password = self.cleaned_data.get('new_password1')
        
        if not password:
            raise ValidationError('Mật khẩu mới là bắt buộc')
        
        # Check minimum length
        if len(password) < 8:
            raise ValidationError('Mật khẩu phải có ít nhất 8 ký tự')
        
        # Check if password contains both letters and numbers
        has_letter = any(c.isalpha() for c in password)
        has_digit = any(c.isdigit() for c in password)
        
        if not (has_letter and has_digit):
            raise ValidationError('Mật khẩu phải bao gồm cả chữ và số')
        
        # Check if new password is different from current password
        current_password = self.data.get('current_password')
        if current_password and password == current_password:
            raise ValidationError('Mật khẩu mới phải khác với mật khẩu hiện tại')
        
        return password
    
    def clean_new_password2(self):
        """Validate password confirmation"""
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        
        if not password2:
            raise ValidationError('Xác nhận mật khẩu là bắt buộc')
        
        if password1 and password2 and password1 != password2:
            raise ValidationError('Mật khẩu xác nhận không khớp')
        
        return password2
    
    def save(self):
        """Save new password"""
        try:
            new_password = self.cleaned_data['new_password1']
            self.user.set_password(new_password)
            self.user.save()
            return True
        except Exception as e:
            print(f"Error saving new password: {e}")
            return False 