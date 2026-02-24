import json
import logging
import time
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
import redis
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from .config import get_settings

logger = logging.getLogger(__name__)

class MemoryManager:
    """Manages short-term and long-term memory using Redis."""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        
    @classmethod
    def from_app_config(cls):
        """Create MemoryManager from Settings."""
        settings = get_settings()
        try:
            redis_client = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                password=settings.REDIS_PASSWORD,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            redis_client.ping()
            logger.info("Redis connection established successfully")
            return cls(redis_client)
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    # Short-term Memory Methods
    def save_short_term_memory(self, user_id: str, messages: List[BaseMessage]) -> bool:
        """Save recent conversation messages to short-term memory."""
        try:
            key = f"short_term:{user_id}"
            
            # Convert messages to serializable format
            messages_data = []
            settings = get_settings()
            for msg in messages[-settings.MAX_SHORT_TERM_MESSAGES:]:
                msg_dict = {
                    'type': msg.__class__.__name__,
                    'content': msg.content,
                    'timestamp': time.time()
                }
                if hasattr(msg, 'tool_calls') and msg.tool_calls:
                    msg_dict['tool_calls'] = [
                        {
                            'name': tc.get('name', ''),
                            'args': tc.get('args', {}),
                            'id': tc.get('id', '')
                        } for tc in msg.tool_calls
                    ]
                messages_data.append(msg_dict)
            
            # Save to Redis with TTL
            self.redis_client.setex(
                key,
                get_settings().SHORT_TERM_MEMORY_TTL,
                json.dumps(messages_data)
            )
            
            logger.info(f"Saved {len(messages_data)} messages to short-term memory for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving short-term memory for user {user_id}: {e}")
            return False
    
    def load_short_term_memory(self, user_id: str) -> List[BaseMessage]:
        """Load recent conversation messages from short-term memory."""
        try:
            key = f"short_term:{user_id}"
            data = self.redis_client.get(key)
            
            if not data:
                logger.info(f"No short-term memory found for user {user_id}")
                return []
            
            messages_data = json.loads(data)
            messages = []
            
            for msg_dict in messages_data:
                if msg_dict['type'] == 'HumanMessage':
                    messages.append(HumanMessage(content=msg_dict['content']))
                elif msg_dict['type'] == 'AIMessage':
                    ai_msg = AIMessage(content=msg_dict['content'])
                    if 'tool_calls' in msg_dict:
                        ai_msg.tool_calls = msg_dict['tool_calls']
                    messages.append(ai_msg)
            
            logger.info(f"Loaded {len(messages)} messages from short-term memory for user {user_id}")
            return messages
            
        except Exception as e:
            logger.error(f"Error loading short-term memory for user {user_id}: {e}")
            return []
    
    def clear_short_term_memory(self, user_id: str) -> bool:
        """Clear short-term memory for a user."""
        try:
            key = f"short_term:{user_id}"
            self.redis_client.delete(key)
            logger.info(f"Cleared short-term memory for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error clearing short-term memory for user {user_id}: {e}")
            return False
    
    def get_short_term_memory_ttl(self, user_id: str) -> int:
        """Get remaining TTL of short-term memory in seconds."""
        try:
            key = f"short_term:{user_id}"
            ttl = self.redis_client.ttl(key)
            return ttl if ttl > 0 else 0
        except Exception as e:
            logger.error(f"Error getting TTL for user {user_id}: {e}")
            return 0
    
    def auto_migrate_old_memory(self, user_id: str) -> bool:
        """Auto-migrate short-term memory to long-term if TTL > 2 hours."""
        try:
            # Check if short-term memory exists
            key = f"short_term:{user_id}"
            data = self.redis_client.get(key)
            
            if not data:
                return True  # No memory to migrate
            
            # Get remaining TTL
            ttl_remaining = self.get_short_term_memory_ttl(user_id)
            original_ttl = get_settings().SHORT_TERM_MEMORY_TTL
            memory_age = original_ttl - ttl_remaining
            
            # If memory is older than 2 hours (7200 seconds), migrate
            if memory_age > 7200:  # 2 hours
                logger.info(f"Auto-migrating old memory for user {user_id} (age: {memory_age}s)")
                
                # Load short-term messages
                messages = self.load_short_term_memory(user_id)
                
                if messages:
                    # Prepare messages for AI summarization
                    message_contents = []
                    for msg in messages:
                        if isinstance(msg, (HumanMessage, AIMessage)) and len(msg.content.strip()) > 15:
                            # Skip context messages and system messages
                            content = msg.content.strip()
                            if not content.startswith("Reference context:") and "Validation" not in content:
                                if len(content) > 150:
                                    content = content[:150] + "..."
                                message_contents.append(content)
                    
                    if message_contents and len(message_contents) >= 2:
                        try:
                            # Use AI summarization tool for better quality
                            from .tools import summarize_conversation
                            
                            # Get user preferences for context
                            user_preferences = self.get_user_preferences(user_id)
                            
                            # Call AI summarization
                            summary = summarize_conversation.invoke({
                                "messages": message_contents[-10:],  # Last 10 relevant messages
                                "user_preferences": user_preferences
                            })
                            
                            if summary and len(summary.strip()) > 20 and not summary.startswith("Lỗi"):
                                # Save AI-generated summary
                                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                conversation_id = f"auto_migrate_{timestamp}"
                                
                                success = self.save_conversation_summary(user_id, summary.strip(), conversation_id)
                                
                                if success:
                                    # Clear short-term memory after successful migration
                                    self.clear_short_term_memory(user_id)
                                    logger.info(f"Auto-migrated with AI summary for user {user_id}: {summary[:100]}...")
                                    return True
                                else:
                                    logger.warning(f"Failed to save AI summary for user {user_id}")
                                    # Fall back to simple summary
                                    raise Exception("Failed to save AI summary")
                            else:
                                logger.warning(f"Poor AI summary quality, falling back to simple summary")
                                raise Exception("Poor summary quality")
                                
                        except Exception as ai_error:
                            logger.warning(f"AI summarization failed for auto-migration: {ai_error}")
                            
                            # Fallback to simple summary
                            auto_summary = f"Auto-migrated conversation: {'; '.join(message_contents[-5:])}"
                            
                            # Save simple summary
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            conversation_id = f"auto_migrate_simple_{timestamp}"
                            
                            success = self.save_conversation_summary(user_id, auto_summary, conversation_id)
                            
                            if success:
                                # Clear short-term memory after successful migration
                                self.clear_short_term_memory(user_id)
                                logger.info(f"Auto-migrated with simple summary for user {user_id}")
                                return True
                            else:
                                logger.error(f"Failed to save even simple summary for user {user_id}")
                                return False
                    
                logger.info(f"No meaningful content to migrate for user {user_id}")
                return True
            
            logger.debug(f"Memory for user {user_id} is recent (age: {memory_age}s), no migration needed")
            return True
            
        except Exception as e:
            logger.error(f"Error in auto-migration for user {user_id}: {e}")
            return False
    
    # Long-term Memory Methods
    def save_long_term_memory(self, user_id: str, memory_type: str, data: Dict[str, Any]) -> bool:
        """Save data to long-term memory."""
        try:
            key = f"long_term:{user_id}:{memory_type}"
            
            # Add metadata
            memory_data = {
                'data': data,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat(),
                'access_count': 0
            }
            
            # Check if memory already exists to preserve access count
            existing_data = self.redis_client.get(key)
            if existing_data:
                existing_memory = json.loads(existing_data)
                memory_data['access_count'] = existing_memory.get('access_count', 0)
                memory_data['created_at'] = existing_memory.get('created_at', memory_data['created_at'])
            
            self.redis_client.setex(
                key,
                get_settings().LONG_TERM_MEMORY_TTL,
                json.dumps(memory_data)
            )
            
            logger.info(f"Saved long-term memory ({memory_type}) for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving long-term memory for user {user_id}: {e}")
            return False
    
    def load_long_term_memory(self, user_id: str, memory_type: str) -> Optional[Dict[str, Any]]:
        """Load data from long-term memory and increment access count."""
        try:
            key = f"long_term:{user_id}:{memory_type}"
            data = self.redis_client.get(key)
            
            if not data:
                logger.info(f"No long-term memory ({memory_type}) found for user {user_id}")
                return None
            
            memory_data = json.loads(data)
            
            # Increment access count
            memory_data['access_count'] += 1
            memory_data['last_accessed'] = datetime.now().isoformat()
            
            # Save updated memory back to Redis
            self.redis_client.setex(
                key,
                get_settings().LONG_TERM_MEMORY_TTL,
                json.dumps(memory_data)
            )
            
            logger.info(f"Loaded long-term memory ({memory_type}) for user {user_id}")
            return memory_data['data']
            
        except Exception as e:
            logger.error(f"Error loading long-term memory for user {user_id}: {e}")
            return None
    
    def get_all_long_term_memory_types(self, user_id: str) -> List[str]:
        """Get all available long-term memory types for a user."""
        try:
            pattern = f"long_term:{user_id}:*"
            keys = self.redis_client.keys(pattern)
            
            memory_types = []
            for key in keys:
                # Extract memory_type from key
                parts = key.split(':')
                if len(parts) >= 3:
                    memory_type = ':'.join(parts[2:])  # Handle memory types with colons
                    memory_types.append(memory_type)
            
            return memory_types
            
        except Exception as e:
            logger.error(f"Error getting long-term memory types for user {user_id}: {e}")
            return []
    
    def delete_long_term_memory(self, user_id: str, memory_type: str) -> bool:
        """Delete specific long-term memory."""
        try:
            key = f"long_term:{user_id}:{memory_type}"
            self.redis_client.delete(key)
            logger.info(f"Deleted long-term memory ({memory_type}) for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting long-term memory for user {user_id}: {e}")
            return False
    
    # Conversation Summary Methods
    def save_conversation_summary(self, user_id: str, summary: str, conversation_id: str = None) -> bool:
        """Save conversation summary to long-term memory."""
        summary_data = {
            'summary': summary,
            'conversation_id': conversation_id or f"conv_{int(time.time())}",
            'timestamp': datetime.now().isoformat()
        }
        
        # Get existing summaries
        existing_summaries = self.load_long_term_memory(user_id, 'conversation_summaries') or []
        existing_summaries.append(summary_data)
        
        # Keep only recent summaries (max 50)
        if len(existing_summaries) > 50:
            existing_summaries = existing_summaries[-50:]
        
        return self.save_long_term_memory(user_id, 'conversation_summaries', existing_summaries)
    
    def get_conversation_summaries(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent conversation summaries."""
        summaries = self.load_long_term_memory(user_id, 'conversation_summaries') or []
        return summaries[-limit:] if summaries else []
    
    # User Preferences Methods
    def save_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        """Save user preferences to long-term memory."""
        return self.save_long_term_memory(user_id, 'user_preferences', preferences)
    
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get user preferences from long-term memory."""
        return self.load_long_term_memory(user_id, 'user_preferences') or {}
    
    # Context Methods
    def save_user_context(self, user_id: str, context: str, context_type: str = 'general') -> bool:
        """Save important context information."""
        context_data = {
            'context': context,
            'type': context_type,
            'timestamp': datetime.now().isoformat()
        }
        return self.save_long_term_memory(user_id, f'context_{context_type}', context_data)
    
    def get_user_context(self, user_id: str, context_type: str = 'general') -> Optional[str]:
        """Get user context information."""
        context_data = self.load_long_term_memory(user_id, f'context_{context_type}')
        return context_data.get('context') if context_data else None
    
    # Health Check
    def health_check(self) -> Dict[str, Any]:
        """Check Redis connection and return status."""
        try:
            start_time = time.time()
            self.redis_client.ping()
            response_time = time.time() - start_time
            
            # Get Redis info
            info = self.redis_client.info()
            
            return {
                'status': 'healthy',
                'response_time_ms': round(response_time * 1000, 2),
                'redis_version': info.get('redis_version', 'unknown'),
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_human': info.get('used_memory_human', 'unknown')
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            } 