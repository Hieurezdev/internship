from django.core.management.base import BaseCommand
from accounts.models import User


class Command(BaseCommand):
    help = 'Liệt kê tất cả người dùng trong hệ thống (chỉ có admin và user)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--role',
            type=str,
            choices=['admin', 'user'],
            help='Lọc theo vai trò (admin hoặc user)',
        )
        parser.add_argument(
            '--stats',
            action='store_true',
            help='Hiển thị thống kê chi tiết',
        )

    def handle(self, *args, **options):
        role_filter = options.get('role')
        show_stats = options.get('stats')
        
        try:
            # Get users based on filter
            if role_filter:
                users = User.objects(role=role_filter).order_by('username')
                self.stdout.write(f'👥 Danh sách người dùng có vai trò "{dict(User.ROLES)[role_filter]}":')
            else:
                users = User.objects.all().order_by('username')
                self.stdout.write('👥 Danh sách tất cả người dùng:')
            
            self.stdout.write('-' * 80)
            
            if not users:
                self.stdout.write(self.style.WARNING('Không có người dùng nào.'))
                return
            
            # Display users
            for i, user in enumerate(users, 1):
                role_icon = '👑' if user.role == 'admin' else '👤'
                status_icon = '✅' if user.is_active else '❌'
                
                self.stdout.write(
                    f'{i:2d}. {role_icon} {user.username:<15} | '
                    f'{user.get_full_name():<25} | '
                    f'{user.email:<30} | '
                    f'{user.get_role_display():<15} | '
                    f'{status_icon}'
                )
                
                if user.last_login:
                    last_login = user.last_login.strftime('%d/%m/%Y %H:%M')
                else:
                    last_login = 'Chưa đăng nhập'
                
                self.stdout.write(
                    f'    📅 Ngày tham gia: {user.date_joined.strftime("%d/%m/%Y")} | '
                    f'🕐 Lần cuối đăng nhập: {last_login}'
                )
                
                if user.permissions:
                    self.stdout.write(f'    🔑 Quyền đặc biệt: {", ".join(user.permissions)}')
                
                self.stdout.write('')  # Empty line
            
            # Show statistics
            if show_stats:
                self.show_statistics()
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Lỗi khi lấy danh sách người dùng: {str(e)}')
            )

    def show_statistics(self):
        """Hiển thị thống kê chi tiết"""
        try:
            self.stdout.write('=' * 80)
            self.stdout.write('📊 THỐNG KÊ HỆ THỐNG')
            self.stdout.write('=' * 80)
            
            # Total users
            total_users = User.objects.count()
            active_users = User.objects(is_active=True).count()
            inactive_users = total_users - active_users
            
            self.stdout.write(f'📈 Tổng quan:')
            self.stdout.write(f'   • Tổng số người dùng: {total_users}')
            self.stdout.write(f'   • Người dùng hoạt động: {active_users}')
            self.stdout.write(f'   • Người dùng không hoạt động: {inactive_users}')
            self.stdout.write('')
            
            # Role statistics (simplified for admin and user only)
            admin_count = User.objects(role='admin').count()
            user_count = User.objects(role='user').count()
            
            self.stdout.write(f'🏷️  Phân bố vai trò:')
            self.stdout.write(f'   👑 Quản trị viên: {admin_count} người ({admin_count/total_users*100:.1f}%)')
            self.stdout.write(f'   👤 Người dùng: {user_count} người ({user_count/total_users*100:.1f}%)')
            self.stdout.write('')
            
            # Login statistics
            users_with_login = User.objects(last_login__ne=None).count()
            users_never_login = total_users - users_with_login
            
            self.stdout.write(f'🔐 Thống kê đăng nhập:')
            self.stdout.write(f'   • Đã từng đăng nhập: {users_with_login} người')
            self.stdout.write(f'   • Chưa từng đăng nhập: {users_never_login} người')
            self.stdout.write('')
            
            # Recent users
            recent_users = User.objects.order_by('-date_joined')[:5]
            self.stdout.write(f'🆕 5 người dùng mới nhất:')
            for i, user in enumerate(recent_users, 1):
                role_icon = '👑' if user.role == 'admin' else '👤'
                self.stdout.write(
                    f'   {i}. {role_icon} {user.username} ({user.get_role_display()}) - '
                    f'{user.date_joined.strftime("%d/%m/%Y")}'
                )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Lỗi khi tạo thống kê: {str(e)}')
            ) 