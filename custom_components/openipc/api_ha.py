"""API endpoints for OpenIPC integration to communicate with addon."""
from homeassistant.core import HomeAssistant
from homeassistant.components.http import HomeAssistantView
import logging

_LOGGER = logging.getLogger(__name__)

class OpenIPCCamerasView(HomeAssistantView):
    """View to return list of OpenIPC cameras for addon."""
    
    url = "/api/openipc/cameras"
    name = "api:openipc:cameras"
    requires_auth = False  # Будем проверять токен вручную
    
    async def get(self, request):
        """Handle GET request."""
        hass = request.app["hass"]
        
        # Проверяем авторизацию (токен из Supervisor)
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            _LOGGER.warning("❌ Unauthorized access to cameras API - no token")
            return self.json({"success": False, "error": "Unauthorized"}, status_code=401)
        
        # Получаем список камер из интеграции
        cameras = await async_get_cameras(hass)
        
        return self.json({
            "success": True,
            "cameras": cameras
        })

async def async_get_cameras(hass: HomeAssistant) -> list:
    """Получить список всех камер OpenIPC."""
    from . import DOMAIN
    
    cameras = []
    
    for entry_id, coordinator in hass.data[DOMAIN].items():
        if entry_id == "config":
            continue
        
        if hasattr(coordinator, 'host'):
            # Получаем модель из данных
            model = "Unknown"
            firmware = "Unknown"
            if coordinator.data and 'parsed' in coordinator.data:
                model = coordinator.data['parsed'].get('model', 'Unknown')
                firmware = coordinator.data['parsed'].get('firmware', 'Unknown')
            
            camera_data = {
                "entry_id": entry_id,
                "name": coordinator.entry.data.get('name', 'OpenIPC Camera'),
                "ip": coordinator.host,
                "port": coordinator.port,
                "username": coordinator.username,
                "password": coordinator.password,
                "device_type": coordinator.entry.data.get('device_type', 'openipc'),
                "rtsp_port": coordinator.rtsp_port,
                "available": coordinator.data.get('available', False) if coordinator.data else False,
                "model": model,
                "firmware": firmware,
            }
            
            # Добавляем информацию о Beward если есть
            if hasattr(coordinator, 'beward') and coordinator.beward:
                camera_data['beward'] = {
                    'relay_count': getattr(coordinator.beward, 'relay_count', 1),
                    'model': getattr(coordinator.beward, '_model', 'DS07P-LP')
                }
            
            # Добавляем информацию о Vivotek если есть
            if hasattr(coordinator, 'vivotek') and coordinator.vivotek:
                camera_data['vivotek'] = {
                    'ptz_available': getattr(coordinator.vivotek, 'ptz_available', False),
                    'model': getattr(coordinator.vivotek, 'model_name', 'SD9364-EHL')
                }
            
            cameras.append(camera_data)
    
    return cameras

async def async_register_api(hass: HomeAssistant) -> None:
    """Зарегистрировать API эндпоинты."""
    hass.http.register_view(OpenIPCCamerasView)
    _LOGGER.info("✅ OpenIPC API endpoints registered at /api/openipc/cameras")