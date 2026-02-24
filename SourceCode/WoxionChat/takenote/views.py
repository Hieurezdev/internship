from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .services import create_note, get_notes_by_user, get_note_by_id, update_note, delete_note

@api_view(['GET'])
def list_notes(request):
    user = request.GET.get('user')
    notes = get_notes_by_user(user)
    data = [
        {
            'id': str(note.id),
            'user': note.user,
            'title': note.title,
            'content': note.content,
            'is_pinned': note.is_pinned,
            'created_at': note.created_at,
            'updated_at': note.updated_at,
        }
        for note in notes
    ]
    return Response(data)

@api_view(['POST'])
def add_note(request):
    # --- PHẦN CẢI TIẾN BẮT ĐẦU ---

    # 1. Xác định người dùng một cách an toàn
    user = request.data.get('user')
    if not user and request.user.is_authenticated:
        user = request.user.username
    
    # Nếu vẫn không có user, trả về lỗi rõ ràng
    if not user:
        return Response(
            {'error': 'Không thể xác định người dùng. Yêu cầu cần có "user" hoặc một phiên đăng nhập hợp lệ.'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # 2. Kiểm tra dữ liệu bắt buộc từ model (title)
    title = request.data.get('title')
    if not title or not title.strip(): # Kiểm tra title có tồn tại và không phải là chuỗi trống
        return Response(
            {'error': 'Trường "title" là bắt buộc và không được để trống.'}, 
            status=status.HTTP_400_BAD_REQUEST
        )

    # Lấy content, nếu không có thì mặc định là chuỗi rỗng
    content = request.data.get('content', '')
    is_pinned = request.data.get('is_pinned', False)
    # --- PHẦN CẢI TIẾN KẾT THÚC ---
    
    # Dữ liệu đã hợp lệ, tiến hành tạo note
    note = create_note(user=user, title=title, content=content)
    
    # Trả về dữ liệu note vừa tạo
    data = {
        'id': str(note.id),
        'user': note.user,
        'title': note.title,
        'content': note.content,
        'is_pinned': note.is_pinned,
        'created_at': note.created_at,
        'updated_at': note.updated_at,
    }
    return Response(data, status=status.HTTP_201_CREATED)

@api_view(['PUT'])
def edit_note(request, note_id):
    title = request.data.get('title')
    content = request.data.get('content')
    is_pinned = request.data.get('is_pinned')
    note = update_note(note_id, title=title, content=content, is_pinned=is_pinned)
    if note:
        data = {
            'id': str(note.id),
            'title': note.title,
            'content': note.content,
            'is_pinned': note.is_pinned,
            'success': True
        }
        return Response({'success': True})
    return Response({'error': 'Note not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['DELETE'])
def remove_note(request, note_id):
    if delete_note(note_id):
        return Response({'success': True})
    return Response({'error': 'Note not found'}, status=status.HTTP_404_NOT_FOUND)