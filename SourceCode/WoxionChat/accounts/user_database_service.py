"""
MongoDB Service for UserDatabase operations
This service provides methods to interact with the user_database collection
"""

from accounts.models import UserDatabase, DocumentProcessing
from mongoengine import connect, disconnect
import logging
from datetime import datetime
import re

logger = logging.getLogger(__name__)

class UserDatabaseService:
    """Service class for UserDatabase operations"""
    
    @staticmethod
    def create_user_database_entry(uploader_username, file_data=None, metadata=None):
        """
        Create a new user database entry (legacy format)
        
        Args:
            uploader_username (str): The username of the uploader
            file_data (dict): Optional file data to store
            metadata (dict): Optional metadata to store
            
        Returns:
            UserDatabase: The created user database entry
        """
        try:
            user_db_entry = UserDatabase(
                uploader_username=uploader_username,
                file_data=file_data or {},
                metadata=metadata or {},
                upload_date=datetime.now()
            )
            user_db_entry.save()
            logger.info(f"Created user database entry for: {uploader_username}")
            return user_db_entry
        except Exception as e:
            logger.error(f"Error creating user database entry: {str(e)}")
            raise
    
    @staticmethod
    def get_user_database_by_username(uploader_username):
        """
        Get user database entry by uploader_username (from document processing)
        
        Args:
            uploader_username (str): The username to search for
            
        Returns:
            DocumentProcessing: The first document processing entry found, or None
        """
        try:
            entries = DocumentProcessing.get_by_uploader_username(uploader_username)
            return entries.first() if entries else None
        except Exception as e:
            logger.error(f"Error getting user database entry: {str(e)}")
            return None
    
    @staticmethod
    def get_all_user_databases_by_username(uploader_username):
        """
        Get all user database entries by uploader_username (from document processing)
        
        Args:
            uploader_username (str): The username to search for
            
        Returns:
            QuerySet: All document processing entries for the user
        """
        try:
            return DocumentProcessing.get_by_uploader_username(uploader_username)
        except Exception as e:
            logger.error(f"Error getting user database entries: {str(e)}")
            return []
    
    @staticmethod
    def update_user_database_entry(uploader_username, file_data=None, metadata=None):
        """
        Update user database entry (legacy format only)
        
        Args:
            uploader_username (str): The username to update
            file_data (dict): Optional file data to update
            metadata (dict): Optional metadata to update
            
        Returns:
            UserDatabase: The updated user database entry
        """
        try:
            user_db_entry = UserDatabase.objects.get(uploader_username=uploader_username)
            
            if file_data:
                user_db_entry.file_data.update(file_data)
            
            if metadata:
                user_db_entry.metadata.update(metadata)
            
            user_db_entry.save()
            logger.info(f"Updated user database entry for: {uploader_username}")
            return user_db_entry
            
        except UserDatabase.DoesNotExist:
            logger.warning(f"User database entry not found for: {uploader_username}")
            return None
        except Exception as e:
            logger.error(f"Error updating user database entry: {str(e)}")
            raise
    
    @staticmethod
    def delete_user_database_entry(uploader_username):
        """
        Delete user database entry (legacy format only)
        
        Args:
            uploader_username (str): The username to delete
            
        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            user_db_entry = UserDatabase.objects.get(uploader_username=uploader_username)
            user_db_entry.delete()
            logger.info(f"Deleted user database entry for: {uploader_username}")
            return True
            
        except UserDatabase.DoesNotExist:
            logger.warning(f"User database entry not found for: {uploader_username}")
            return False
        except Exception as e:
            logger.error(f"Error deleting user database entry: {str(e)}")
            raise
    
    @staticmethod
    def get_all_active_entries():
        """
        Get all active user database entries (from document processing)
        
        Returns:
            List: All active document processing entries in display format
        """
        try:
            # Get all completed document processing entries
            entries = DocumentProcessing.get_all_active_entries()
            
            # Convert to display format
            result = []
            for entry in entries:
                try:
                    display_format = entry.to_display_format()
                    result.append(display_format)
                except Exception as e:
                    logger.warning(f"Error converting entry to display format: {str(e)}")
                    continue
            
            logger.info(f"Retrieved {len(result)} active document processing entries")
            return result
            
        except Exception as e:
            logger.error(f"Error getting active user database entries: {str(e)}")
            return []
    
    @staticmethod
    def search_by_partial_username(partial_username):
        """
        Search for user database entries by partial username match (from document processing)
        
        Args:
            partial_username (str): Partial username to search for
            
        Returns:
            List: Document processing entries matching the partial username in display format
        """
        try:
            entries = DocumentProcessing.objects.filter(
                uploader_username__icontains=partial_username,
                status='completed'
            )
            
            # Convert to display format
            result = []
            for entry in entries:
                try:
                    display_format = entry.to_display_format()
                    result.append(display_format)
                except Exception as e:
                    logger.warning(f"Error converting entry to display format: {str(e)}")
                    continue
            
            return result
            
        except Exception as e:
            logger.error(f"Error searching user database entries: {str(e)}")
            return []

    @staticmethod
    def get_user_documents_with_content(uploader_username):
        """
        Get user documents with full content for analysis
        
        Args:
            uploader_username (str): The username to search for
            
        Returns:
            List: Document processing entries with full content
        """
        try:
            entries = DocumentProcessing.objects.filter(
                uploader_username=uploader_username,
                status='completed'
            )
            
            result = []
            for entry in entries:
                result.append({
                    'filename': entry.get_filename(),
                    'content': entry.raw_markdown,
                    'created_at': entry.created_at,
                    'processing_time': entry.processing_time_seconds,
                    'file_type': entry.get_file_type()
                })
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting user documents with content: {str(e)}")
            return []

    @staticmethod
    def delete_user_database_entry_with_search_strategies(uploader_username, source_file=None):
        """
        Delete user database entry using the same search strategies as chunking
        
        Args:
            uploader_username (str): The username to delete
            source_file (str): Optional source file identifier
            
        Returns:
            dict: Result with success status and details
        """
        try:
            logger.info(f"🗑️ DATABASE DELETE: Searching for user: {uploader_username}, file: {source_file}")
            
            # Use same search strategies as chunking
            document = None
            strategy_used = None
            
            # Strategy 1: Exact match (username + source_file)
            if source_file and source_file != 'unknown':
                try:
                    document = DocumentProcessing.objects.get(
                        uploader_username=uploader_username,
                        source_file=source_file
                    )
                    strategy_used = "Strategy 1: Exact match (username + source_file)"
                    logger.info(f"🗑️ DATABASE DELETE: {strategy_used} - Found")
                except DocumentProcessing.DoesNotExist:
                    logger.info(f"🗑️ DATABASE DELETE: Strategy 1 - Not found")
            
            # Strategy 2: Source file only (if not found in strategy 1)
            if not document and source_file and source_file != 'unknown':
                try:
                    document = DocumentProcessing.objects.get(source_file=source_file)
                    strategy_used = "Strategy 2: Source file only"
                    logger.info(f"🗑️ DATABASE DELETE: {strategy_used} - Found")
                except DocumentProcessing.DoesNotExist:
                    logger.info(f"🗑️ DATABASE DELETE: Strategy 2 - Not found")
            
            # Strategy 3: MongoDB ObjectId lookup (if source_file looks like ObjectId)
            if not document and source_file and len(source_file) == 24:
                try:
                    from bson import ObjectId
                    document = DocumentProcessing.objects.get(id=ObjectId(source_file))
                    strategy_used = "Strategy 3: MongoDB ObjectId lookup"
                    logger.info(f"🗑️ DATABASE DELETE: {strategy_used} - Found")
                except (DocumentProcessing.DoesNotExist, Exception):
                    logger.info(f"🗑️ DATABASE DELETE: Strategy 3 - Not found")
            
            # Strategy 4: Filename search in file_data
            if not document and source_file and source_file != 'unknown':
                try:
                    document = DocumentProcessing.objects.get(
                        uploader_username=uploader_username,
                        file_data__filename=source_file
                    )
                    strategy_used = "Strategy 4: Filename search in file_data"
                    logger.info(f"🗑️ DATABASE DELETE: {strategy_used} - Found")
                except DocumentProcessing.DoesNotExist:
                    logger.info(f"🗑️ DATABASE DELETE: Strategy 4 - Not found")
            
            # Strategy 5: Regex partial matching
            if not document and source_file and source_file != 'unknown':
                try:
                    regex_pattern = re.compile(re.escape(source_file), re.IGNORECASE)
                    candidates = DocumentProcessing.objects.filter(
                        uploader_username=uploader_username,
                        source_file__regex=regex_pattern
                    )
                    if candidates:
                        document = candidates.first()
                        strategy_used = "Strategy 5: Regex partial matching"
                        logger.info(f"🗑️ DATABASE DELETE: {strategy_used} - Found")
                    else:
                        logger.info(f"🗑️ DATABASE DELETE: Strategy 5 - Not found")
                except Exception:
                    logger.info(f"🗑️ DATABASE DELETE: Strategy 5 - Error")
            
            # Strategy 6: Fallback to any user document
            if not document:
                try:
                    candidates = DocumentProcessing.objects.filter(
                        uploader_username=uploader_username
                    ).order_by('-created_at')
                    if candidates:
                        document = candidates.first()
                        strategy_used = "Strategy 6: Fallback to any user document"
                        logger.info(f"🗑️ DATABASE DELETE: {strategy_used} - Found")
                    else:
                        logger.info(f"🗑️ DATABASE DELETE: Strategy 6 - Not found")
                except Exception:
                    logger.info(f"🗑️ DATABASE DELETE: Strategy 6 - Error")
            
            if document:
                # Found document, delete it
                document_info = {
                    'id': str(document.id),
                    'uploader_username': document.uploader_username,
                    'source_file': document.source_file,
                    'filename': document.get_filename(),
                    'strategy_used': strategy_used
                }
                
                document.delete()
                logger.info(f"🗑️ DATABASE DELETE: Successfully deleted document: {document_info}")
                
                return {
                    'success': True,
                    'message': 'Document deleted successfully',
                    'details': document_info
                }
            else:
                logger.warning(f"🗑️ DATABASE DELETE: Document not found for user: {uploader_username}, file: {source_file}")
                return {
                    'success': False,
                    'message': 'Document not found in database',
                    'details': {
                        'uploader_username': uploader_username,
                        'source_file': source_file,
                        'strategies_tried': [
                            'Strategy 1: Exact match (username + source_file)',
                            'Strategy 2: Source file only',
                            'Strategy 3: MongoDB ObjectId lookup',
                            'Strategy 4: Filename search in file_data',
                            'Strategy 5: Regex partial matching',
                            'Strategy 6: Fallback to any user document'
                        ]
                    }
                }
                
        except Exception as e:
            logger.error(f"🗑️ DATABASE DELETE: Error deleting document: {str(e)}")
            return {
                'success': False,
                'message': f'Error deleting document: {str(e)}',
                'details': {
                    'uploader_username': uploader_username,
                    'source_file': source_file,
                    'error': str(e)
                }
            }
