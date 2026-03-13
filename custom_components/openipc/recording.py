"""Recording functions for OpenIPC cameras."""
import asyncio
import logging
from datetime import datetime
from pathlib import Path

from .const import RECORD_START, RECORD_STOP, RECORD_STATUS, RECORD_MANUAL

_LOGGER = logging.getLogger(__name__)

async def start_recording(coordinator):
    """Start recording on camera SD card."""
    if coordinator.is_beward or coordinator.is_vivotek:
        _LOGGER.warning("Recording not supported for this device")
        return False
    
    _LOGGER.info("Starting recording on camera %s", coordinator.host)
    
    endpoints = [
        RECORD_START,
        "/cgi-bin/record.cgi?action=start",
        "/api/v1/record?action=start",
    ]
    
    for endpoint in endpoints:
        if await coordinator.async_send_command(endpoint):
            _LOGGER.info("Recording started via %s", endpoint)
            coordinator._recording_end_time = None
            return True
    
    _LOGGER.error("Failed to start recording")
    return False

async def stop_recording(coordinator):
    """Stop recording on camera SD card."""
    if coordinator.is_beward or coordinator.is_vivotek:
        _LOGGER.warning("Recording not supported for this device")
        return False
    
    _LOGGER.info("Stopping recording on camera %s", coordinator.host)
    
    if coordinator._recording_task:
        coordinator._recording_task.cancel()
        coordinator._recording_task = None
    
    if coordinator._ha_recording_task and not coordinator._ha_recording_task.done():
        coordinator._ha_recording_task.cancel()
    
    endpoints = [
        RECORD_STOP,
        "/cgi-bin/record.cgi?action=stop",
        "/api/v1/record?action=stop",
    ]
    
    for endpoint in endpoints:
        if await coordinator.async_send_command(endpoint):
            _LOGGER.info("Recording stopped via %s", endpoint)
            coordinator._recording_end_time = None
            return True
    
    _LOGGER.error("Failed to stop recording")
    return False

async def get_recording_status(coordinator):
    """Get recording status."""
    endpoints = [
        RECORD_STATUS,
        "/cgi-bin/record.cgi?action=status",
        "/api/v1/record/status",
    ]
    
    for endpoint in endpoints:
        try:
            url = f"http://{coordinator.host}:{coordinator.port}{endpoint}"
            async with coordinator.session.get(url, auth=coordinator.auth, timeout=3) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        return data
                    except:
                        text = await response.text()
                        if "recording" in text.lower():
                            return {
                                "recording": "active" in text.lower() or "true" in text.lower(),
                                "raw": text
                            }
        except:
            continue
    
    if coordinator._recording_end_time:
        remaining = coordinator._recording_end_time - coordinator.hass.loop.time()
        if remaining > 0:
            return {
                "recording": True,
                "remaining": int(remaining),
                "end_time": coordinator._recording_end_time,
            }
    
    return {"recording": False}

async def record_to_ha_media(coordinator, duration: int, method: str = "snapshots") -> dict:
    """Record video directly to Home Assistant media folder."""
    _LOGGER.info("Starting HA media recording for %d seconds using %s", duration, method)
    
    # Создаем имя файла
    camera_name = coordinator.recorder.camera_name if hasattr(coordinator, 'recorder') else "camera"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{camera_name}_{timestamp}_{duration}s.mp4"
    
    # Полный путь для сохранения
    if hasattr(coordinator, 'recorder') and coordinator.recorder:
        await coordinator.recorder.ensure_folder_exists()
        folder = coordinator.recorder.record_folder
        full_path = folder / filename
    else:
        full_path = Path(f"/config/media/openipc_recordings/{camera_name}/{filename}")
        full_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Записываем видео через встроенный сервис HA
        await coordinator.hass.services.async_call(
            "camera",
            "record",
            {
                "entity_id": f"camera.{camera_name}",
                "filename": str(full_path),
                "duration": duration
            },
            blocking=True
        )
        
        # Ждем окончания записи
        await asyncio.sleep(duration + 5)
        
        if full_path.exists():
            file_size = full_path.stat().st_size
            _LOGGER.info(f"✅ Recording saved: {full_path} ({file_size} bytes)")
            
            return {
                "success": True,
                "filename": str(filename),
                "filepath": str(full_path),
                "size": file_size,
                "duration": duration,
                "url": f"/local/openipc_recordings/{camera_name}/{filename}"
            }
        else:
            _LOGGER.error(f"❌ File not created: {full_path}")
            return {"success": False, "error": "File not created"}
            
    except Exception as err:
        _LOGGER.error(f"❌ Failed to record: {err}")
        return {"success": False, "error": str(err)}

async def start_timed_recording(coordinator, duration: int, save_to_ha: bool = True, method: str = "snapshots"):
    """Start recording for specified duration."""
    _LOGGER.info("Starting %d second recording on camera %s (save_to_ha=%s)", 
                 duration, coordinator.host, save_to_ha)
    
    if save_to_ha:
        if coordinator._ha_recording_task and not coordinator._ha_recording_task.done():
            coordinator._ha_recording_task.cancel()
        
        coordinator._ha_recording_task = asyncio.create_task(
            record_to_ha_media(coordinator, duration, method)
        )
        
        coordinator._recording_end_time = coordinator.hass.loop.time() + duration
        return True
    else:
        if coordinator.is_beward or coordinator.is_vivotek:
            _LOGGER.warning("SD card recording not supported for this device")
            return False
            
        await stop_recording(coordinator)
        await asyncio.sleep(1)
        
        duration_url = RECORD_MANUAL.format(duration)
        if await coordinator.async_send_command(duration_url):
            _LOGGER.info("Timed recording started via %s", duration_url)
            coordinator._recording_end_time = coordinator.hass.loop.time() + duration
            return True
        
        if await start_recording(coordinator):
            coordinator._recording_end_time = coordinator.hass.loop.time() + duration
            
            async def stop_after_delay():
                try:
                    await asyncio.sleep(duration)
                    await stop_recording(coordinator)
                except asyncio.CancelledError:
                    _LOGGER.debug("Recording timer cancelled")
            
            coordinator._recording_task = asyncio.create_task(stop_after_delay())
            return True
        
        return False

async def record_and_send_telegram(coordinator, duration: int, method: str = "snapshots",
                                  caption: str = None, chat_id: str = None) -> dict:
    """Record video and send to Telegram using camera.record service."""
    _LOGGER.info("📹 Recording and sending to Telegram for %d seconds", duration)
    
    try:
        # Создаем имя файла
        camera_name = coordinator.recorder.camera_name if hasattr(coordinator, 'recorder') else "camera"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{camera_name}_{timestamp}_{duration}s.mp4"
        
        # Полный путь для сохранения
        if hasattr(coordinator, 'recorder') and coordinator.recorder:
            await coordinator.recorder.ensure_folder_exists()
            folder = coordinator.recorder.record_folder
            full_path = folder / filename
        else:
            full_path = Path(f"/config/media/openipc_recordings/{camera_name}/{filename}")
            full_path.parent.mkdir(parents=True, exist_ok=True)
        
        _LOGGER.info(f"📁 Saving to: {full_path}")
        
        # Записываем видео через встроенный сервис HA
        await coordinator.hass.services.async_call(
            "camera",
            "record",
            {
                "entity_id": f"camera.{camera_name}",
                "filename": str(full_path),
                "duration": duration
            },
            blocking=True
        )
        
        # Ждем окончания записи
        await asyncio.sleep(duration + 5)
        
        # Проверяем, создался ли файл
        if not full_path.exists():
            _LOGGER.error(f"❌ File not created: {full_path}")
            return {"success": False, "error": "File not created"}
        
        file_size = full_path.stat().st_size
        _LOGGER.info(f"✅ File created: {full_path} ({file_size} bytes)")
        
        # Отправляем в Telegram
        telegram_sent = False
        if hasattr(coordinator, 'recorder') and coordinator.recorder:
            telegram_sent = await coordinator.recorder.send_to_telegram(
                full_path, 
                caption, 
                chat_id
            )
        
        # Показываем уведомление
        if telegram_sent:
            await coordinator.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"📹 Видео отправлено в Telegram",
                    "message": f"✅ Запись завершена и отправлена\n"
                              f"📁 {filename}\n"
                              f"⏱ Длительность: {duration} сек\n"
                              f"📊 Размер: {file_size / 1024:.1f} KB",
                    "notification_id": f"openipc_telegram_{coordinator.entry.entry_id}"
                },
                blocking=True
            )
        
        return {
            "success": True,
            "telegram_sent": telegram_sent,
            "filename": str(filename),
            "filepath": str(full_path),
            "size": file_size,
            "duration": duration
        }
        
    except Exception as err:
        _LOGGER.error(f"❌ Error in record_and_send_telegram: {err}")
        return {"success": False, "error": str(err)}