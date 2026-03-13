"""Simplified recorder for OpenIPC integration - uses HA native recording for video."""
import os
import logging
import asyncio
import aiohttp
import aiofiles
import time
from datetime import datetime
from pathlib import Path
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

from .const import DOMAIN

class OpenIPCRecorder:
    """Simplified recorder that uses HA's native recording for video."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, username: str, password: str, camera_name: str):
        """Initialize recorder."""
        self.hass = hass
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.camera_name = camera_name.replace(" ", "_").lower()
        self.session = async_get_clientsession(hass)
        self.auth = aiohttp.BasicAuth(username, password)
        
        # Путь для записей (из конфигурации)
        self.record_base = Path("/config/media/openipc_recordings")
        self.record_folder = self.record_base / self.camera_name
        
        # Текущая запись (для совместимости)
        self._current_recording = None
        
        _LOGGER.info(f"📁 Recorder initialized for {camera_name}, saving to {self.record_folder}")

    async def ensure_folder_exists(self):
        """Ensure record folder exists."""
        try:
            self.record_folder.mkdir(parents=True, exist_ok=True)
            _LOGGER.info(f"✅ Folder ensured: {self.record_folder}")
            
            # Проверяем права на запись
            test_file = self.record_folder / "test_write.tmp"
            try:
                test_file.touch()
                test_file.unlink()
                _LOGGER.debug(f"✅ Write permission OK for {self.record_folder}")
            except Exception as e:
                _LOGGER.error(f"❌ Cannot write to {self.record_folder}: {e}")
                # Пробуем исправить права
                try:
                    os.chmod(str(self.record_folder), 0o777)
                    _LOGGER.info(f"✅ Fixed permissions for {self.record_folder}")
                except:
                    pass
                    
            return True
        except Exception as err:
            _LOGGER.error(f"Failed to create record folder: {err}")
            return False

    def _get_telegram_config(self):
        """Get Telegram configuration from hass.data."""
        yaml_config = self.hass.data.get(DOMAIN, {}).get("config", {})
        bot_token = yaml_config.get("telegram_bot_token")
        chat_id = yaml_config.get("telegram_chat_id")
        
        if chat_id is not None:
            chat_id = str(chat_id)
        
        return {
            "bot_token": bot_token,
            "chat_id": chat_id
        }

    async def send_to_telegram_direct(self, filepath: Path, bot_token: str, chat_id: str, caption: str = None, max_retries: int = 5) -> bool:
        """Send file directly to Telegram API."""
        if not filepath.exists():
            _LOGGER.error(f"File not found: {filepath}")
            return False
            
        url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
        file_size_mb = filepath.stat().st_size / 1024 / 1024
        
        if file_size_mb > 50:
            _LOGGER.error("File too large for Telegram: %.2f MB (max 50 MB)", file_size_mb)
            return False
        
        timeout_seconds = max(120, min(600, int(file_size_mb * 30)))
        
        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(total=timeout_seconds * (attempt + 1))
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with aiofiles.open(filepath, 'rb') as f:
                        file_data = await f.read()
                    
                    data = aiohttp.FormData()
                    data.add_field('chat_id', str(chat_id))
                    data.add_field('video', file_data, filename=filepath.name, content_type='video/mp4')
                    
                    if caption:
                        full_caption = caption
                    else:
                        full_caption = f"📹 Запись с камеры {filepath.parent.parent.name}"
                    
                    full_caption += f"\n⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    full_caption += f"\n📊 {file_size_mb:.1f} MB"
                    
                    if len(full_caption) > 1024:
                        full_caption = full_caption[:1020] + "..."
                    
                    data.add_field('caption', full_caption)
                    
                    async with session.post(url, data=data) as response:
                        result = await response.json()
                        if result.get('ok'):
                            _LOGGER.info(f"✅ Video sent to Telegram (attempt {attempt + 1})")
                            return True
                            
            except Exception as err:
                _LOGGER.warning(f"Attempt {attempt + 1} failed: {err}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5 * (attempt + 1))
        
        _LOGGER.error("❌ All attempts failed")
        return False

    async def send_to_telegram_via_service(self, filepath: Path, caption: str = None, chat_id: str = None) -> bool:
        """Send video using telegram_bot.send_video service."""
        if not filepath.exists():
            _LOGGER.error(f"File not found: {filepath}")
            return False
        
        try:
            service_data = {
                "file": str(filepath),
                "caption": caption or f"📹 Запись с камеры\n⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
            if chat_id:
                service_data["target"] = chat_id
            
            await self.hass.services.async_call(
                "telegram_bot",
                "send_video",
                service_data,
                blocking=True
            )
            _LOGGER.info("✅ Video sent via telegram_bot service")
            return True
            
        except Exception as err:
            _LOGGER.error(f"❌ Failed: {err}")
            return False

    async def send_to_telegram(self, filepath: Path, caption: str = None, chat_id: str = None) -> bool:
        """Send recorded video to Telegram."""
        if not filepath.exists():
            _LOGGER.error(f"File not found: {filepath}")
            return False
        
        telegram_config = self._get_telegram_config()
        bot_token = telegram_config["bot_token"]
        default_chat_id = telegram_config["chat_id"]
        target_chat_id = chat_id or default_chat_id
        
        if not target_chat_id:
            _LOGGER.error("❌ No chat_id provided")
            return False
        
        # Пробуем прямой API если есть токен
        if bot_token:
            success = await self.send_to_telegram_direct(filepath, bot_token, target_chat_id, caption)
            if success:
                return True
        
        # Пробуем через сервис
        success = await self.send_to_telegram_via_service(filepath, caption, target_chat_id)
        return success

    async def get_recordings_list(self, limit: int = 20) -> list:
        """Get list of recordings in the folder."""
        recordings = []
        try:
            if not self.record_folder.exists():
                return []
            
            files = sorted(self.record_folder.glob("*.mp4"), key=lambda x: x.stat().st_ctime, reverse=True)[:limit]
            
            for file in files:
                stat = file.stat()
                recordings.append({
                    "filename": file.name,
                    "path": str(file),
                    "size": stat.st_size,
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    "url": f"/local/openipc_recordings/{self.camera_name}/{file.name}"
                })
        except Exception as err:
            _LOGGER.error("Error getting recordings list: %s", err)
        
        return recordings

    async def delete_recording(self, filename: str) -> bool:
        """Delete a recording file."""
        filepath = self.record_folder / filename
        try:
            if filepath.exists():
                filepath.unlink()
                _LOGGER.info("Deleted recording: %s", filename)
                return True
        except Exception as err:
            _LOGGER.error("Failed to delete %s: %s", filename, err)
        return False

    async def delete_all_recordings(self) -> bool:
        """Delete all recordings."""
        try:
            files = list(self.record_folder.glob("*.mp4"))
            for file in files:
                file.unlink()
            _LOGGER.info("Deleted all recordings (%d files)", len(files))
            return True
        except Exception as err:
            _LOGGER.error("Failed to delete all recordings: %s", err)
            return False

    async def diagnose_telegram(self) -> dict:
        """Diagnose Telegram bot configuration."""
        telegram_config = self._get_telegram_config()
        
        results = {
            "telegram_bot_service": self.hass.services.has_service("telegram_bot", "send_file"),
            "notify_service": self.hass.services.has_service("notify", "telegram_notify"),
            "available_services": [],
            "bot_token_configured": bool(telegram_config["bot_token"]),
            "chat_id_configured": bool(telegram_config["chat_id"])
        }
        
        services_to_check = ["send_document", "send_file", "send_video", "send_message", "send_photo"]
        for service in services_to_check:
            if self.hass.services.has_service("telegram_bot", service):
                results["available_services"].append(f"telegram_bot.{service}")
        
        return results

    async def test_telegram_file_send(self, chat_id: str = None) -> dict:
        """Test sending a file to Telegram."""
        results = {
            "methods_tested": [],
            "results": {},
            "success": False,
            "diagnostics": {}
        }
        
        _LOGGER.info("=" * 50)
        _LOGGER.info("Starting Telegram file send test")
        
        telegram_config = self._get_telegram_config()
        bot_token = telegram_config["bot_token"]
        default_chat_id = telegram_config["chat_id"]
        target_chat_id = chat_id or default_chat_id
        
        results["diagnostics"]["has_bot_token"] = bool(bot_token)
        results["diagnostics"]["has_chat_id"] = bool(target_chat_id)
        results["diagnostics"]["config_source"] = "YAML (openipc section)"
        
        results["diagnostics"]["available_services"] = []
        for domain in self.hass.services.async_services():
            for service in self.hass.services.async_services()[domain]:
                if "telegram" in domain or "telegram" in service:
                    results["diagnostics"]["available_services"].append(f"{domain}.{service}")
        
        _LOGGER.debug("Available Telegram services: %s", results["diagnostics"]["available_services"])
        
        results["diagnostics"]["external_url"] = self.hass.config.external_url
        results["diagnostics"]["internal_url"] = self.hass.config.internal_url
        
        await self.ensure_folder_exists()
        
        test_file = self.record_folder / f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            async with aiofiles.open(test_file, 'w') as f:
                await f.write(f"Test file from Home Assistant\n")
                await f.write(f"Camera: {self.camera_name}\n")
                await f.write(f"Timestamp: {datetime.now()}\n")
                await f.write("This is a test file to verify Telegram file sending.")
            
            _LOGGER.info("Test file created: %s", test_file)
            _LOGGER.info("File size: %d bytes", test_file.stat().st_size)
            
            if bot_token and target_chat_id:
                results["methods_tested"].append("direct_api (YAML)")
                try:
                    success = await self.send_to_telegram_direct(test_file, bot_token, target_chat_id, "📱 Direct API Test", max_retries=2)
                    results["results"]["direct_api (YAML)"] = "✅ Success" if success else "❌ Failed"
                except Exception as err:
                    results["results"]["direct_api (YAML)"] = f"❌ Failed: {str(err)[:100]}"
            
            if self.hass.services.has_service("telegram_bot", "send_video"):
                results["methods_tested"].append("telegram_bot.send_video (UI)")
                try:
                    success = await self.send_to_telegram_via_service(test_file, "📱 Video Test", target_chat_id)
                    results["results"]["telegram_bot.send_video (UI)"] = "✅ Success" if success else "❌ Failed"
                except Exception as err:
                    results["results"]["telegram_bot.send_video (UI)"] = f"❌ Failed: {str(err)[:100]}"
            
            if self.hass.services.has_service("telegram_bot", "send_file"):
                results["methods_tested"].append("telegram_bot.send_file (UI)")
                try:
                    service_data = {
                        "file": str(test_file),
                        "caption": f"📱 Test: send_file from {self.camera_name}"
                    }
                    if target_chat_id:
                        service_data["target"] = target_chat_id
                    
                    await self.hass.services.async_call(
                        "telegram_bot",
                        "send_file",
                        service_data,
                        blocking=True
                    )
                    results["results"]["telegram_bot.send_file (UI)"] = "✅ Success"
                except Exception as err:
                    results["results"]["telegram_bot.send_file (UI)"] = f"❌ Failed: {str(err)[:100]}"
            
            if self.hass.services.has_service("notify", "telegram_notify"):
                results["methods_tested"].append("notify.telegram_notify")
                try:
                    service_data = {
                        "message": f"📱 Test: notify from {self.camera_name}",
                        "data": {
                            "file": str(test_file)
                        }
                    }
                    if target_chat_id:
                        service_data["target"] = target_chat_id
                    
                    await self.hass.services.async_call(
                        "notify",
                        "telegram_notify",
                        service_data,
                        blocking=True
                    )
                    results["results"]["notify.telegram_notify"] = "✅ Success"
                except Exception as err:
                    results["results"]["notify.telegram_notify"] = f"❌ Failed: {str(err)[:100]}"
            
            results["success"] = any("✅" in str(result) for result in results["results"].values())
            
            message = f"📱 **Telegram Test Results for {self.camera_name}**\n\n"
            message += f"**Bot Token (YAML):** {'✅ Configured' if bot_token else '❌ Not configured'}\n"
            message += f"**Chat ID (YAML):** {'✅ Configured' if default_chat_id else '❌ Not configured'}\n"
            message += f"**Target Chat ID:** {target_chat_id or 'Not set'}\n"
            message += f"**External URL:** {self.hass.config.external_url or 'Not set'}\n\n"
            message += "**Available services:**\n"
            for service in results["diagnostics"]["available_services"][:10]:
                message += f"• {service}\n"
            message += "\n**Test results:**\n"
            for method, result in results["results"].items():
                message += f"• {method}: {result}\n"
            
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Telegram Test Results",
                    "message": message,
                    "notification_id": f"openipc_telegram_test_{int(time.time())}"
                },
                blocking=True
            )
            
        except Exception as err:
            _LOGGER.error("Error during test: %s", err)
            results["error"] = str(err)
        
        finally:
            if test_file.exists():
                try:
                    test_file.unlink()
                    _LOGGER.debug("Test file deleted")
                except Exception as err:
                    _LOGGER.warning("Failed to delete test file: %s", err)
        
        return results

    async def get_recordings_stats(self) -> dict:
        """Get statistics about recordings."""
        stats = {
            "count": 0,
            "total_size_mb": 0,
            "oldest": None,
            "newest": None,
            "by_date": {}
        }
        
        try:
            if not self.record_folder.exists():
                return stats
            
            files = list(self.record_folder.glob("*.mp4"))
            
            for file in files:
                stat = file.stat()
                size_mb = stat.st_size / 1024 / 1024
                created = datetime.fromtimestamp(stat.st_ctime)
                date_str = created.strftime("%Y-%m-%d")
                
                stats["count"] += 1
                stats["total_size_mb"] += size_mb
                
                if date_str not in stats["by_date"]:
                    stats["by_date"][date_str] = {"count": 0, "size_mb": 0}
                stats["by_date"][date_str]["count"] += 1
                stats["by_date"][date_str]["size_mb"] += size_mb
                
                if stats["oldest"] is None or created < stats["oldest"]:
                    stats["oldest"] = created
                if stats["newest"] is None or created > stats["newest"]:
                    stats["newest"] = created
            
            if stats["oldest"]:
                stats["oldest"] = stats["oldest"].isoformat()
            if stats["newest"]:
                stats["newest"] = stats["newest"].isoformat()
            
        except Exception as err:
            _LOGGER.error("Error getting recordings stats: %s", err)
        
        return stats

    async def get_video_thumbnail(self, filename: str) -> bytes:
        """Get video thumbnail using ffmpeg."""
        filepath = self.record_folder / filename
        if not filepath.exists():
            return None
        
        thumb_path = self.record_folder / f"thumb_{filename}.jpg"
        
        try:
            import subprocess
            cmd = [
                "ffmpeg",
                "-i", str(filepath),
                "-ss", "00:00:01",
                "-vframes", "1",
                "-vf", "scale=320:-1",
                "-f", "image2",
                str(thumb_path)
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            
            if thumb_path.exists():
                async with aiofiles.open(thumb_path, 'rb') as f:
                    thumb_data = await f.read()
                thumb_path.unlink()
                return thumb_data
            
        except Exception as err:
            _LOGGER.error("Error creating thumbnail: %s", err)
        
        return None

    async def list_available_fonts(self) -> list:
        """List available fonts (legacy method)."""
        return []