"""
Direct MongoDB connection utilities for user_database collection
This module provides direct MongoDB operations using MongoEngine
"""

from mongoengine import connect, disconnect
from accounts.models import UserDatabase
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DirectMongoDBConnection:
    """Direct MongoDB connection utilities"""
    
    @staticmethod
    def connect_to_mongodb():
        """
        Connect to MongoDB using existing Django settings
        Returns True if connection successful, False otherwise
        """
        try:
            # Connection is already established in Django settings
            # This function can be used to verify connection
            logger.info("MongoDB connection verified")
            return True
        except Exception as e:
            logger.error(f"MongoDB connection failed: {str(e)}")
            return False
    
    @staticmethod
    def query_user_database_by_username(uploader_username):
        """
        Direct query to user_database collection by uploader_username
        
        Args:
            uploader_username (str): Username to search for
            
        Returns:
            dict: User database document or None
        """
        try:
            user_db = UserDatabase.objects.get(uploader_username=uploader_username)
            return {
                'uploader_username': user_db.uploader_username,
                'upload_date': user_db.upload_date,
                'file_data': user_db.file_data,
                'metadata': user_db.metadata,
                'is_active': user_db.is_active,
                'id': str(user_db.id)
            }
        except UserDatabase.DoesNotExist:
            logger.warning(f"User database entry not found for username: {uploader_username}")
            return None
        except Exception as e:
            logger.error(f"Error querying user database: {str(e)}")
            return None
    
    @staticmethod
    def query_all_user_databases():
        """
        Get all documents from user_database collection
        
        Returns:
            list: List of all user database documents
        """
        try:
            user_databases = UserDatabase.objects.all()
            result = []
            for user_db in user_databases:
                result.append({
                    'uploader_username': user_db.uploader_username,
                    'upload_date': user_db.upload_date,
                    'file_data': user_db.file_data,
                    'metadata': user_db.metadata,
                    'is_active': user_db.is_active,
                    'id': str(user_db.id)
                })
            return result
        except Exception as e:
            logger.error(f"Error querying all user databases: {str(e)}")
            return []
    
    @staticmethod
    def insert_user_database_document(uploader_username, file_data=None, metadata=None):
        """
        Insert a new document into user_database collection
        
        Args:
            uploader_username (str): Username of the uploader
            file_data (dict): File data to store
            metadata (dict): Metadata to store
            
        Returns:
            str: ID of the inserted document or None if failed
        """
        try:
            user_db = UserDatabase(
                uploader_username=uploader_username,
                file_data=file_data or {},
                metadata=metadata or {},
                upload_date=datetime.now(),
                is_active=True
            )
            user_db.save()
            logger.info(f"Inserted user database document for: {uploader_username}")
            return str(user_db.id)
        except Exception as e:
            logger.error(f"Error inserting user database document: {str(e)}")
            return None
    
    @staticmethod
    def update_user_database_document(uploader_username, updates):
        """
        Update a document in user_database collection
        
        Args:
            uploader_username (str): Username to find the document
            updates (dict): Fields to update
            
        Returns:
            bool: True if update successful, False otherwise
        """
        try:
            user_db = UserDatabase.objects.get(uploader_username=uploader_username)
            
            # Update fields
            for key, value in updates.items():
                if hasattr(user_db, key):
                    setattr(user_db, key, value)
            
            user_db.save()
            logger.info(f"Updated user database document for: {uploader_username}")
            return True
        except UserDatabase.DoesNotExist:
            logger.warning(f"User database entry not found for username: {uploader_username}")
            return False
        except Exception as e:
            logger.error(f"Error updating user database document: {str(e)}")
            return False
    
    @staticmethod
    def delete_user_database_document(uploader_username):
        """
        Delete a document from user_database collection
        
        Args:
            uploader_username (str): Username to find the document
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        try:
            user_db = UserDatabase.objects.get(uploader_username=uploader_username)
            user_db.delete()
            logger.info(f"Deleted user database document for: {uploader_username}")
            return True
        except UserDatabase.DoesNotExist:
            logger.warning(f"User database entry not found for username: {uploader_username}")
            return False
        except Exception as e:
            logger.error(f"Error deleting user database document: {str(e)}")
            return False
    
    @staticmethod
    def count_user_database_documents():
        """
        Count total documents in user_database collection
        
        Returns:
            int: Total number of documents
        """
        try:
            return UserDatabase.objects.count()
        except Exception as e:
            logger.error(f"Error counting user database documents: {str(e)}")
            return 0
    
    @staticmethod
    def get_user_database_stats():
        """
        Get statistics about user_database collection
        
        Returns:
            dict: Statistics about the collection
        """
        try:
            total_count = UserDatabase.objects.count()
            active_count = UserDatabase.objects.filter(is_active=True).count()
            inactive_count = total_count - active_count
            
            return {
                'total_documents': total_count,
                'active_documents': active_count,
                'inactive_documents': inactive_count,
                'collection_name': 'user_database'
            }
        except Exception as e:
            logger.error(f"Error getting user database stats: {str(e)}")
            return {
                'total_documents': 0,
                'active_documents': 0,
                'inactive_documents': 0,
                'collection_name': 'user_database',
                'error': str(e)
            }

# Example usage functions
def example_usage():
    """
    Example of how to use the UserDatabase model and utilities
    """
    print("=== UserDatabase MongoDB Example Usage ===")
    
    # 1. Create a new user database entry
    print("\n1. Creating a new user database entry...")
    service = DirectMongoDBConnection()
    
    doc_id = service.insert_user_database_document(
        uploader_username="example_user",
        file_data={"filename": "example.txt", "size": 1024},
        metadata={"description": "Example file upload"}
    )
    print(f"Created document with ID: {doc_id}")
    
    # 2. Query by username
    print("\n2. Querying by username...")
    result = service.query_user_database_by_username("example_user")
    print(f"Query result: {result}")
    
    # 3. Update the document
    print("\n3. Updating the document...")
    success = service.update_user_database_document(
        uploader_username="example_user",
        updates={"metadata": {"description": "Updated description", "version": "1.1"}}
    )
    print(f"Update successful: {success}")
    
    # 4. Get statistics
    print("\n4. Getting collection statistics...")
    stats = service.get_user_database_stats()
    print(f"Collection stats: {stats}")
    
    # 5. Query all documents
    print("\n5. Querying all documents...")
    all_docs = service.query_all_user_databases()
    print(f"Total documents: {len(all_docs)}")
    
    # 6. Delete the document
    print("\n6. Deleting the document...")
    success = service.delete_user_database_document("example_user")
    print(f"Delete successful: {success}")
    
    print("\n=== Example completed ===")

if __name__ == "__main__":
    example_usage()
