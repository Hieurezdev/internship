from accounts.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
import os
from asgiref.sync import async_to_sync  # 1. Import async_to_sync
from .services import create_chunks_from_markdown
from .models import AdminDocumentChunking, UserDocumentChunking

def connect_to_mongodb(mongo_url=os.environ.get('MONGODB_ATLAS_URI')):
    if not mongo_url:
        raise ValueError("Biến môi trường MONGODB_ATLAS_URI chưa được thiết lập.")
    mongo_client = MongoClient(mongo_url)
    db = mongo_client['local-bot']
    return db

class SemanticChunkingAPIView(APIView):
    # Đưa hàm gọi service ra riêng để dễ đọc
    @async_to_sync
    async def call_chunking_service(self, markdown, source_file):
        return await create_chunks_from_markdown(markdown_text=markdown, source_file=source_file)

    def get(self, request):
        """Check chunking status for documents"""
        uploader_username = request.query_params.get('uploader_username')
        source_file = request.query_params.get('source_file')
        
        # If checking single document
        if uploader_username and source_file:
            try:
                user = User.objects.get(username=uploader_username)
                
                # Select the appropriate model based on user role
                if user.role == 'admin':
                    model_to_use = AdminDocumentChunking
                else:
                    model_to_use = UserDocumentChunking
                
                # Check if chunks exist
                chunk_count = model_to_use.objects.filter(
                    uploader_username=uploader_username,
                    source_file=source_file
                ).count()
                
                return Response({
                    "chunked": chunk_count > 0,
                    "chunk_count": chunk_count,
                    "uploader_username": uploader_username,
                    "source_file": source_file
                }, status=status.HTTP_200_OK)
                
            except User.DoesNotExist:
                return Response(
                    {"message": f"Người dùng '{uploader_username}' không tồn tại."},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        # If checking multiple documents for a user
        elif uploader_username:
            try:
                user = User.objects.get(username=uploader_username)
                
                # Select the appropriate model based on user role
                if user.role == 'admin':
                    model_to_use = AdminDocumentChunking
                else:
                    model_to_use = UserDocumentChunking
                
                # Get all chunks for this user
                chunks = model_to_use.objects.filter(uploader_username=uploader_username)
                
                # Group by source_file
                chunked_files = {}
                for chunk in chunks:
                    source_file = chunk.source_file
                    if source_file not in chunked_files:
                        chunked_files[source_file] = 0
                    chunked_files[source_file] += 1
                
                return Response({
                    "chunked_files": chunked_files,
                    "total_files": len(chunked_files),
                    "uploader_username": uploader_username
                }, status=status.HTTP_200_OK)
                
            except User.DoesNotExist:
                return Response(
                    {"message": f"Người dùng '{uploader_username}' không tồn tại."},
                    status=status.HTTP_404_NOT_FOUND
                )
        
        else:
            return Response(
                {"message": "Vui lòng cung cấp 'uploader_username' để kiểm tra trạng thái chunking."},
                status=status.HTTP_400_BAD_REQUEST
            )

    def post(self, request):
        uploader_username = request.data.get('uploader_username')
        source_file = request.data.get('source_file')

        if not uploader_username or not source_file:
            return Response(
                {"message": "Vui lòng cung cấp đủ 'uploader_username' và 'source_file'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Xử lý lỗi không tìm thấy User
        try:
            user = User.objects.get(username=uploader_username)
        except User.DoesNotExist:
            return Response(
                {"message": f"Người dùng '{uploader_username}' không tồn tại."},
                status=status.HTTP_404_NOT_FOUND
            )

        try:
            # Lấy markdown text từ MongoDB
            db = connect_to_mongodb()
            source_collection_name = user.role + "_database"  
            
            # Debug info: Show collection name being used
            # print(f"🔍 DEBUG: Using collection: {source_collection_name}")
            # print(f"🔍 DEBUG: User role: {user.role}")
            # print(f"🔍 DEBUG: Searching for user: {uploader_username}, file: {source_file}")
            
            # Try multiple search strategies
            document = None
            
            # Strategy 1: Search by both uploader_username and source_file (exact match)
            document = db[source_collection_name].find_one({
                "uploader_username": uploader_username, 
                "source_file": source_file
            })
            # print(f"🔍 DEBUG: Strategy 1 result: {'Found' if document else 'Not found'}")
            
            # Strategy 2: Search by source_file only (in case uploader_username doesn't match exactly)
            if not document:
                document = db[source_collection_name].find_one({"source_file": source_file})
                # print(f"🔍 DEBUG: Strategy 2 result: {'Found' if document else 'Not found'}")
                
            # Strategy 3: Search by ObjectId if source_file looks like a MongoDB ObjectId
            if not document and len(source_file) == 24:
                from bson import ObjectId
                try:
                    document = db[source_collection_name].find_one({"_id": ObjectId(source_file)})
                    # print(f"🔍 DEBUG: Strategy 3 (ObjectId) result: {'Found' if document else 'Not found'}")
                except Exception as e:
                    # print(f"🔍 DEBUG: Strategy 3 (ObjectId) error: {e}")
                    pass
                    
            # Strategy 4: Search by filename in file_data
            if not document:
                document = db[source_collection_name].find_one({"file_data.filename": source_file})
                # print(f"🔍 DEBUG: Strategy 4 result: {'Found' if document else 'Not found'}")
                
            # Strategy 5: Search by partial match on source_file with regex
            if not document:
                try:
                    document = db[source_collection_name].find_one({
                        "$or": [
                            {"source_file": {"$regex": source_file.replace("(", "\\(").replace(")", "\\)"), "$options": "i"}},
                            {"file_data.filename": {"$regex": source_file.replace("(", "\\(").replace(")", "\\)"), "$options": "i"}}
                        ]
                    })
                    # print(f"🔍 DEBUG: Strategy 5 result: {'Found' if document else 'Not found'}")
                except Exception as e:
                    # print(f"🔍 DEBUG: Strategy 5 error: {e}")
                    pass

            # Strategy 6: Find any document for this user (fallback)
            if not document:
                document = db[source_collection_name].find_one({"uploader_username": uploader_username})
                # print(f"🔍 DEBUG: Strategy 6 (any user doc) result: {'Found' if document else 'Not found'}")

            # If still not found, provide detailed debug info
            if not document:
                # Get available documents for debugging
                available_docs = list(db[source_collection_name].find({}, {"source_file": 1, "file_data.filename": 1, "uploader_username": 1, "_id": 1}).limit(10))
                # print(f"🔍 DEBUG: Found {len(available_docs)} documents in collection")
                
                available_info = []
                for i, doc in enumerate(available_docs):
                    info = f"{i+1}. User: {doc.get('uploader_username', 'N/A')}, "
                    info += f"Source: {doc.get('source_file', 'N/A')}, "
                    info += f"Filename: {doc.get('file_data', {}).get('filename', 'N/A')}, "
                    info += f"ID: {str(doc.get('_id', 'N/A'))}"
                    available_info.append(info)
                
                debug_info = "\n".join(available_info) if available_info else "No documents found in collection"
                
                # Also check if user_database collection exists (legacy format)
                try:
                    legacy_docs = list(db["user_database"].find({}, {"source_file": 1, "file_data.filename": 1, "uploader_username": 1, "_id": 1}).limit(5))
                    if legacy_docs:
                        debug_info += f"\n\n--- Legacy user_database collection ({len(legacy_docs)} docs) ---\n"
                        for i, doc in enumerate(legacy_docs):
                            info = f"{i+1}. User: {doc.get('uploader_username', 'N/A')}, "
                            info += f"Source: {doc.get('source_file', 'N/A')}, "
                            info += f"Filename: {doc.get('file_data', {}).get('filename', 'N/A')}, "
                            info += f"ID: {str(doc.get('_id', 'N/A'))}"
                            debug_info += info + "\n"
                except Exception as e:
                    debug_info += f"\n\n--- Legacy collection check failed: {str(e)} ---"
                
                # Check if user has any documents in other collections
                user_doc_count = db[source_collection_name].count_documents({"uploader_username": uploader_username})
                debug_info += f"\n\n--- User '{uploader_username}' has {user_doc_count} documents in {source_collection_name} ---"
                
                return Response(
                    {
                        "message": f"Không tìm thấy tài liệu '{source_file}' cho người dùng '{uploader_username}'.",
                        "debug_info": f"Collection used: {source_collection_name}\nUser role: {user.role}\nSearch term: {source_file}\n\nAvailable documents:\n{debug_info}",
                        "search_strategies_tried": [
                            "uploader_username + source_file",
                            "source_file only", 
                            "MongoDB ObjectId",
                            "file_data.filename",
                            "regex partial match",
                            "any document for user"
                        ],
                        "suggestion": "Try using the exact document ID (hash) shown in the frontend instead of filename"
                    },
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Sửa lỗi chính tả và xử lý nếu key không tồn tại
            markdown_text = document.get("raw_markdown") # Sửa thành 'raw_markdown'
            if not markdown_text:
                 return Response(
                    {"message": f"Tài liệu '{source_file}' không có nội dung 'raw_markdown' để xử lý."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # 1. Gọi service một cách an toàn
            processed_chunks = self.call_chunking_service(markdown_text, source_file)

            if not processed_chunks:
                return Response({"message": "Xử lý thành công nhưng không có chunk nào được tạo."}, status=status.HTTP_200_OK)

            # 3. Sử dụng bulk_create để tối ưu hiệu năng
            if user.role == 'admin':
                model_to_use = AdminDocumentChunking
            else:
                model_to_use = UserDocumentChunking
            
            # Tạo một danh sách các object để chuẩn bị cho bulk_create
            chunks_to_create = [
                model_to_use(
                    source_file=source_file,
                    content=chunk.get("content"),
                    uploader_username=uploader_username,
                    embedding=chunk.get("embedding"),
                ) for chunk in processed_chunks
            ]

            model_to_use.objects.filter(uploader_username=uploader_username, source_file=source_file).delete()
            for chunk_object in chunks_to_create:
                chunk_object.save()
            
            return Response(
                {"message": f"Tài liệu đã được chunking và lưu thành công {len(chunks_to_create)} chunks."},
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response(
                {"message": f"Service xử lý tài liệu đã báo lỗi: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            # Các lỗi không lường trước khác
            return Response(
                {"message": f"Đã xảy ra lỗi hệ thống không mong muốn: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def delete(self, request):
        """
        Delete document chunking data ONLY.
        
        ⚠️ IMPORTANT: This method only deletes chunks and chunking data.
        The original document in user_database collection should remain intact
        so users can re-chunk the document later if needed.
        
        Document deletion should be handled by the accounts/user_database_service.py
        """
        uploader_username = request.query_params.get('uploader_username')
        source_file = request.query_params.get('source_file')

        if not uploader_username or not source_file:
            return Response(
                {"message": "Vui lòng cung cấp đủ 'uploader_username' và 'source_file'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get user to determine which model to use
            user = User.objects.get(username=uploader_username)
            
            # First, find the actual document in MongoDB to get the correct source_file
            db = connect_to_mongodb()
            source_collection_name = user.role + "_database"
            
            # print(f"🗑️ DELETE DEBUG: Using collection: {source_collection_name}")
            # print(f"🗑️ DELETE DEBUG: User role: {user.role}")
            # print(f"🗑️ DELETE DEBUG: Searching for user: {uploader_username}, file: {source_file}")
            
            # Use the same search strategies as POST method
            document = None
            actual_source_file = source_file  # Default to provided source_file
            
            # Strategy 1: Search by both uploader_username and source_file (exact match)
            document = db[source_collection_name].find_one({
                "uploader_username": uploader_username, 
                "source_file": source_file
            })
            # print(f"🗑️ DELETE DEBUG: Strategy 1 result: {'Found' if document else 'Not found'}")
            
            # Strategy 2: Search by source_file only
            if not document:
                document = db[source_collection_name].find_one({"source_file": source_file})
                # print(f"🗑️ DELETE DEBUG: Strategy 2 result: {'Found' if document else 'Not found'}")
                
            # Strategy 3: Search by ObjectId if source_file looks like a MongoDB ObjectId
            if not document and len(source_file) == 24:
                from bson import ObjectId
                try:
                    document = db[source_collection_name].find_one({"_id": ObjectId(source_file)})
                    # print(f"🗑️ DELETE DEBUG: Strategy 3 (ObjectId) result: {'Found' if document else 'Not found'}")
                except Exception as e:
                    # print(f"🗑️ DELETE DEBUG: Strategy 3 (ObjectId) error: {e}")
                    pass
                    
            # Strategy 4: Search by filename in file_data
            if not document:
                document = db[source_collection_name].find_one({"file_data.filename": source_file})
                # print(f"🗑️ DELETE DEBUG: Strategy 4 result: {'Found' if document else 'Not found'}")
                
            # Strategy 5: Search by partial match on source_file with regex
            if not document:
                try:
                    document = db[source_collection_name].find_one({
                        "$or": [
                            {"source_file": {"$regex": source_file.replace("(", "\\(").replace(")", "\\)"), "$options": "i"}},
                            {"file_data.filename": {"$regex": source_file.replace("(", "\\(").replace(")", "\\)"), "$options": "i"}}
                        ]
                    })
                    # print(f"🗑️ DELETE DEBUG: Strategy 5 result: {'Found' if document else 'Not found'}")
                except Exception as e:
                    # print(f"🗑️ DELETE DEBUG: Strategy 5 error: {e}")
                    pass

            # If document found, get the actual source_file from the document
            if document:
                actual_source_file = document.get("source_file", source_file)
                # print(f"🗑️ DELETE DEBUG: Found document with source_file: {actual_source_file}")
                
                # DON'T delete the document from MongoDB - chunking system should only delete chunks
                # The original document should remain in user_database collection
                # print(f"🗑️ DELETE DEBUG: Original document found but preserved in MongoDB")
            else:
                # print(f"🗑️ DELETE DEBUG: Document not found in MongoDB, proceeding with chunking deletion only")
                pass
            
            # Select the appropriate model based on user role
            if user.role == 'admin':
                model_to_use = AdminDocumentChunking
            else:
                model_to_use = UserDocumentChunking
            
            # Delete all chunks using the actual source_file
            chunks_deleted = model_to_use.objects.filter(
                uploader_username=uploader_username,
                source_file=actual_source_file
            ).delete()
            
            # print(f"🗑️ DELETE DEBUG: Chunks deleted: {chunks_deleted}")
            
            # Also try to delete chunks with the original search term if different
            if actual_source_file != source_file:
                additional_chunks_deleted = model_to_use.objects.filter(
                    uploader_username=uploader_username,
                    source_file=source_file
                ).delete()
                # print(f"🗑️ DELETE DEBUG: Additional chunks deleted: {additional_chunks_deleted}")
                chunks_deleted = (chunks_deleted[0] + additional_chunks_deleted[0], chunks_deleted[1])
            
            total_chunks_deleted = chunks_deleted[0] if isinstance(chunks_deleted, tuple) else chunks_deleted
            
            if total_chunks_deleted > 0:
                message = f"Đã xoá thành công {total_chunks_deleted} chunks cho tài liệu '{source_file}'"
                if document:
                    message += f" (document gốc được giữ lại trong database)"
                
                return Response(
                    {
                        "message": message,
                        "details": {
                            "mongodb_deleted": 0,  # Document không bị xoá
                            "chunks_deleted": total_chunks_deleted,
                            "actual_source_file": actual_source_file,
                            "document_preserved": True  # Document được giữ lại
                        }
                    },
                    status=status.HTTP_200_OK
                )
            else:
                return Response(
                    {"message": f"Không tìm thấy chunks nào cho '{source_file}' của người dùng '{uploader_username}'."},
                    status=status.HTTP_404_NOT_FOUND
                )
                
        except User.DoesNotExist:
            return Response(
                {"message": f"Người dùng '{uploader_username}' không tồn tại."},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            # print(f"🗑️ DELETE ERROR: {str(e)}")
            return Response(
                {"message": f"Lỗi khi xoá document: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )