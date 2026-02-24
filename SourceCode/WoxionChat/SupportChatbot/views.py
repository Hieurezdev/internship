from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from . import services

class SupportChatbotAPIView(APIView):
    def post(self, request):
        user_question = request.data.get('question')
        if not user_question:
            return Response({"error": "Không có câu hỏi."}, status=status.HTTP_400_BAD_REQUEST)

        chat_history = request.session.get('chat_history', [])
        answer = services.get_answer_with_rag(
            user_question=user_question,
            chat_history=chat_history 
        )

        chat_history.append(("user", user_question))
        chat_history.append(("model", answer))
        request.session['chat_history'] = chat_history
        request.session.modified = True

        return Response({"answer": answer}, status=status.HTTP_200_OK)
