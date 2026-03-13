"""OSD Manager for OpenIPC cameras based on official API documentation."""
import logging
import aiohttp
import asyncio
import urllib.parse
from typing import Optional, Dict, Any, List
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

class OpenIPCOSDManager:
    """Manager for OSD functionality on OpenIPC cameras based on official API."""

    # Предустановленные шрифты из документации
    AVAILABLE_FONTS = ["UbuntuMono-Regular", "comic", "arial", "times"]
    
    # Спецификаторы для динамических данных
    SPECIFIERS = {
        "$t": "time",
        "$B": "bitrate",
        "$C": "frame_counter",
        "$M": "memory"
    }

    def __init__(self, hass: HomeAssistant, host: str, username: str, password: str, port: int = 9000):
        """Initialize OSD manager."""
        self.hass = hass
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.session = async_get_clientsession(hass)
        self._auth = aiohttp.BasicAuth(username, password)
        self._available = False
        self._regions = [0, 1, 2, 3]  # До 4х регионов как в документации
        self._region_configs = {}  # Кэш конфигураций регионов
        
        _LOGGER.info(f"🔧 OSD Manager initialized for {host}:{port}")

    @property
    def available(self) -> bool:
        """Return True if OSD API is available."""
        return self._available

    @property
    def regions(self) -> List[int]:
        """Return available regions."""
        return self._regions

    async def async_check_availability(self) -> bool:
        """Check if OSD API is available."""
        try:
            # Проверяем доступность через запрос к региону 0
            url = f"http://{self.host}:{self.port}/api/osd/0"
            _LOGGER.info(f"🔍 Checking OSD availability at {url}")
            async with self.session.get(url, auth=self._auth, timeout=3) as response:
                if response.status == 200:
                    self._available = True
                    _LOGGER.info(f"✅ OSD API available at {self.host}:{self.port}")
                    # Загружаем конфигурации всех регионов
                    await self.async_update_all_configs()
                    return True
                else:
                    _LOGGER.error(f"❌ OSD API returned HTTP {response.status}")
                    return False
        except aiohttp.ClientConnectorError as e:
            _LOGGER.error(f"❌ OSD API not available at {self.host}:{self.port} (connection refused): {e}")
            return False
        except Exception as err:
            _LOGGER.error(f"❌ OSD API check failed: {err}")
            return False

    async def async_get_region_config(self, region: int) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific region."""
        if region not in self._regions:
            _LOGGER.error(f"Invalid region {region}")
            return None

        try:
            url = f"http://{self.host}:{self.port}/api/osd/{region}"
            _LOGGER.debug(f"Getting region {region} config from {url}")
            async with self.session.get(url, auth=self._auth, timeout=5) as response:
                if response.status == 200:
                    config = await response.json()
                    self._region_configs[region] = config
                    _LOGGER.debug(f"Region {region} config: {config}")
                    return config
                else:
                    _LOGGER.error(f"Failed to get region {region} config: HTTP {response.status}")
                    return None
        except Exception as err:
            _LOGGER.error(f"Error getting region {region} config: {err}")
            return None

    async def async_update_all_configs(self) -> Dict[int, Dict[str, Any]]:
        """Update configurations for all regions."""
        for region in self._regions:
            await self.async_get_region_config(region)
        return self._region_configs

    def _escape_url_param(self, value: str) -> str:
        """
        Экранирует параметры для URL согласно документации:
        - пробелы -> %20
        - % -> %25
        - специальные символы
        """
        # Сначала экранируем процент
        value = value.replace('%', '%25')
        # Затем экранируем все остальное
        return quote(value, safe='')

    async def async_set_region_text(
        self,
        region: int = 0,
        text: str = "",
        font: str = "UbuntuMono-Regular",
        size: float = 32.0,
        color: str = "#ffffff",
        outline: str = "#0",
        thickness: float = 0.0,
        opacity: int = 255,
        posx: Optional[int] = None,
        posy: Optional[int] = None,
        save: bool = True,
    ) -> bool:
        """
        Set text for a specific OSD region according to official API.
        
        Args:
            region: Region number (0-3)
            text: Text to display (supports $t, $B, $C, $M specifiers)
            font: Font name from /usr/share/fonts/truetype/
            size: Font size (float)
            color: Text color in hex (e.g., "#ffffff" for white)
            outline: Outline color in hex
            thickness: Outline thickness
            opacity: Opacity (0-255)
            posx: X position in pixels from left edge
            posy: Y position in pixels from top edge
            save: Save to persistent config
        """
        _LOGGER.info(f"🎯 async_set_region_text called for region {region}")
        _LOGGER.info(f"📝 Parameters: text='{text}', size={size}, color={color}, posx={posx}, posy={posy}")
        
        if not self._available:
            _LOGGER.error("❌ OSD API not available")
            return False

        if region not in self._regions:
            _LOGGER.error(f"❌ Invalid region {region}. Must be one of {self._regions}")
            return False

        try:
            # Формируем параметры запроса как в curl
            params = []
            
            # Текст (обязательный параметр)
            if text:
                # Кодируем текст для URL
                import urllib.parse
                encoded_text = urllib.parse.quote(text, safe='')
                params.append(f"text={encoded_text}")
                _LOGGER.debug(f"📝 Original text: {text}")
                _LOGGER.debug(f"📝 Encoded text: {encoded_text}")
            else:
                # Если текст пустой - очищаем регион
                params.append("text=")
                _LOGGER.debug("📝 Clearing region - empty text")
            
            # Размер шрифта
            if size is not None and size != 32.0:
                params.append(f"size={size}")
                _LOGGER.debug(f"📏 Size: {size}")
            
            # Цвет (убираем # и добавляем %23 как в curl)
            if color and color != "#ffffff":
                color_value = color.replace('#', '')
                params.append(f"color=%23{color_value}")
                _LOGGER.debug(f"🎨 Color: {color} -> %23{color_value}")
            
            # Обводка
            if outline and outline != "#0":
                outline_value = outline.replace('#', '')
                params.append(f"outl=%23{outline_value}")
                _LOGGER.debug(f"🎨 Outline: {outline} -> %23{outline_value}")
            
            # Толщина обводки
            if thickness is not None and thickness != 0.0:
                params.append(f"thick={thickness}")
                _LOGGER.debug(f"📏 Thickness: {thickness}")
            
            # Прозрачность
            if opacity is not None and opacity != 255:
                params.append(f"opal={opacity}")
                _LOGGER.debug(f"🎨 Opacity: {opacity}")
            
            # Шрифт (если не стандартный)
            if font and font != "UbuntuMono-Regular":
                params.append(f"font={font}")
                _LOGGER.debug(f"🔤 Font: {font}")
            
            # Позиция X
            if posx is not None:
                params.append(f"posx={posx}")
                _LOGGER.debug(f"📌 posx: {posx}")
            
            # Позиция Y
            if posy is not None:
                params.append(f"posy={posy}")
                _LOGGER.debug(f"📌 posy: {posy}")
            
            # Сохранение
            if save:
                params.append("save=true")
                _LOGGER.debug(f"💾 Save: true")

            # Формируем URL с параметрами
            query_string = "&".join(params)
            url = f"http://{self.host}:{self.port}/api/osd/{region}?{query_string}"
            
            _LOGGER.info(f"🔗 Sending OSD request: {url}")
            
            # Отправляем GET запрос как в curl
            async with self.session.get(url, auth=self._auth, timeout=5) as response:
                _LOGGER.info(f"📡 Response status: {response.status}")
                
                if response.status == 200:
                    response_text = await response.text()
                    _LOGGER.info(f"✅ Response body: {response_text}")
                    # Обновляем кэш
                    await self.async_get_region_config(region)
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"❌ Failed to set OSD region {region}: HTTP {response.status}")
                    _LOGGER.error(f"❌ Response: {error_text}")
                    return False
                    
        except Exception as err:
            _LOGGER.error(f"❌ Error setting OSD region {region}: {err}")
            return False

    async def async_clear_region(self, region: int = 0, save: bool = True) -> bool:
        """Clear a specific OSD region by setting empty text."""
        _LOGGER.info(f"🧹 Clearing region {region}")
        
        # ВАЖНО: Устанавливаем пустой текст и сбрасываем все параметры
        # Не передаем никаких других параметров, только пустой текст
        url = f"http://{self.host}:{self.port}/api/osd/{region}?text=&save={'true' if save else 'false'}"
        
        try:
            _LOGGER.info(f"🔗 Sending OSD clear request: {url}")
            async with self.session.get(url, auth=self._auth, timeout=5) as response:
                if response.status == 200:
                    response_text = await response.text()
                    _LOGGER.info(f"✅ Region {region} cleared: {response_text}")
                    
                    # Обновляем кэш
                    await self.async_get_region_config(region)
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"❌ Failed to clear region {region}: HTTP {response.status}")
                    _LOGGER.error(f"❌ Response: {error_text}")
                    return False
        except Exception as err:
            _LOGGER.error(f"❌ Error clearing region {region}: {err}")
            return False

    async def async_clear_all_text(self, save: bool = True) -> Dict[int, bool]:
        """Clear text from all regions."""
        results = {}
        for region in self._regions:
            results[region] = await self.async_clear_region(region, save)
        return results

    async def async_set_region_image(
        self,
        region: int = 0,
        image_path: str = "",
        opacity: Optional[int] = None,
        posx: Optional[int] = None,
        posy: Optional[int] = None,
    ) -> bool:
        """
        Upload an image to an OSD region.
        
        Args:
            region: Region number (0-3)
            image_path: Path to image file (PNG or BMP)
            opacity: Opacity (0-255)
            posx: X position
            posy: Y position
        """
        _LOGGER.info(f"🖼️ Uploading image to region {region}: {image_path}")
        
        if not self._available:
            _LOGGER.error("OSD API not available")
            return False

        if region not in self._regions:
            _LOGGER.error(f"Invalid region {region}")
            return False

        if not image_path:
            _LOGGER.error("No image path provided")
            return False

        try:
            import aiofiles
            import os
            
            if not os.path.exists(image_path):
                _LOGGER.error(f"Image file not found: {image_path}")
                return False
            
            # Проверяем расширение файла (должен быть .bmp)
            if not image_path.lower().endswith('.bmp'):
                _LOGGER.warning(f"Image file should be BMP format according to documentation: {image_path}")
            
            url = f"http://{self.host}:{self.port}/api/osd/{region}"
            
            # Читаем файл
            async with aiofiles.open(image_path, 'rb') as f:
                image_data = await f.read()
            
            # Создаем multipart form data как в curl -F
            data = aiohttp.FormData()
            filename = os.path.basename(image_path)
            data.add_field('data', image_data, filename=filename, content_type='image/bmp')
            
            if opacity is not None:
                data.add_field('opal', str(opacity))
                _LOGGER.debug(f"Opacity: {opacity}")
            if posx is not None:
                data.add_field('posx', str(posx))
                _LOGGER.debug(f"posx: {posx}")
            if posy is not None:
                data.add_field('posy', str(posy))
                _LOGGER.debug(f"posy: {posy}")
            
            _LOGGER.info(f"📤 Uploading image {filename} to region {region}")
            
            # Отправляем POST запрос
            async with self.session.post(url, auth=self._auth, data=data, timeout=10) as response:
                _LOGGER.info(f"📡 Response status: {response.status}")
                
                if response.status == 200:
                    response_text = await response.text()
                    _LOGGER.info(f"✅ Response: {response_text}")
                    # Обновляем кэш
                    await self.async_get_region_config(region)
                    return True
                else:
                    error_text = await response.text()
                    _LOGGER.error(f"❌ Failed to upload image: HTTP {response.status}")
                    _LOGGER.error(f"❌ Response: {error_text}")
                    return False
                    
        except Exception as err:
            _LOGGER.error(f"❌ Error uploading image: {err}")
            return False

    async def async_set_time_format(self, format_str: str = "%d.%m.%Y %H:%M:%S") -> bool:
        """
        Set time format for $t specifier.
        According to documentation, % must be escaped as %25 in URL.
        """
        _LOGGER.info(f"⏰ Setting time format: {format_str}")
        
        try:
            # Экранируем проценты согласно документации: % -> %25
            escaped_format = format_str.replace('%', '%25')
            
            url = f"http://{self.host}:{self.port}/api/time?fmt={escaped_format}"
            
            _LOGGER.info(f"🔗 Time format URL: {url}")
            
            async with self.session.get(url, auth=self._auth, timeout=5) as response:
                _LOGGER.info(f"📡 Response status: {response.status}")
                
                if response.status == 200:
                    response_text = await response.text()
                    _LOGGER.info(f"✅ Response: {response_text}")
                    return True
                else:
                    _LOGGER.error(f"❌ Failed to set time format: HTTP {response.status}")
                    return False
        except Exception as err:
            _LOGGER.error(f"❌ Error setting time format: {err}")
            return False

    async def async_set_time(self, timestamp: Optional[int] = None) -> bool:
        """Set camera time using Unix timestamp."""
        if timestamp is None:
            import time
            timestamp = int(time.time())
        
        _LOGGER.info(f"⏰ Setting camera time to {timestamp}")
        
        try:
            url = f"http://{self.host}:{self.port}/api/time?ts={timestamp}"
            
            _LOGGER.info(f"🔗 Time URL: {url}")
            
            async with self.session.get(url, auth=self._auth, timeout=5) as response:
                _LOGGER.info(f"📡 Response status: {response.status}")
                
                if response.status == 200:
                    response_text = await response.text()
                    _LOGGER.info(f"✅ Response: {response_text}")
                    return True
                else:
                    _LOGGER.error(f"❌ Failed to set time: HTTP {response.status}")
                    return False
        except Exception as err:
            _LOGGER.error(f"❌ Error setting time: {err}")
            return False

    async def async_get_time_format(self) -> Optional[str]:
        """Get current time format."""
        try:
            url = f"http://{self.host}:{self.port}/api/time"
            async with self.session.get(url, auth=self._auth, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("format")
                else:
                    return None
        except Exception as err:
            _LOGGER.error(f"Error getting time format: {err}")
            return None

    def get_region_summary(self) -> Dict[int, Dict[str, Any]]:
        """Get a summary of all regions for display."""
        summary = {}
        for region, config in self._region_configs.items():
            summary[region] = {
                "has_text": bool(config.get("text")),
                "has_image": bool(config.get("img")),
                "position": config.get("pos", [0, 0]),
                "font": config.get("font", "unknown"),
                "size": config.get("size", 0),
                "color": config.get("color", "#ffffff"),
                "outline": config.get("outl", "#0"),
                "thickness": config.get("thick", 0.0),
                "opacity": config.get("opal", 255),
            }
        return summary

    def validate_specifiers(self, text: str) -> List[str]:
        """Check which specifiers are used in text."""
        used = []
        for spec in self.SPECIFIERS:
            if spec in text:
                used.append(self.SPECIFIERS[spec])
        return used