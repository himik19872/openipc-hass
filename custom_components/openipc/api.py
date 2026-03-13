"""API calls to OpenIPC cameras."""
import logging
import aiohttp
from typing import Optional, Dict, Any

_LOGGER = logging.getLogger(__name__)

async def get_json_config(coordinator):
    """Get JSON configuration from camera."""
    url = f"http://{coordinator.host}:{coordinator.port}/api/v1/config.json"
    try:
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=5) as response:
            if response.status == 200:
                try:
                    return await response.json()
                except ValueError as e:
                    _LOGGER.debug(f"Failed to parse JSON from {url}: {e}")
                    return {}
            else:
                _LOGGER.debug(f"HTTP {response.status} from {url}")
            return {}
    except aiohttp.ClientError as e:
        _LOGGER.debug(f"Client error getting {url}: {e}")
        return {}
    except asyncio.TimeoutError:
        _LOGGER.debug(f"Timeout getting {url}")
        return {}
    except Exception as e:
        _LOGGER.debug(f"Unexpected error getting {url}: {e}")
        return {}

async def get_metrics(coordinator):
    """Get Prometheus metrics from camera."""
    url = f"http://{coordinator.host}:{coordinator.port}/metrics"
    try:
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=5) as response:
            if response.status == 200:
                text = await response.text()
                return _parse_metrics_text(text)
            else:
                _LOGGER.debug(f"HTTP {response.status} from {url}")
            return {}
    except aiohttp.ClientError as e:
        _LOGGER.debug(f"Client error getting metrics: {e}")
        return {}
    except asyncio.TimeoutError:
        _LOGGER.debug(f"Timeout getting metrics")
        return {}
    except Exception as e:
        _LOGGER.debug(f"Unexpected error getting metrics: {e}")
        return {}

async def get_camera_status(coordinator):
    """Get camera status from HTML endpoint."""
    url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/status.cgi"
    return await _fetch_url(coordinator, url)

async def send_command(coordinator, command, params=None):
    """Send command to camera."""
    url = f"http://{coordinator.host}:{coordinator.port}{command}"
    if params:
        url += f"?{params}"
    try:
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=5) as response:
            return response.status == 200
    except aiohttp.ClientError:
        return False
    except asyncio.TimeoutError:
        return False
    except Exception:
        return False

async def _fetch_url(coordinator, url):
    """Fetch URL with error handling."""
    try:
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=5) as response:
            if response.status == 200:
                # Пробуем разные кодировки
                try:
                    text = await response.text(encoding='utf-8')
                    return {"raw": text, "status": response.status}
                except UnicodeDecodeError:
                    try:
                        text = await response.text(encoding='latin-1')
                        return {"raw": text, "status": response.status}
                    except:
                        return {"raw": "", "status": response.status}
            return {"status": response.status}
    except aiohttp.ClientError:
        return {"status": 0, "error": "connection_error"}
    except asyncio.TimeoutError:
        return {"status": 0, "error": "timeout"}
    except Exception:
        return {"status": 0, "error": "unknown"}

def _parse_metrics_text(text):
    """Parse Prometheus metrics format."""
    metrics = {}
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        # Парсим метрики с лейблами
        if '{' in line and '}' in line:
            try:
                name_part = line[:line.index('{')]
                labels_part = line[line.index('{')+1:line.index('}')]
                value_part = line[line.index('}')+1:].strip()
                
                labels = {}
                for label in labels_part.split(','):
                    if '=' in label:
                        k, v = label.split('=', 1)
                        labels[k.strip()] = v.strip().strip('"')
                
                try:
                    value = float(value_part)
                except ValueError:
                    continue
                
                if name_part not in metrics:
                    metrics[name_part] = {}
                
                if len(labels) == 1 and 'device' in labels:
                    metrics[name_part][labels['device']] = value
                else:
                    label_key = ','.join([f"{k}={v}" for k, v in labels.items()])
                    if name_part not in metrics:
                        metrics[name_part] = {}
                    metrics[name_part][label_key] = value
            except Exception as e:
                _LOGGER.debug(f"Error parsing metric line '{line}': {e}")
                continue
        else:
            # Простые метрики без лейблов
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                try:
                    value = float(parts[1])
                    metrics[name] = value
                except ValueError:
                    continue
    
    return metrics

# ==================== API для интеграции с аддоном ====================

async def async_get_cameras_list(hass):
    """Получить список камер для аддона (совместимость с существующим api.py)."""
    try:
        from . import async_get_cameras
        return await async_get_cameras(hass)
    except ImportError:
        _LOGGER.error("Failed to import async_get_cameras from __init__.py")
        return []
    except Exception as e:
        _LOGGER.error(f"Error getting cameras list: {e}")
        return []