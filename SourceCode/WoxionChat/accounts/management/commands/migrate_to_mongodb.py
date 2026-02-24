from django.core.management.base import BaseCommand
import sqlite3
import os
from accounts.models import User
from datetime import datetime
from django.conf import settings

class Command(BaseCommand):
    help = 'Migrate data from SQLite to MongoDB'

    def handle(self, *args, **options):
        """Migrate existing SQLite data to MongoDB"""
        
        # Path to SQLite database
        sqlite_db_path = os.path.join(settings.BASE_DIR, 'db.sqlite3')
        
        if not os.path.exists(sqlite_db_path):
            self.stdout.write(
                self.style.WARNING('SQLite database not found. No data to migrate.')
            )
            return
        
        try:
            # Connect to SQLite database
            conn = sqlite3.connect(sqlite_db_path)
            cursor = conn.cursor()
            
            # Check if auth_user table exists (Django's default user table)
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='auth_user';
            """)
            
            if not cursor.fetchone():
                self.stdout.write(
                    self.style.WARNING('No Django user table found in SQLite database.')
                )
                conn.close()
                return
            
            # Get all users from SQLite
            cursor.execute("""
                SELECT id, username, first_name, last_name, email, 
                       is_staff, is_active, is_superuser, date_joined, last_login, password
                FROM auth_user
            """)
            
            users = cursor.fetchall()
            migrated_count = 0
            skipped_count = 0
            
            for user_data in users:
                (user_id, username, first_name, last_name, email, 
                 is_staff, is_active, is_superuser, date_joined, last_login, hashed_password) = user_data
                
                # Check if user already exists in MongoDB
                if User.objects(username=username).first():
                    self.stdout.write(
                        self.style.WARNING(f'User {username} already exists in MongoDB. Skipping.')
                    )
                    skipped_count += 1
                    continue
                
                # Determine role based on Django flags
                role = 'admin' if is_superuser or is_staff else 'user'
                
                # Parse date strings
                try:
                    date_joined_dt = datetime.fromisoformat(date_joined.replace('Z', '+00:00')) if date_joined else datetime.now()
                    last_login_dt = datetime.fromisoformat(last_login.replace('Z', '+00:00')) if last_login else None
                except:
                    date_joined_dt = datetime.now()
                    last_login_dt = None
                
                # Create MongoDB user
                mongo_user = User(
                    username=username,
                    email=email or f"{username}@example.com",  # Fallback email
                    first_name=first_name or username,
                    last_name=last_name or "",
                    password=hashed_password,  # Keep the hashed password
                    role=role,
                    is_active=bool(is_active),
                    is_staff=bool(is_staff),
                    is_superuser=bool(is_superuser),
                    date_joined=date_joined_dt,
                    last_login=last_login_dt,
                    is_verified=True  # Assume migrated users are verified
                )
                
                try:
                    mongo_user.save()
                    migrated_count += 1
                    self.stdout.write(f'✅ Migrated user: {username} ({role})')
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'❌ Failed to migrate user {username}: {e}')
                    )
            
            conn.close()
            
            # Summary
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n🎉 Migration completed!\n'
                    f'✅ Successfully migrated: {migrated_count} users\n'
                    f'⚠️  Skipped (already exists): {skipped_count} users\n'
                    f'📝 Total processed: {len(users)} users'
                )
            )
            
            if migrated_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n🗑️  You can now safely delete the SQLite database file: db.sqlite3'
                    )
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Migration failed: {e}')
            ) 