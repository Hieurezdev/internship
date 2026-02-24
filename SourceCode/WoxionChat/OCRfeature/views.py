from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse, Http404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.conf import settings
import json
import logging

from .models import UploadedFile, OCRResultFactory
from .services import FileUploadService, OCRProcessingService
from accounts.models import User 

logger = logging.getLogger(__name__)

def get_authenticated_user(request):
    """Helper function to get authenticated user from session"""
    if not request.session.get('is_authenticated'):
        return None
    
    username = request.session.get('username')
    if not username:
        return None
    
    user = User.objects(username=username).first()
    return user

def ocr_home(request):
    """OCR feature home/dashboard view"""
    logger.info("You're currently at: /ocr/")
    try:
        # Get authenticated user from session
        user = get_authenticated_user(request)
        
        # Mock data for unauthenticated users
        if not user:
            context = {
                'recent_files': [],
                'recent_ocr_results': [],
                'stats': {
                    'total_files': 0,
                    'completed_ocr': 0,
                    'pending_ocr': 0, # Can be removed
                    'processing_ocr': 0 # Can be removed
                },
                'supported_formats': ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.txt']
            }
            return render(request, 'OCRfeature/home.html', context)

        # For authenticated users
        recent_files = FileUploadService.get_user_files(user, limit=10)
        
        # Get OCR results for user using OCRResultFactory
        recent_ocr_results = []
        if recent_files:
            try:
                # Use OCRResultFactory to get results with proper permission checking
                all_user_results = OCRResultFactory.get_results_for_user(user)
                # Get recent results and limit to 5
                recent_ocr_results = sorted(all_user_results, key=lambda x: x.created_at, reverse=True)[:5]
            except Exception as query_error:
                logger.warning(f"Failed to query OCR results: {query_error}")
                recent_ocr_results = []
        
        # Statistics for dashboard
        total_files = len(recent_files)
        completed_ocr = len([r for r in recent_ocr_results if r.is_successful])
        pending_ocr = len([r for r in recent_ocr_results if r.status == 'pending'])
        processing_ocr = len([r for r in recent_ocr_results if r.status == 'processing'])
        
        context = {
            'recent_files': recent_files,
            'recent_ocr_results': recent_ocr_results,
            'stats': {
                'total_files': total_files,
                'completed_ocr': completed_ocr,
                'pending_ocr': pending_ocr, # Can be removed
                'processing_ocr': processing_ocr # Can be removed
            },
            'supported_formats': ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.txt']
        }
        
        return render(request, 'OCRfeature/home.html', context)
        
    except Exception as e:
        logger.error(f"Error loading OCR home: {e}")
        messages.error(request, f'Lỗi tải trang chủ OCR: {str(e)}')
        return render(request, 'OCRfeature/home.html', {
            'recent_files': [],
            'recent_ocr_results': [],
            'stats': {'total_files': 0, 'completed_ocr': 0, 'pending_ocr': 0, 'processing_ocr': 0},
            'supported_formats': ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.txt']
        })

def upload_file(request):
    """Upload file view"""
    if request.method == 'POST':
        try:
            # Check session-based authentication instead of Django auth
            if not request.session.get('is_authenticated'):
                if request.headers.get('Content-Type', '').startswith('application/json'):
                    return JsonResponse({'success': False, 'error': 'Bạn cần đăng nhập để upload file.'}, status=401)
                messages.error(request, 'Bạn cần đăng nhập để upload file.')
                return render(request, 'OCRfeature/upload.html')
            
            # Get user from session
            username = request.session.get('username')
            if not username:
                if request.headers.get('Content-Type', '').startswith('application/json'):
                    return JsonResponse({'success': False, 'error': 'Phiên đăng nhập không hợp lệ.'}, status=401)
                messages.error(request, 'Phiên đăng nhập không hợp lệ.')
                return render(request, 'OCRfeature/upload.html')
            
            # Get MongoDB user
            user = User.objects(username=username).first()
            if not user:
                if request.headers.get('Content-Type', '').startswith('application/json'):
                    return JsonResponse({'success': False, 'error': 'Không tìm thấy thông tin người dùng.'}, status=404)
                messages.error(request, 'Không tìm thấy thông tin người dùng.')
                return render(request, 'OCRfeature/upload.html')
            
            title = request.POST.get('title', '').strip()
            file_obj = request.FILES.get('file')
            
            if not file_obj:
                if request.headers.get('Content-Type', '').startswith('application/json'):
                    return JsonResponse({'success': False, 'error': 'Vui lòng chọn file để upload.'}, status=400)
                messages.error(request, 'Vui lòng chọn file để upload.')
                return render(request, 'OCRfeature/upload.html')
            
            # Upload file using service
            uploaded_file = FileUploadService.upload_file(
                user=user,
                title=title,
                file_obj=file_obj
            )
            
            # Always redirect to file detail page to monitor OCR progress
            success_message = f'File "{uploaded_file.title}" đã được tải lên thành công!'
            
            # Store file info in session (useful for any future features)
            request.session['uploaded_file_id'] = str(uploaded_file.id)
            request.session['uploaded_file_title'] = uploaded_file.title
            
            # If it's an AJAX request, return JSON
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True, 
                    'message': success_message,
                    'redirect_url': reverse('OCRfeature:file_detail', args=[str(uploaded_file.id)]),
                    'file_id': str(uploaded_file.id)
                })
            else:
                messages.success(request, success_message)
                return redirect('OCRfeature:file_detail', file_id=str(uploaded_file.id))
            
        except Exception as e:
            logger.error(f"Error uploading file: {e}")
            error_message = f'Lỗi upload file: {str(e)}'
            
            # If it's an AJAX request, return JSON error
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': error_message}, status=500)
            else:
                messages.error(request, error_message)
    
    return render(request, 'OCRfeature/upload.html')

def list_files(request):
    """List user's files"""
    try:
        user = get_authenticated_user(request)
        if not user:
            return render(request, 'OCRfeature/file_list.html', {'files': []})
            
        files = FileUploadService.get_user_files(user, limit=50)
        return render(request, 'OCRfeature/file_list.html', {'files': files})
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        messages.error(request, f'Lỗi tải danh sách file: {str(e)}')
        return render(request, 'OCRfeature/file_list.html', {'files': []})

def file_detail(request, file_id):
    """File detail view with OCR results"""
    try:
        user = get_authenticated_user(request)
        if not user:
            raise Http404("Bạn cần đăng nhập để xem file.")
        logger.info("You've signed in!")
        uploaded_file = UploadedFile.objects.get(id=file_id, uploader_id=str(user.id))
        logger.info("You get uploaded_file") 
        # Get OCR results using OCRResultFactory with improved error handling
        ocr_results = []
        
        # Get all results for this user
        all_user_results = OCRResultFactory.get_results_for_user(user)
        logger.info("You got all user results")
        try:
            # Filter by source_file - no more DBRef issues
            for result in all_user_results:
                if result.source_file == str(uploaded_file.id):
                    ocr_results.append(result)
            
            # Sort by created_at descending
            ocr_results = sorted(ocr_results, key=lambda x: x.created_at, reverse=True)
            
        except Exception as query_error:
            logger.warning(f"Failed to query OCR results for file {file_id}: {query_error}")
            ocr_results = []
        
        return render(request, 'OCRfeature/file_detail.html', {
            'file': uploaded_file,
            'ocr_results': ocr_results
        })
    except UploadedFile.DoesNotExist:
        raise Http404("File không tồn tại hoặc bạn không có quyền truy cập.")
    except Exception as e:
        logger.error(f"Error in file_detail: {e}")
        messages.error(request, f'Lỗi tải chi tiết file: {str(e)}')
        return redirect('OCRfeature:list_files')

def process_ocr(request, file_id):
    """Process OCR for file - ✅ UPDATED: Sử dụng session authentication"""
    try:
        user = get_authenticated_user(request)
        if not user:
            messages.error(request, 'Bạn cần đăng nhập để xử lý OCR.')
            return redirect('OCRfeature:ocr_home')
            
        # Get the file
        uploaded_file = UploadedFile.objects.get(id=file_id, uploader_id=str(user.id))
        logger.info("Get uploaded file")
        # Check if OCR is already running using OCRResultFactory
        existing_ocr = None
        try:
            all_user_results = OCRResultFactory.get_results_for_user(user)
            # Find existing OCR for this file using source_file
            for result in all_user_results:
                if (result.source_file == str(uploaded_file.id) and 
                    result.status in ['pending', 'processing']):
                    existing_ocr = result
                    break
        except Exception as query_error:
            logger.warning(f"Failed to check existing OCR: {query_error}")
        
        if existing_ocr:
            messages.warning(request, f'OCR đang được xử lý cho file "{uploaded_file.title}"')
            return redirect('OCRfeature:file_detail', file_id=file_id)
        
        # Start OCR processing
        try:
            mistral_api_key = getattr(settings, 'MISTRAL_API_KEY', None)
            if mistral_api_key:
                logger.info(f"Starting Mistral OCR for file: {uploaded_file.title}")
                ocr_result = OCRProcessingService.Processing_with_mistral(uploaded_file, mistral_api_key)
                messages.success(request, f'OCR processing completed for "{uploaded_file.title}"!')
            else:
                # Create basic OCR task without API
                ocr_result = OCRProcessingService.create_ocr_task(uploaded_file)
                messages.info(request, f'OCR task created for "{uploaded_file.title}" (API key not configured)')
                
        except Exception as ocr_error:
            logger.error(f"OCR processing error: {ocr_error}")
            messages.error(request, f'Lỗi xử lý OCR: {str(ocr_error)}')
        
        return redirect('OCRfeature:file_detail', file_id=file_id)
        
    except UploadedFile.DoesNotExist:
        messages.error(request, 'File không tồn tại hoặc bạn không có quyền truy cập.')
        return redirect('OCRfeature:list_files')
    except Exception as e:
        logger.error(f"Error in process_ocr: {e}")
        messages.error(request, f'Lỗi xử lý OCR: {str(e)}')
        return redirect('OCRfeature:list_files')

def delete_file(request, file_id):
    """Xóa file và tất cả các kết quả OCR liên quan"""
    try:
        user = get_authenticated_user(request)
        if not user:
            messages.error(request, 'Bạn cần đăng nhập để xóa file.')
            return redirect('OCRfeature:ocr_home')

        # Lấy file để đảm bảo quyền truy cập
        uploaded_file = UploadedFile.objects.get(id=file_id, uploader_id=str(user.id))
        file_title = uploaded_file.title
        file_id_str = str(uploaded_file.id)

        # Xóa tất cả các kết quả OCR liên quan bằng cách truy vấn trực tiếp
        try:
            from .models import AdminOCRResult, UserOCRResult

            # Sử dụng __in để xóa các document có source_file khớp với file_id
            admin_deleted_count = AdminOCRResult.objects(source_file=file_id_str).delete()
            user_deleted_count = UserOCRResult.objects(source_file=file_id_str).delete()

            logger.info(
                f"Đã xóa {admin_deleted_count} bản ghi từ AdminOCRResult và "
                f"{user_deleted_count} bản ghi từ UserOCRResult cho file ID: {file_id_str}"
            )

        except Exception as delete_error:
            logger.error(f"Lỗi khi xóa kết quả OCR cho file ID {file_id_str}: {delete_error}")
            messages.error(request, 'Không thể xóa các kết quả OCR liên quan.')

        # Xóa file vật lý và bản ghi UploadedFile
        try:
            FileUploadService.delete_file(uploaded_file)
            messages.success(request, f'File "{file_title}" và các dữ liệu liên quan đã được xóa thành công!')
        
        except Exception as e:
            logger.error(f"Lỗi khi xóa file chính {file_id_str}: {e}")
            messages.error(request, f'Không thể xóa file chính: {str(e)}')

        return redirect('OCRfeature:list_files')

    except UploadedFile.DoesNotExist:
        messages.error(request, 'File không tồn tại hoặc bạn không có quyền truy cập.')
        return redirect('OCRfeature:list_files')
    except Exception as e:
        logger.error(f"Lỗi không xác định trong quá trình xóa file: {e}")
        messages.error(request, f'Đã xảy ra lỗi không mong muốn: {str(e)}')
        return redirect('OCRfeature:list_files')

def download_file(request, file_id):
    """Download file - ✅ UPDATED: Sử dụng session authentication"""
    try:
        user = get_authenticated_user(request)
        if not user:
            messages.error(request, 'Bạn cần đăng nhập để tải file.')
            return redirect('OCRfeature:ocr_home')
            
        uploaded_file = UploadedFile.objects.get(id=file_id, uploader_id=str(user.id))
        
        # Get file content from GridFS
        file_content = uploaded_file.file.read()
        filename = uploaded_file.filename
        
        # Determine content type
        content_type = uploaded_file.mime_type or 'application/octet-stream'
        
        # Create HTTP response
        response = HttpResponse(file_content, content_type=content_type)
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Content-Length'] = len(file_content)
        
        return response
        
    except UploadedFile.DoesNotExist:
        messages.error(request, 'File không tồn tại hoặc bạn không có quyền truy cập.')
        return redirect('OCRfeature:list_files')
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        messages.error(request, f'Lỗi tải file: {str(e)}')
        return redirect('OCRfeature:list_files')

def ocr_result_detail(request, result_id):
    """OCR result detail view - ✅ UPDATED: Sử dụng OCRResultFactory"""
    try:
        user = get_authenticated_user(request)
        if not user:
            raise Http404("Bạn cần đăng nhập.")
            
        # Use OCRResultFactory to get result with permission checking
        ocr_result = OCRResultFactory.get_result_by_id(result_id, user)
        
        if not ocr_result:
            raise Http404("Kết quả OCR không tồn tại hoặc bạn không có quyền truy cập.")
        
        # ✅ FIX: Correct template path
        return render(request, 'ocr_result_detail.html', {
            'result': ocr_result,
            'file': ocr_result.source_file_object,
            'collection_info': ocr_result._meta.get('collection', 'unknown')  # Debug info
        })
        
    except Exception as e:
        logger.error(f"Error loading OCR result: {e}")
        messages.error(request, f'Lỗi tải kết quả OCR: {str(e)}')
        return redirect('OCRfeature:ocr_home')

def ocr_status(request, result_id):
    """OCR status endpoint"""
    try:
        result_data = OCRProcessingService.get_processing_status(result_id)
        return JsonResponse(result_data)
    except Exception as e:
        logger.error(f"Error getting OCR status: {e}")
        return JsonResponse({'error': str(e)}, status=500)

# API Views
@csrf_exempt
@require_http_methods(["POST"])
def api_upload_file(request):
    """API endpoint for file upload - ✅ UPDATED: Sử dụng session authentication"""
    try:
        user = get_authenticated_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        title = request.POST.get('title', '').strip()
        file_obj = request.FILES.get('file')
        
        if not file_obj:
            return JsonResponse({'error': 'File is required'}, status=400)
        
        uploaded_file = FileUploadService.upload_file(
            user=user,
            title=title,
            file_obj=file_obj
        )
        
        return JsonResponse({
            'success': True,
            'file_id': str(uploaded_file.id),
            'title': uploaded_file.title,
            'filename': uploaded_file.filename,
            'size': uploaded_file.file_size
        })
        
    except Exception as e:
        logger.error(f"API upload error: {e}")
        return JsonResponse({'error': str(e)}, status=500)

def api_process_ocr(request, file_id):
    """API endpoint to process OCR - ✅ UPDATED: Sử dụng session authentication"""
    try:
        user = get_authenticated_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
            
        uploaded_file = UploadedFile.objects.get(id=file_id, uploader_id=str(user.id))
        
        # Start OCR processing
        mistral_api_key = getattr(settings, 'MISTRAL_API_KEY', None)
        if mistral_api_key:
            ocr_result = OCRProcessingService.Processing_with_mistral(uploaded_file, mistral_api_key)
        else:
            ocr_result = OCRProcessingService.create_ocr_task(uploaded_file)
        
        return JsonResponse({
            'success': True,
            'message': 'OCR processing started',
            'file_id': file_id,
            'ocr_result_id': str(ocr_result.id),
            'collection': ocr_result._meta.get('collection', 'unknown')  # Debug info về collection được sử dụng
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def api_ocr_result(request, result_id):
    """API endpoint for OCR result - ✅ UPDATED: Includes collection info"""
    try:
        result_data = OCRProcessingService.get_processing_status(result_id)
        return JsonResponse(result_data)
    except Exception as e:
        logger.error(f"API OCR result error: {e}")
        return JsonResponse({'error': str(e)}, status=500)