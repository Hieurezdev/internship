from django.core.management.base import BaseCommand, CommandError
from accounts.models import User


class Command(BaseCommand):
    help = 'Thay đổi vai trò của người dùng (chỉ hỗ trợ admin và user)'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Tên đăng nhập của người dùng')
        parser.add_argument('role', type=str, choices=['admin', 'user'], 
                          help='Vai trò mới (admin hoặc user)')

    def handle(self, *args, **options):
        username = options['username']
        new_role = options['role']
        
        try:
            # Tìm user
            user = User.objects.get(username=username)
            
            # Lưu vai trò cũ
            old_role = user.get_role_display()
            
            # Cập nhật vai trò
            user.role = new_role
            user.save()  # This will automatically update is_staff and is_superuser
            
            new_role_display = user.get_role_display()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Đã thay đổi vai trò của "{username}" từ "{old_role}" thành "{new_role_display}"'
                )
            )
            
            # Hiển thị thông tin chi tiết
            self.stdout.write(f'👤 Họ tên: {user.get_full_name()}')
            self.stdout.write(f'📧 Email: {user.email}')
            self.stdout.write(f'🏷️  Vai trò: {user.get_role_display()}')
            self.stdout.write(f'⚙️  Django Staff: {user.is_staff}')
            self.stdout.write(f'🔑 Django Superuser: {user.is_superuser}')
            
        except User.DoesNotExist:
            raise CommandError(f'❌ Không tìm thấy người dùng với username "{username}"')
        except Exception as e:
            raise CommandError(f'❌ Lỗi khi thay đổi vai trò: {str(e)}') 