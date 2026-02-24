import requests
import json
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Flask service configuration
FLASK_SERVICE_URL = "http://localhost:5002"

@csrf_exempt
def proxy_to_flask(request, path):
    """
    Proxy requests to the Flask agenticRAG service running on port 5002
    """
    try:
        # Construct the full URL for the Flask service
        flask_url = f"{FLASK_SERVICE_URL}/{path}"
        
        # Prepare headers (excluding host-related headers)
        headers = {}
        for key, value in request.META.items():
            if key.startswith('HTTP_'):
                header_name = key[5:].replace('_', '-').title()
                # Skip problematic headers
                if header_name not in ['Host', 'Connection', 'Content-Length']:
                    headers[header_name] = value
        
        # Add content type if present
        if request.content_type:
            headers['Content-Type'] = request.content_type
        
        # Prepare request data
        data = None
        files = None
        
        if request.method in ['POST', 'PUT', 'PATCH']:
            if request.content_type and 'multipart/form-data' in request.content_type:
                # Handle file uploads
                files = {}
                for key, file in request.FILES.items():
                    files[key] = (file.name, file.read(), file.content_type)
                data = request.POST.dict()
            elif request.content_type and 'application/json' in request.content_type:
                # Handle JSON data
                data = request.body
                headers['Content-Type'] = 'application/json'
            else:
                # Handle form data
                data = request.POST.dict()
        
        # Make the request to Flask service
        response = requests.request(
            method=request.method,
            url=flask_url,
            headers=headers,
            data=data,
            files=files,
            params=request.GET.dict(),
            timeout=125,  # Changed from 30 to 125 seconds (buffer for 2 minutes)
            stream=True
        )
        
        # Create Django response
        django_response = HttpResponse(
            content=response.content,
            status=response.status_code,
            content_type=response.headers.get('content-type', 'application/json')
        )
        
        # Copy relevant headers from Flask response
        for key, value in response.headers.items():
            if key.lower() not in ['content-encoding', 'content-length', 'transfer-encoding', 'connection']:
                django_response[key] = value
        
        return django_response
        
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to Flask service at {FLASK_SERVICE_URL}")
        return JsonResponse({
            "error": "AgenticRAG service is not available",
            "message": f"Cannot connect to service at {FLASK_SERVICE_URL}"
        }, status=503)
    
    except requests.exceptions.Timeout:
        logger.error(f"Timeout when connecting to Flask service at {FLASK_SERVICE_URL}")
        return JsonResponse({
            "error": "AgenticRAG service timeout",
            "message": "The service took too long to respond"
        }, status=504)
    
    except Exception as e:
        logger.error(f"Error proxying request to Flask service: {str(e)}")
        return JsonResponse({
            "error": "Proxy error",
            "message": str(e)
        }, status=500)
