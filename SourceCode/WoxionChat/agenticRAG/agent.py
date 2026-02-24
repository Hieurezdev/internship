import logging
import operator
from typing import TypedDict, Annotated, Sequence, Optional, Union
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from .models import ModelRegistry
from .tools import (
    summarize_conversation, 
    find_document_from_user, 
    find_document_from_admin, 
    find_documents_parallel,
    rerank_documents, 
    classify_query_type, 
    direct_response
)
from .prompts import LANGGRAPH_AGENT_PROMPT_SYSTEM
from .memory import MemoryManager
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# Configure logging
logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    """Represents the state of our agent."""
    input: str
    context: Optional[str]
    user_context: Optional[str]
    messages: Annotated[Sequence[BaseMessage], operator.add]

    user_id: str
    message_count: int
    summarize_text: Optional[str]
    need_summarize: bool
    agent_output_message: Optional[BaseMessage]
    
    # Memory-related fields
    memory_manager: Optional[MemoryManager]
    short_term_memory: Optional[Sequence[BaseMessage]]
    user_preferences: Optional[dict]
    conversation_summaries: Optional[list]
    
    # Query classification fields
    needs_retrieval: Optional[bool]
    query_type: Optional[str]
    confidence: Optional[float]


def create_agent_graph(models: Union[ModelRegistry, BaseChatModel], tools):
    """
    Creates and compiles the LangGraph agent.

    Parameters
    ----------
    models : ModelRegistry | BaseChatModel
        Either a ModelRegistry (multimodel) or a single LLM for backward
        compatibility.  When a ModelRegistry is provided:
          - ``models.gemini``  is used for RAG answering + tool-calls
          - ``models.local``   is used for direct (no-retrieval) responses
    tools  : list
        LangChain tools to bind to the Gemini LLM.
    """
    # ── Resolve LLMs ─────────────────────────────────────────────────────────
    if isinstance(models, ModelRegistry):
        gemini_llm = models.gemini
        local_llm  = models.local
        logger.info("AgenticRAG running in MULTIMODEL mode (Gemini + Local).")
    else:
        # Backward-compatible: single LLM passed directly
        gemini_llm = models
        local_llm  = models
        logger.info("AgenticRAG running in SINGLE-MODEL mode.")

    llm_with_tools = gemini_llm.bind_tools(tools)

    def memory_initialization_node(state: AgentState):
        """Initialize memory manager and load user's memory."""
        logger.info("--- Running Node: memory_initialization_node ---")
        try:
            memory_manager = MemoryManager.from_app_config()
            
            
            migration_success = memory_manager.auto_migrate_old_memory(state['user_id'])
            if migration_success:
                logger.info(f"Auto-migration check completed for user {state['user_id']}")
            else:
                logger.warning(f"Auto-migration failed for user {state['user_id']}")
            
            # Load short-term memory (recent conversation)
            short_term_memory = memory_manager.load_short_term_memory(state['user_id'])
            
            # Load user preferences
            user_preferences = memory_manager.get_user_preferences(state['user_id'])
            
            # Load more conversation summaries for better context
            conversation_summaries = memory_manager.get_conversation_summaries(state['user_id'], limit=10)
            
            return {
                "memory_manager": memory_manager,
                "short_term_memory": short_term_memory,
                "user_preferences": user_preferences,
                "conversation_summaries": conversation_summaries
            }
        except Exception as e:
            logger.error(f"Failed to initialize memory manager: {e}")
            return {
                "memory_manager": None,
                "short_term_memory": [],
                "user_preferences": {},
                "conversation_summaries": []
            }

    def retrieve_context_parallel_node(state: AgentState):
        """Retrieve both user and admin context in parallel for better performance."""
        logger.info("--- Running Node: retrieve_context_parallel_node ---")
        logger.info(f"Using user_id '{state['user_id']}' for parallel context retrieval")
        
        start_time = time.time()
        
        # Use the new parallel tool for document retrieval
        try:
            parallel_results = find_documents_parallel.invoke({
                "search_query": state['input'], 
                "uploader_username": state['user_id']
            })
            
            user_context = parallel_results.get("user_documents", [])
            admin_context = parallel_results.get("admin_documents", [])
            
            logger.info(f"Parallel retrieval found {len(user_context)} user docs and {len(admin_context)} admin docs")
            
            # Rerank both document sets in parallel
            def rerank_user_docs():
                return rerank_documents.invoke({
                    "user_question": state['input'], 
                    "documents": user_context
                })
            
            def rerank_admin_docs():
                return rerank_documents.invoke({
                    "user_question": state['input'], 
                    "documents": admin_context
                })
            
            # Parallel reranking
            with ThreadPoolExecutor(max_workers=2) as executor:
                user_future = executor.submit(rerank_user_docs)
                admin_future = executor.submit(rerank_admin_docs)
                
                reranked_user_context = user_future.result()
                reranked_admin_context = admin_future.result()
            
            def build_context_string(
                reranked_documents: list[dict],
                score_threshold: float = 0.5,
                top_k: int = 10
            ) -> str:
                filtered_docs = [
                    doc for doc in reranked_documents
                    if doc.get('new_score', 0) >= score_threshold
                ]

                top_docs = filtered_docs[:top_k]
                if not top_docs:
                    return ""
                    
                context_parts = []
                for i, doc in enumerate(top_docs):
                    content = doc.get('content', 'N/A')
                    score = doc.get('new_score', 'N/A')
                    context_part = f"--- Tài liệu {i+1} (Điểm: {score:.2f}) ---\n{content}"
                    context_parts.append(context_part)

                return "\n\n".join(context_parts)

            # Build context strings
            user_context_string = build_context_string(reranked_user_context)
            admin_context_string = build_context_string(reranked_admin_context)
            
            # Simple memory context building
            memory_context = ""
            
            # Add user preferences if available
            if state.get('user_preferences'):
                prefs = state['user_preferences']
                memory_context += f"\nUser preferences: {prefs}"
            
            # Add conversation summaries
            if state.get('conversation_summaries'):
                summaries = [s.get('summary', '') for s in state['conversation_summaries'][-3:]]
                if summaries:
                    memory_context += f"\nPrevious conversations: {'; '.join(summaries)}"
            
            # Combine all context
            user_id_info = f"--- USER IDENTIFICATION ---\nUser ID: {state['user_id']}\nDocuments automatically retrieved for this user.\n"
            
            combined_context = user_id_info
            
            # Add user context
            if user_context_string:
                combined_context += f"\n=== TÀI LIỆU NGƯỜI DÙNG, USER, CÁ NHÂN ===\n{user_context_string}"
            else:
                combined_context += f"\n=== TÀI LIỆU NGƯỜI DÙNG, USER, CÁ NHÂN ===\nNo user documents found for this query, but user is already identified."
            
            # Add admin context 
            if admin_context_string:
                combined_context += f"\n\n=== TÀI LIỆU ADMIN, QUAN TRỊ, THÔNG TIN CHUNG ===\n{admin_context_string}"
            else:
                combined_context += f"\n\n=== TÀI LIỆU ADMIN, QUAN TRỊ, THÔNG TIN CHUNG ===\nNo admin documents found for this query."
            
            # Add memory context
            if memory_context:
                combined_context += f"\n\n--- MEMORY CONTEXT ---{memory_context}"
            
            # Always remind about user identification
            combined_context += f"\n\n--- SYSTEM REMINDER ---\nUser is already identified with ID: {state['user_id']}. Do not ask for name or identification."
            
            total_time = time.time() - start_time
            logger.info(f"Parallel context retrieval completed in {total_time:.3f}s")
            
            return {
                "context": combined_context,
                "user_context": user_context_string if user_context_string else "No user documents found"
            }
            
        except Exception as e:
            logger.error(f"Error in parallel context retrieval: {e}", exc_info=True)
            return {
                "context": f"Error retrieving context for user {state['user_id']}",
                "user_context": "Error retrieving user context"
            }

    def retrieve_user_context_node(state: AgentState):
        """Retrieve context with basic memory integration."""
        logger.info("--- Running Node: retrieve_user_context_node ---")
        logger.info(f"Using user_id '{state['user_id']}' as uploader_username for user document search")
        
        # Get basic context - fix function call with proper parameters
        user_context = find_document_from_user.invoke({"search_query": state['input'], "uploader_username": state['user_id']})
        
        reranked_user_context = rerank_documents.invoke({"user_question": state['input'], "documents": user_context})    
        def build_context_string(
            reranked_documents: list[dict],
            score_threshold: float = 0.5,
            top_k: int = 10
        ) -> str:
        
        
            filtered_docs = [
                doc for doc in reranked_documents
                if doc.get('new_score', 0) >= score_threshold
            ]

            top_docs = filtered_docs[:top_k]
            if not top_docs:
                return ""
            context_parts = []
            for i, doc in enumerate(top_docs):
                content = doc.get('content', 'N/A')
                score = doc.get('new_score', 'N/A')
                context_part = f"--- Tài liệu người dùng {i+1} (Điểm: {score:.2f}) ---\n{content}"
                context_parts.append(context_part)

            return "\n\n".join(context_parts)

        user_context_string = build_context_string(reranked_user_context)
        logger.info(f"Found {len(reranked_user_context)} user documents for user_id '{state['user_id']}'")
        
        # Simple memory context building
        memory_context = ""
        
        # Add user preferences if available (simplified)
        if state.get('user_preferences'):
            prefs = state['user_preferences']
            memory_context += f"\nUser preferences: {prefs}"
        
        # Add conversation summaries (simplified)
        if state.get('conversation_summaries'):
            summaries = [s.get('summary', '') for s in state['conversation_summaries'][-3:]]
            if summaries:
                memory_context += f"\nPrevious conversations: {'; '.join(summaries)}"
        
        # Store user context separately - Always include user_id info
        user_id_info = f"--- USER IDENTIFICATION ---\nUser ID: {state['user_id']}\nDocuments automatically retrieved for this user.\n"
        
        full_user_context = user_id_info
        if user_context_string:
            full_user_context += f"\n--- USER DOCUMENTS ---\n{user_context_string}"
        else:
            full_user_context += f"\n--- USER DOCUMENTS ---\nNo user documents found for this query, but user is already identified."
            
        if memory_context:
            full_user_context += f"\n\n--- MEMORY CONTEXT ---{memory_context}"
        
        return {"user_context": full_user_context}

    def retrieve_admin_context_node(state: AgentState):
        """Retrieve admin context with basic memory integration."""
        logger.info("--- Running Node: retrieve_admin_context_node ---")
        logger.info(f"Using user_id '{state['user_id']}' as uploader_username for admin document search")
        
        # Get basic context - fix function call with proper parameters
        admin_context = find_document_from_admin.invoke({"search_query": state['input'], "uploader_username": state['user_id']})
        
        reranked_admin_context = rerank_documents.invoke({"user_question": state['input'], "documents": admin_context})    
        def build_context_string(
            reranked_documents: list[dict],
            score_threshold: float = 0.5,
            top_k: int = 5
        ) -> str:
        
        
            filtered_docs = [
                doc for doc in reranked_documents
                if doc.get('new_score', 0) >= score_threshold
            ]

            top_docs = filtered_docs[:top_k]
            if not top_docs:
                return ""
            context_parts = []
            for i, doc in enumerate(top_docs):
                content = doc.get('content', 'N/A')
                score = doc.get('new_score', 'N/A')
                context_part = f"--- Tài liệu quản trị {i+1} (Điểm: {score:.2f}) ---\n{content}"
                context_parts.append(context_part)

            return "\n\n".join(context_parts)

        admin_context_string = build_context_string(reranked_admin_context)
        logger.info(f"Found {len(reranked_admin_context)} admin documents for user_id '{state['user_id']}'")
        
        # Combine user context and admin context
        combined_context = ""
        
        # Add user context if available
        if state.get('user_context'):
            combined_context += f"=== TÀI LIỆU NGƯỜI DÙNG, USER, CÁ NHÂN ===\n{state['user_context']}\n\n"
        
        # Add admin context
        if admin_context_string: 
            combined_context += f"=== TÀI LIỆU ADMIN, QUAN TRỊ, THÔNG TIN CHUNG ===\n{admin_context_string}"
        else:
            combined_context += f"=== TÀI LIỆU ADMIN, QUAN TRỊ, THÔNG TIN CHUNG ===\nNo admin documents found for this query."
            
        # Always remind about user identification
        combined_context += f"\n\n--- SYSTEM REMINDER ---\nUser is already identified with ID: {state['user_id']}. Do not ask for name or identification."
        
        return {"context": combined_context}

    
    def agent_node(state: AgentState):
        """Agent node with simplified processing - no validation needed."""
        logger.info("--- Running Node: agent_node ---")
        logger.info(f"Processing query for user_id: {state['user_id']}")
        
        # Combine current messages with short-term memory
        messages = list(state['messages'])
        
        # Add short-term memory for context
        if state.get('short_term_memory'):
            recent_memory = list(state['short_term_memory'])[-5:]  
            messages = recent_memory + messages
        
        # Add combined context message with clear user identification
        context_content = f"""IMPORTANT: User is already identified with ID: {state['user_id']}
DO NOT ask for name, username, or any identification information.

Reference context:
```
{state.get('context', 'No context available')}
```"""
        
        context_message = HumanMessage(content=context_content)
        
        if len(messages) > 1:
             messages.insert(-1, context_message)
        else:
             messages.append(context_message)
        
        # Simple system prompt with user ID emphasis
        system_prompt = f"""User ID: {state['user_id']} - User is already identified. Do not ask for identification.

{LANGGRAPH_AGENT_PROMPT_SYSTEM}"""
        
        # Add basic user preferences if available
        if state.get('user_preferences'):
            prefs = state['user_preferences']
            system_prompt += f"\n\nUser preferences: {prefs}"
        
        # Add conversation context if available
        if state.get('conversation_summaries'):
            latest_summaries = state['conversation_summaries'][-2:]  # Last 2 summaries
            if latest_summaries:
                summary_text = "; ".join([s.get('summary', '') for s in latest_summaries])
                system_prompt += f"\n\nPrevious conversations: {summary_text}"
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="messages"),
        ])
        agent_chain = prompt | llm_with_tools
        
        try:
            logger.info(f"[Gemini] Calling LLM with user_id {state['user_id']} clearly specified")
            agent_outcome_message = agent_chain.invoke({"messages": messages})
        except Exception as e:
            logger.error(f"[Gemini] LLM invocation failed: {e}", exc_info=True)
            agent_outcome_message = AIMessage(content=f"Error calling LLM: {e}")

        return {"messages": [agent_outcome_message]}

    def memory_save_node(state: AgentState):
        """Save current conversation to memory with improved summarization."""
        logger.info("--- Running Node: memory_save_node ---")
        
        if not state.get('memory_manager') or not state['user_id']:
            logger.warning("Memory manager or user_id not available for saving")
            return {}
        
        try:
            memory_manager = state['memory_manager']
            
            # Combine all messages for saving
            all_messages = []
            if state.get('short_term_memory'):
                all_messages.extend(state['short_term_memory'])
            all_messages.extend(state['messages'])
            
            # Save short-term memory
            success = memory_manager.save_short_term_memory(state['user_id'], all_messages)
            
            if success:
                logger.info(f"Successfully saved conversation to memory for user {state['user_id']}")
            else:
                logger.warning(f"Failed to save conversation to memory for user {state['user_id']}")
                
            # Create conversation summary earlier for better memory
            total_messages = len(all_messages)
            if total_messages > 15:  
                try:
                    logger.info("Creating intelligent conversation summary using Gemini...")
                    
                    # Prepare messages for summarization
                    message_contents = []
                    for msg in all_messages[-12:]:  # Focus on last 12 messages for relevance
                        if isinstance(msg, (HumanMessage, AIMessage)) and len(msg.content.strip()) > 15:
                            # Skip context messages and system messages
                            if not msg.content.startswith("Reference context:") and "Validation" not in msg.content:
                                # Clean up the content
                                content = msg.content.strip()
                                if len(content) > 200:
                                    content = content[:200] + "..."
                                message_contents.append(content)
                    
                    if len(message_contents) >= 3:  
                        # Use the summarize_conversation tool with better context
                        user_prefs = state.get('user_preferences', {})
                        
                        # Enhanced summarization call
                        summary = summarize_conversation.invoke({
                            "messages": message_contents[-8:],
                            "user_preferences": user_prefs
                        })
                        
                        if summary and not summary.startswith("Lỗi") and len(summary.strip()) > 10:
                            memory_manager.save_conversation_summary(state['user_id'], summary.strip())
                            logger.info(f"Saved AI-generated conversation summary for user {state['user_id']}: {summary[:100]}...")
                        else:
                            logger.warning(f"Failed to generate summary or received poor quality: {summary}")
                            raise Exception("Poor quality summary")
                
                except Exception as e:
                    logger.error(f"Failed to create AI conversation summary: {e}")
             
                    
            
        except Exception as e:
            logger.error(f"Error in memory_save_node: {e}")
        
        return {}

    # Tool node for summarization only
    knowledge_tool_node = ToolNode(tools)

    def decide_next_step(state: AgentState):
        """Decide if we need to use tools or save to memory."""
        last_message = state['messages'][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "take_action"
        return "save_memory"

    # Build simplified workflow
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("memory_init", memory_initialization_node)
    
    # Wrap classify_query_type to handle state properly
    def classify_query_node(state: AgentState):
        """Wrapper to properly extract user query from state."""
        try:
            logger.info(f"--- Running Node: classify_query_node ---")
            logger.info(f"Input query: '{state['input']}'")
            
            result = classify_query_type.invoke({
                "user_query": state["input"]
            })
            
            logger.info(f"Classification result: needs_retrieval={result.get('needs_retrieval')}, query_type={result.get('query_type')}, confidence={result.get('confidence')}")
            
            # Merge classification result with state
            return result
        except Exception as e:
            logger.error(f"Error in classify_query_node: {e}")
            return {
                "needs_retrieval": True,
                "query_type": "knowledge_query",
                "confidence": 0.5
            }
    
    workflow.add_node("classify_query", classify_query_node)
    workflow.add_node("retrieve_context_parallel", retrieve_context_parallel_node)
    workflow.add_node("retrieve_user_context", retrieve_user_context_node)
    workflow.add_node("retrieve_admin_context", retrieve_admin_context_node)
    workflow.add_node("agent", agent_node)
    
    # Wrap direct_response to handle state properly
    def direct_response_node(state: AgentState):
        """Use the local model for lightweight, no-retrieval responses."""
        try:
            query_type = state.get("query_type", "general_chat")
            logger.info(f"--- Running Node: direct_response_node ---")
            logger.info(f"Query: '{state['input']}'")
            logger.info(f"Query type: {query_type}")
            logger.info("✅ NO DATABASE QUERY - Using local model for direct response")

            # First try the local model directly
            try:
                prompt = ChatPromptTemplate.from_messages([
                    ("system", LANGGRAPH_AGENT_PROMPT_SYSTEM),
                    ("human", "{query}"),
                ])
                chain = prompt | local_llm
                result_msg = chain.invoke({"query": state["input"]})
                result = result_msg.content.strip()
                logger.info(f"[Local] Direct response generated: {result[:100]}...")
            except Exception as local_err:
                logger.warning(f"[Local] model failed ({local_err}), falling back to Gemini tool")
                # Fallback to the existing direct_response tool (uses Gemini internally)
                result = direct_response.invoke({
                    "user_query": state["input"],
                    "query_type": query_type,
                })

            return {"messages": [AIMessage(content=result)]}
        except Exception as e:
            logger.error(f"Error in direct_response_node: {e}")
            return {"messages": [AIMessage(content="Xin lỗi, tôi không hiểu câu hỏi của bạn. / Sorry, I don't understand your question.")]}
    
    workflow.add_node("direct_response", direct_response_node)
    workflow.add_node("action_node", knowledge_tool_node)
    workflow.add_node("memory_save", memory_save_node)

    # Set entry point
    workflow.set_entry_point("memory_init")
    
    # Add basic edges
    workflow.add_edge("memory_init", "classify_query")

    # Define conditional routing function
    def route_after_classification(state: AgentState):
        """Route based on query classification."""
        needs_retrieval = state.get("needs_retrieval", True)
        query_type = state.get("query_type", "knowledge_query")
        confidence = state.get("confidence", 0.5)
        
        logger.info(f"--- Routing Decision ---")
        logger.info(f"Query: '{state['input']}'")
        logger.info(f"needs_retrieval: {needs_retrieval}")
        logger.info(f"query_type: {query_type}")
        logger.info(f"confidence: {confidence}")
        
        if needs_retrieval:
            logger.info("→ Routing to retrieve_context_parallel (will query database)")
            return "retrieve_context_parallel"
        else:
            logger.info("→ Routing to direct_response (NO database query)")
            return "direct_response"
    
    workflow.add_conditional_edges(
        "classify_query",
        route_after_classification,
        {
            "retrieve_context_parallel": "retrieve_context_parallel",
            "direct_response": "direct_response"
        }
    )
    
    # Parallel retrieval path
    workflow.add_edge("retrieve_context_parallel", "agent")
    
    # Traditional path (fallback)
    workflow.add_edge("retrieve_user_context", "retrieve_admin_context")
    workflow.add_edge("retrieve_admin_context", "agent")
    workflow.add_edge("action_node", "agent")
    
    # Both paths converge to memory save
    workflow.add_edge("direct_response", "memory_save")
    workflow.add_edge("agent", "memory_save")
    workflow.add_edge("memory_save", END)

    return workflow.compile() 