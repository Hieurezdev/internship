from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse
from . import services


class TextToSpeechAPIView(APIView):
    def post(self, request):
        text_to_convert = request.data.get('text')
        if not text_to_convert:
            return Response(
                {"error": "Vui lòng cung cấp 'text'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        voice_id = request.data.get('voice_id', 'JBFqnCBsd6RMkjVDRZzb')
        model_id = request.data.get('model_id', 'eleven_multilingual_v2')

        try:
            audio_bytes = services.text_to_speech(
                text_to_convert,
                voice_id=voice_id,
                model_id=model_id,
            )
            return HttpResponse(
                audio_bytes,
                content_type="audio/mpeg",
                status=200,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response(
                {"error": f"ElevenLabs TTS error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )