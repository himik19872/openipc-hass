"""Service implementations for OpenIPC integration."""
from homeassistant.core import ServiceCall, HomeAssistant
import logging
import aiohttp
import os
import time
import asyncio
from pathlib import Path
from datetime import datetime

from homeassistant.const import CONF_ENTITY_ID

from .const import (
    DOMAIN,
    DEFAULT_OSD_TEMPLATE,
    DEFAULT_OSD_POSITION,
    DEFAULT_OSD_FONT_SIZE,
    DEFAULT_OSD_COLOR,
    OSD_POSITIONS,
    OSD_COLORS,
)
from .helpers import (
    find_coordinator_by_entity_id,
    find_media_player,
    find_button,
    find_switch,
)

_LOGGER = logging.getLogger(__name__)

# ==================== Basic Services ====================

async def async_play_audio(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle play audio service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    media_id = call.data.get("media_id", "beep")
    
    entity = await find_media_player(hass, entity_id)
    if entity:
        await entity.async_play_media("audio", media_id)
        _LOGGER.debug("Play audio called on %s with media_id=%s", entity_id, media_id)
    else:
        _LOGGER.error("Media player entity %s not found", entity_id)

async def async_test_audio(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle test audio service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    entity = await find_media_player(hass, entity_id)
    if entity:
        await entity.async_test_audio()
        _LOGGER.debug("Test audio called on %s", entity_id)
    else:
        _LOGGER.error("Media player entity %s not found", entity_id)

async def async_reboot(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle reboot service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    entity = await find_button(hass, entity_id)
    if entity:
        await entity.async_press()
        _LOGGER.debug("Reboot called on %s", entity_id)
    else:
        _LOGGER.error("Button entity %s not found", entity_id)

async def async_set_ir_mode(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle set IR mode service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    mode = call.data["mode"]
    
    entity = await find_switch(hass, entity_id)
    if entity:
        coordinator = await find_coordinator_by_entity_id(hass, entity_id)
        if coordinator:
            if mode == "0":
                await coordinator.async_set_night_mode("off")
            elif mode == "1":
                await coordinator.async_set_night_mode("on")
            elif mode == "2":
                await coordinator.async_set_night_mode("auto")
            _LOGGER.debug("Set IR mode %s on %s", mode, entity_id)
    else:
        _LOGGER.error("Switch entity %s not found", entity_id)

async def async_scan_devices(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle scan devices service."""
    try:
        from .discovery import OpenICPCDiscovery
        discovery = OpenICPCDiscovery(hass)
        devices = await discovery.discover_all()
        
        if devices:
            message = f"Found {len(devices)} OpenIPC camera(s):\n\n"
            for device in devices:
                message += f"📍 **{device.get('name', 'OpenIPC Camera')}**\n"
                message += f"   IP: {device['ip']}\n"
                message += f"   Port: {device.get('port', 80)}\n"
                message += f"   Source: {device.get('source', 'unknown')}\n"
                if device.get('mac'):
                    message += f"   MAC: {device['mac']}\n"
                if device.get('verified_by'):
                    message += f"   Verified: {device['verified_by']}\n"
                message += "\n"
        else:
            message = "No OpenIPC cameras found on the network"
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "OpenIPC Discovery Results",
                "message": message,
                "notification_id": "openipc_discovery"
            },
            blocking=True
        )
    except Exception as err:
        _LOGGER.error("Scan devices error: %s", err)

# ==================== Recording Services ====================

async def async_start_recording(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle start recording service using HA's native recording."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    duration = call.data.get("duration")
    filename = call.data.get("filename")
    save_to_ha = call.data.get("save_to_ha", True)
    
    if not entity_id:
        _LOGGER.error("No entity_id provided")
        return
    
    _LOGGER.info(f"🎥 Starting recording on {entity_id} via HA native recorder")
    
    if not filename and save_to_ha:
        camera_name = entity_id.replace("camera.", "").replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        coordinator = await find_coordinator_by_entity_id(hass, entity_id)
        if coordinator and hasattr(coordinator, 'recorder'):
            await coordinator.recorder.ensure_folder_exists()
            folder = coordinator.recorder.record_folder
            filename = f"{folder}/{camera_name}_{timestamp}.mp4"
        else:
            filename = f"/config/media/openipc_recordings/{camera_name}/{camera_name}_{timestamp}.mp4"
    
    service_data = {
        "entity_id": entity_id,
    }
    
    if filename:
        service_data["filename"] = filename
    
    if duration:
        service_data["duration"] = duration
    
    try:
        await hass.services.async_call(
            "camera",
            "record",
            service_data,
            blocking=True
        )
        _LOGGER.info(f"✅ Recording started via HA native recorder: {filename}")
        
        if coordinator and hasattr(coordinator, 'recorder'):
            coordinator.recorder._current_recording = {
                "filename": filename.split('/')[-1] if filename else None,
                "filepath": filename,
                "duration": duration
            }
            if duration:
                coordinator._recording_end_time = hass.loop.time() + duration
                
    except Exception as err:
        _LOGGER.error(f"❌ Failed to start recording: {err}")

async def async_stop_recording(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle stop recording service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    if not entity_id:
        _LOGGER.error("No entity_id provided")
        return
    
    _LOGGER.info(f"⏹️ Stopping recording on {entity_id}")
    
    try:
        await hass.services.async_call(
            "camera",
            "stop_record",
            {"entity_id": entity_id},
            blocking=True
        )
        _LOGGER.info(f"✅ Recording stopped")
        
        coordinator = await find_coordinator_by_entity_id(hass, entity_id)
        if coordinator:
            coordinator._recording_end_time = None
            
    except Exception as err:
        _LOGGER.error(f"❌ Failed to stop recording: {err}")

async def async_timed_recording(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle timed recording service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    duration = call.data["duration"]
    filename = call.data.get("filename")
    
    if not entity_id:
        _LOGGER.error("No entity_id provided")
        return
    
    _LOGGER.info(f"🎥 Starting timed recording on {entity_id} for {duration}s")
    
    if not filename:
        camera_name = entity_id.replace("camera.", "").replace(".", "_")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        coordinator = await find_coordinator_by_entity_id(hass, entity_id)
        if coordinator and hasattr(coordinator, 'recorder'):
            await coordinator.recorder.ensure_folder_exists()
            folder = coordinator.recorder.record_folder
            filename = f"{folder}/{camera_name}_{timestamp}_{duration}s.mp4"
        else:
            filename = f"/config/media/openipc_recordings/{camera_name}/{camera_name}_{timestamp}_{duration}s.mp4"
    
    try:
        await hass.services.async_call(
            "camera",
            "record",
            {
                "entity_id": entity_id,
                "filename": filename,
                "duration": duration
            },
            blocking=True
        )
        _LOGGER.info(f"✅ Timed recording started: {filename}")
        
        coordinator = await find_coordinator_by_entity_id(hass, entity_id)
        if coordinator:
            coordinator._recording_end_time = hass.loop.time() + duration
            
    except Exception as err:
        _LOGGER.error(f"❌ Failed to start timed recording: {err}")

async def async_get_recordings(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle get recordings service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    limit = call.data.get("limit", 20)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        recordings = await coordinator.recorder.get_recordings_list(limit)
        
        if recordings:
            message = f"📹 **Recordings for {coordinator.recorder.camera_name}**\n\n"
            for rec in recordings[:10]:
                size_mb = rec['size'] / 1024 / 1024
                message += f"• {rec['filename']}\n"
                message += f"  📊 {size_mb:.1f} MB\n"
                message += f"  📅 {rec['created']}\n\n"
        else:
            message = "No recordings found"
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"OpenIPC Recordings",
                "message": message,
                "notification_id": f"openipc_recordings_{coordinator.entry.entry_id}"
            },
            blocking=True
        )
    else:
        _LOGGER.error("Coordinator or recorder not found for entity %s", entity_id)

async def async_delete_recording(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle delete recording service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    filename = call.data["filename"]
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        success = await coordinator.recorder.delete_recording(filename)
        if success:
            _LOGGER.info("Deleted recording %s", filename)
        else:
            _LOGGER.error("Failed to delete recording %s", filename)
    else:
        _LOGGER.error("Coordinator or recorder not found for entity %s", entity_id)

async def async_record_and_send_telegram(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle record and send to Telegram service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    duration = call.data["duration"]
    caption = call.data.get("caption")
    chat_id = call.data.get("chat_id")
    
    if not entity_id:
        _LOGGER.error("No entity_id provided")
        return
    
    _LOGGER.info(f"📹 Recording and sending to Telegram for {duration}s")
    
    camera_name = entity_id.replace("camera.", "").replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        await coordinator.recorder.ensure_folder_exists()
        folder = coordinator.recorder.record_folder
        filename = f"{folder}/{camera_name}_{timestamp}_{duration}s.mp4"
    else:
        filename = f"/config/media/openipc_recordings/{camera_name}/{camera_name}_{timestamp}_{duration}s.mp4"
    
    try:
        await hass.services.async_call(
            "camera",
            "record",
            {
                "entity_id": entity_id,
                "filename": filename,
                "duration": duration
            },
            blocking=True
        )
        
        await asyncio.sleep(duration + 2)
        
        filepath = Path(filename)
        if filepath.exists():
            if coordinator and hasattr(coordinator, 'recorder'):
                success = await coordinator.recorder.send_to_telegram(filepath, caption, chat_id)
                if success:
                    _LOGGER.info(f"✅ Video recorded and sent to Telegram")
                    
                    await hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {
                            "title": f"📹 Видео отправлено",
                            "message": f"✅ Видео успешно записано и отправлено в Telegram\n"
                                      f"📁 {filepath.name}\n"
                                      f"⏱ Длительность: {duration} сек",
                            "notification_id": f"openipc_telegram_{coordinator.entry.entry_id}"
                        },
                        blocking=True
                    )
                else:
                    _LOGGER.warning(f"⚠️ Video recorded but failed to send to Telegram")
            else:
                _LOGGER.error("Recorder not available")
        else:
            _LOGGER.error(f"❌ Video file not found: {filename}")
            
    except Exception as err:
        _LOGGER.error(f"❌ Failed to record and send: {err}")

# ==================== Diagnostic Services ====================

async def async_diagnose_rtsp(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle diagnose RTSP service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        await coordinator.async_diagnose_rtsp()
    else:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)

async def async_diagnose_telegram(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle diagnose Telegram service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        await coordinator.async_diagnose_telegram()
    else:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)

async def async_test_telegram(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle test Telegram service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    chat_id = call.data.get("chat_id")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        await coordinator.async_test_telegram(chat_id)
    else:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)

# ==================== Recording Statistics ====================

async def async_get_recordings_stats(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle get recordings statistics service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        stats = await coordinator.recorder.get_recordings_stats()
        
        message = f"📊 **Recordings Statistics for {coordinator.recorder.camera_name}**\n\n"
        message += f"**Total recordings:** {stats['count']}\n"
        message += f"**Total size:** {stats['total_size_mb']:.1f} MB\n"
        if stats['oldest']:
            message += f"**Oldest:** {stats['oldest']}\n"
        if stats['newest']:
            message += f"**Newest:** {stats['newest']}\n"
        
        if stats['by_date']:
            message += "\n**By date:**\n"
            for date, data in sorted(stats['by_date'].items()):
                message += f"• {date}: {data['count']} files ({data['size_mb']:.1f} MB)\n"
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Recordings Statistics",
                "message": message,
                "notification_id": f"openipc_stats_{coordinator.entry.entry_id}"
            },
            blocking=True
        )
    else:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)

async def async_delete_all_recordings(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle delete all recordings service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        success = await coordinator.recorder.delete_all_recordings()
        
        if success:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Recordings Deleted",
                    "message": f"✅ All recordings for {coordinator.recorder.camera_name} have been deleted.",
                    "notification_id": f"openipc_delete_{coordinator.entry.entry_id}"
                },
                blocking=True
            )
    else:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)

async def async_get_video_thumbnail(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle get video thumbnail service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    filename = call.data["filename"]
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'recorder'):
        thumbnail = await coordinator.recorder.get_video_thumbnail(filename)
        if thumbnail:
            _LOGGER.info("Thumbnail created for %s", filename)
    else:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)

# ==================== OSD Recording ====================

async def async_record_with_osd(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle record with OSD service."""
    _LOGGER.debug("=" * 60)
    _LOGGER.debug("📹 RECORD WITH OSD CALLED")
    _LOGGER.debug("Call data: %s", call.data)
    
    entity_id = call.data.get(CONF_ENTITY_ID)
    duration = call.data.get("duration")
    template = call.data.get("template", DEFAULT_OSD_TEMPLATE)
    position = call.data.get("position", DEFAULT_OSD_POSITION)
    font_size = call.data.get("font_size", DEFAULT_OSD_FONT_SIZE)
    color = call.data.get("color", DEFAULT_OSD_COLOR)
    send_telegram = call.data.get("send_telegram", False)
    
    if not entity_id:
        _LOGGER.error("❌ No entity_id provided for record_with_osd service")
        return
    
    if not duration:
        _LOGGER.error("No duration provided for record_with_osd service")
        return
    
    try:
        duration = int(duration)
    except (ValueError, TypeError):
        _LOGGER.error("Invalid duration value: %s", duration)
        return
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    
    if not coordinator:
        _LOGGER.error("❌ No camera found with entity_id: %s", entity_id)
        return
        
    if not hasattr(coordinator, 'recorder'):
        _LOGGER.error("❌ Coordinator has no recorder for %s", entity_id)
        return
    
    _LOGGER.info("✅ Using camera - Name: %s, Host: %s", 
                coordinator.recorder.camera_name, coordinator.host)
    
    osd_config = {
        "template": template,
        "position": position,
        "font_size": font_size,
        "color": color,
        "bg_color": "black@0.5",
    }
    
    camera_name = entity_id.replace("camera.", "").replace(".", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{coordinator.recorder.record_folder}/{camera_name}_{timestamp}_{duration}s.mp4"
    
    try:
        if coordinator.osd_manager and coordinator.osd_manager.available:
            _LOGGER.info(f"🎯 OSD would be set on camera: {template}")
        
        await hass.services.async_call(
            "camera",
            "record",
            {
                "entity_id": entity_id,
                "filename": filename,
                "duration": duration
            },
            blocking=True
        )
        
        await asyncio.sleep(duration + 2)
        
        result = {
            "success": True,
            "filepath": filename,
            "filename": Path(filename).name,
            "duration": duration,
            "camera": coordinator.recorder.camera_name,
        }
        
        if send_telegram:
            filepath = Path(filename)
            if filepath.exists():
                await coordinator.recorder.send_to_telegram(filepath, f"📹 Запись с OSD\n⏱ {duration} секунд")
                _LOGGER.info("Video with OSD sent to Telegram")
        
        _LOGGER.info("Video with OSD recorded: %s", result["filename"])
        
    except Exception as err:
        _LOGGER.error("Failed to record video with OSD: %s", err)
        result = {"success": False, "error": str(err)}
    
    _LOGGER.debug("=" * 60)

# ==================== Font Management ====================

async def async_list_fonts(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle the list_fonts service call."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    
    if hasattr(coordinator, 'recorder') and coordinator.recorder:
        fonts = await coordinator.recorder.list_available_fonts()
        if fonts:
            message = f"📚 Найдено {len(fonts)} шрифтов:\n\n"
            for i, font in enumerate(fonts[:15], 1):
                message += f"{i}. {font}\n"
            if len(fonts) > 15:
                message += f"\n... и еще {len(fonts) - 15} шрифтов"
        else:
            message = "❌ Шрифты не найдены!\n\n"
            message += "Поместите .ttf файлы в папку:\n"
            message += "`/config/custom_components/openipc/openipc_fonts/`\n\n"
            message += "Шрифты можно скачать с:\n"
            message += "https://github.com/dejavu-fonts/dejavu-fonts"
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "OpenIPC - Доступные шрифты",
                "message": message,
                "notification_id": "openipc_fonts"
            },
            blocking=True
        )
    else:
        _LOGGER.error("Recorder not initialized")

# ==================== Beward Specific Services ====================

async def async_beward_open_door(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle Beward open door service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    main = call.data.get("main", True)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'beward') and coordinator.beward:
        await coordinator.beward.async_open_door(main)
        _LOGGER.debug("Beward open door on %s", entity_id)
    else:
        _LOGGER.error("Beward device not available for entity %s", entity_id)

async def async_beward_play_beep(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle Beward play beep service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'beward') and coordinator.beward:
        await coordinator.beward.async_play_beep()
        _LOGGER.debug("Beward play beep on %s", entity_id)
    else:
        _LOGGER.error("Beward device not available for entity %s", entity_id)

async def async_beward_play_ringtone(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle Beward play ringtone service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'beward') and coordinator.beward:
        await coordinator.beward.async_play_ringtone()
        _LOGGER.debug("Beward play ringtone on %s", entity_id)
    else:
        _LOGGER.error("Beward device not available for entity %s", entity_id)

async def async_beward_enable_audio(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle Beward enable audio service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    enable = call.data.get("enable", True)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'beward') and coordinator.beward:
        await coordinator.beward.async_enable_audio(enable)
        _LOGGER.debug("Beward enable audio %s on %s", enable, entity_id)
    else:
        _LOGGER.error("Beward device not available for entity %s", entity_id)

async def async_beward_test(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle Beward test service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if coordinator and hasattr(coordinator, 'beward') and coordinator.beward:
        results = await coordinator.beward.async_test_alarm()
        
        message = "📊 **Beward Test Results**\n\n"
        for test, result in results.items():
            status = result.get("status", "ERROR")
            status_icon = "✅" if status == 200 else "❌"
            message += f"{status_icon} **{test}**: HTTP {status}\n"
            if "response" in result:
                message += f"   Response: `{result['response'][:100]}`\n"
            message += "\n"
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Beward Device Test",
                "message": message,
                "notification_id": "beward_test"
            },
            blocking=True
        )
    else:
        _LOGGER.error("Beward device not available for entity %s", entity_id)

# ==================== LNPR Services ====================

async def async_lnpr_get_list(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR get list service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.use_addon and coordinator.addon.available:
        plates = await coordinator.addon.async_lnpr_list(coordinator.recorder.camera_name)
        if plates is not None:
            message = f"📋 **Список разрешенных номеров:**\n\n"
            if plates:
                for i, plate in enumerate(plates, 1):
                    message += f"{i}. {plate}\n"
                message += f"\nВсего: {len(plates)} номеров"
            else:
                message += "Список пуст"
            
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"LNPR Whitelist - {coordinator.recorder.camera_name}",
                    "message": message,
                    "notification_id": f"openipc_lnpr_list_{coordinator.entry.entry_id}"
                },
                blocking=True
            )
            return
    
    if not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    try:
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnpr_cgi?action=list"
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=10) as response:
            if response.status == 200:
                text = await response.text()
                
                plates = []
                lines = text.strip().split('\n')
                for line in lines:
                    if line.startswith('Number'):
                        plates.append(line)
                
                message = f"📋 **Список разрешенных номеров:**\n\n"
                if plates:
                    for i, plate in enumerate(plates, 1):
                        message += f"{i}. {plate}\n"
                    message += f"\nВсего: {len(plates)} номеров"
                else:
                    message += "Список пуст"
                
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"LNPR Whitelist - {coordinator.recorder.camera_name}",
                        "message": message,
                        "notification_id": f"openipc_lnpr_list_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
            else:
                _LOGGER.error("Failed to get LNPR list: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error getting LNPR list: %s", err)

async def async_lnpr_add_plate(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR add plate service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    number = call.data.get("number")
    begin = call.data.get("begin", "")
    end = call.data.get("end", "")
    notify = "on" if call.data.get("notify", False) else "off"
    note = call.data.get("note", "")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.use_addon and coordinator.addon.available:
        success = await coordinator.addon.async_lnpr_add(
            coordinator.recorder.camera_name,
            number,
            begin=begin,
            end=end,
            note=note
        )
        if success:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"✅ Номер добавлен - {coordinator.recorder.camera_name}",
                    "message": f"Номер {number} успешно добавлен в белый список",
                    "notification_id": f"openipc_lnpr_add_{coordinator.entry.entry_id}"
                },
                blocking=True
            )
            await coordinator.async_request_refresh()
            return
    
    if not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    try:
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnpr_cgi?action=add"
        params = f"&Number={number}"
        if begin:
            params += f"&Begin={begin}"
        if end:
            params += f"&End={end}"
        if notify:
            params += f"&Notify={notify}"
        if note:
            params += f"&Note={note}"
        
        full_url = url + params
        async with coordinator.session.get(full_url, auth=coordinator.auth, timeout=10) as response:
            if response.status == 200:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"✅ Номер добавлен - {coordinator.recorder.camera_name}",
                        "message": f"Номер {number} успешно добавлен в белый список",
                        "notification_id": f"openipc_lnpr_add_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to add LNPR plate: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error adding LNPR plate: %s", err)

async def async_lnpr_delete_plate(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR delete plate service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    number = call.data.get("number")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.use_addon and coordinator.addon.available:
        success = await coordinator.addon.async_lnpr_delete(coordinator.recorder.camera_name, number)
        if success:
            await hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": f"✅ Номер удален - {coordinator.recorder.camera_name}",
                    "message": f"Номер {number} успешно удален из белого списка",
                    "notification_id": f"openipc_lnpr_delete_{coordinator.entry.entry_id}"
                },
                blocking=True
            )
            await coordinator.async_request_refresh()
            return
    
    if not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    try:
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnpr_cgi?action=remove&Number={number}"
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=10) as response:
            if response.status == 200:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"✅ Номер удален - {coordinator.recorder.camera_name}",
                        "message": f"Номер {number} успешно удален из белого списка",
                        "notification_id": f"openipc_lnpr_delete_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to delete LNPR plate: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error deleting LNPR plate: %s", err)

async def async_lnpr_export_events(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR export events service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    days = call.data.get("days", 7)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    from datetime import datetime, timedelta
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    start_str = start_date.strftime("%Y-%m-%d %%20%H:%%20%M:%%20%S")
    end_str = end_date.strftime("%Y-%m-%d %%20%H:%%20%M:%%20%S")
    
    try:
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnprevent_cgi?action=export&begin={start_str}&end={end_str}"
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=30) as response:
            if response.status == 200:
                text = await response.text()
                
                filename = f"/config/lnpr_events_{coordinator.entry.entry_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                with open(filename, 'w') as f:
                    f.write(text)
                
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"📊 LNPR Events - {coordinator.recorder.camera_name}",
                        "message": f"✅ Экспорт завершен\n\n"
                                  f"📁 Файл: {filename}\n"
                                  f"📅 Период: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}\n"
                                  f"Размер: {len(text)} байт",
                        "notification_id": f"openipc_lnpr_export_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
            else:
                _LOGGER.error("Failed to export LNPR events: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error exporting LNPR events: %s", err)

async def async_lnpr_clear_events(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR clear events service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    try:
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnprevent_cgi?action=clear"
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=10) as response:
            if response.status == 200:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"✅ LNPR Events Cleared - {coordinator.recorder.camera_name}",
                        "message": "Журнал событий LNPR успешно очищен",
                        "notification_id": f"openipc_lnpr_clear_events_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
            else:
                _LOGGER.error("Failed to clear LNPR events: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error clearing LNPR events: %s", err)

async def async_lnpr_clear_list(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR clear list service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    try:
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnpr_cgi?action=clear"
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=10) as response:
            if response.status == 200:
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"✅ LNPR List Cleared - {coordinator.recorder.camera_name}",
                        "message": "Список разрешенных номеров успешно очищен",
                        "notification_id": f"openipc_lnpr_clear_list_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
                await coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to clear LNPR list: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error clearing LNPR list: %s", err)

async def async_lnpr_get_picture(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle LNPR get picture service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    time_str = call.data.get("time")
    filename = call.data.get("filename")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not coordinator.beward:
        _LOGGER.error("Beward device not found for entity %s", entity_id)
        return
    
    try:
        encoded_time = time_str.replace(' ', '%20')
        url = f"http://{coordinator.host}:{coordinator.port}/cgi-bin/lnprevent_cgi?action=getpic&time={encoded_time}"
        
        async with coordinator.session.get(url, auth=coordinator.auth, timeout=30) as response:
            if response.status == 200:
                data = await response.read()
                
                with open(filename, 'wb') as f:
                    f.write(data)
                
                await hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": f"✅ LNPR Picture Saved - {coordinator.recorder.camera_name}",
                        "message": f"Изображение сохранено:\n{filename}\n\nРазмер: {len(data)} байт",
                        "notification_id": f"openipc_lnpr_picture_{coordinator.entry.entry_id}"
                    },
                    blocking=True
                )
            else:
                _LOGGER.error("Failed to get LNPR picture: HTTP %d", response.status)
    except Exception as err:
        _LOGGER.error("Error getting LNPR picture: %s", err)

# ==================== PTZ Services ====================

async def async_ptz_move(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle PTZ move service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    direction = call.data["direction"]
    speed = call.data.get("speed", 50)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.use_addon and coordinator.addon.available:
        success = await coordinator.addon.async_ptz_move(
            coordinator.recorder.camera_name,
            direction,
            speed
        )
        if success:
            _LOGGER.debug("PTZ move %s on %s via add-on", direction, entity_id)
            return
    
    if coordinator.vivotek and coordinator.vivotek.ptz:
        await coordinator.vivotek.ptz.async_move(direction, speed)
        _LOGGER.debug("PTZ move %s on %s locally", direction, entity_id)
    else:
        _LOGGER.error("PTZ not available for %s", entity_id)

async def async_ptz_goto_preset(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle PTZ goto preset service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    preset_id = call.data["preset_id"]
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.use_addon and coordinator.addon.available:
        success = await coordinator.addon.async_ptz_preset(
            coordinator.recorder.camera_name,
            "goto",
            preset_id
        )
        if success:
            _LOGGER.debug("PTZ goto preset %d on %s via add-on", preset_id, entity_id)
            return
    
    if coordinator.vivotek and coordinator.vivotek.ptz:
        await coordinator.vivotek.ptz.async_goto_preset(preset_id)
        _LOGGER.debug("PTZ goto preset %d on %s locally", preset_id, entity_id)
    else:
        _LOGGER.error("PTZ not available for %s", entity_id)

async def async_ptz_set_preset(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle PTZ set preset service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    preset_id = call.data["preset_id"]
    name = call.data.get("name", f"Preset {preset_id}")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.use_addon and coordinator.addon.available:
        success = await coordinator.addon.async_ptz_preset(
            coordinator.recorder.camera_name,
            "set",
            preset_id,
            name
        )
        if success:
            _LOGGER.debug("PTZ set preset %d on %s via add-on", preset_id, entity_id)
            return
    
    if coordinator.vivotek and coordinator.vivotek.ptz:
        await coordinator.vivotek.ptz.async_set_preset(preset_id, name)
        _LOGGER.debug("PTZ set preset %d on %s locally", preset_id, entity_id)
    else:
        _LOGGER.error("PTZ not available for %s", entity_id)

# ==================== QR Code Services ====================

async def async_qr_scan(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle QR scan service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    timeout = call.data.get("timeout", 30)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.qr_scanner:
        await coordinator.qr_scanner.async_activate(
            reason=f"service_{timeout}s",
            timeout=timeout
        )
        _LOGGER.debug("QR scan activated on %s for %d seconds", entity_id, timeout)
    else:
        _LOGGER.error("QR scanner not available for %s", entity_id)

async def async_qr_set_mode(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle QR set mode service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    mode = call.data["mode"]
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.qr_scanner:
        from .qr_scanner import QRMode
        mode_map = {
            "disabled": QRMode.DISABLED,
            "single": QRMode.SINGLE,
            "periodic": QRMode.PERIODIC,
            "continuous": QRMode.CONTINUOUS
        }
        coordinator.qr_scanner.mode = mode_map.get(mode, QRMode.DISABLED)
        _LOGGER.debug("QR mode set to %s on %s", mode, entity_id)
    else:
        _LOGGER.error("QR scanner not available for %s", entity_id)

async def async_qr_stop(call: ServiceCall, hass: HomeAssistant) -> None:
    """Handle QR stop service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator:
        _LOGGER.error("Coordinator not found for entity %s", entity_id)
        return
    
    if coordinator.qr_scanner:
        await coordinator.qr_scanner.async_deactivate()
        _LOGGER.debug("QR scan stopped on %s", entity_id)
    else:
        _LOGGER.error("QR scanner not available for %s", entity_id)

# ==================== Continuous QR Scan Service ====================

async def async_start_qr_scan(call: ServiceCall, hass: HomeAssistant) -> None:
    """Start continuous QR scanning for a camera."""
    _LOGGER.error(f"🔥🔥🔥 START_QR_SCAN CALLED with data: {call.data}")
    
    entity_id = call.data.get('entity_id')
    expected_code = call.data.get('expected_code', 'a4625vol')
    timeout = call.data.get('timeout', 300)
    
    _LOGGER.error(f"🔥 entity_id: {entity_id}")
    _LOGGER.error(f"🔥 expected_code: {expected_code}")
    _LOGGER.error(f"🔥 timeout: {timeout}")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    
    _LOGGER.error(f"🔥 coordinator found: {coordinator is not None}")
    
    if not coordinator:
        _LOGGER.error(f"❌ Coordinator not found for {entity_id}")
        return
    
    _LOGGER.error(f"🔥 camera_ip: {coordinator.host}")
    _LOGGER.error(f"🔥 use_addon: {coordinator.use_addon}")
    _LOGGER.error(f"🔥 addon available: {coordinator.addon.available if coordinator.addon else False}")
    
    if not coordinator.use_addon or not coordinator.addon.available:
        _LOGGER.warning(f"⚠️ Addon not available, trying to rediscover...")
        if coordinator.addon:
            found = await coordinator.addon.async_discover_addon()
            if found:
                coordinator.use_addon = True
                _LOGGER.info(f"✅ Addon rediscovered successfully!")
            else:
                _LOGGER.error(f"❌ Addon still not available for {entity_id}")
                return
    
    if not coordinator.use_addon or not coordinator.addon.available:
        _LOGGER.error(f"❌ Addon not available for {entity_id}")
        return
    
    camera_ip = coordinator.host
    
    result = await coordinator.addon.async_start_scan(camera_ip, expected_code, timeout)
    
    if result and result.get('success'):
        _LOGGER.info(f"✅ Scan started with ID: {result.get('scan_id')}")
        
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "🔍 QR сканирование запущено",
                "message": f"Сканирование запущено для камеры {entity_id}\n"
                          f"Ожидаемый код: {expected_code}\n"
                          f"Таймаут: {timeout} сек\n"
                          f"ID: {result.get('scan_id')}",
                "notification_id": f"qr_scan_start_{int(time.time())}"
            },
            blocking=True
        )
    else:
        _LOGGER.error(f"❌ Failed to start scan")
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "❌ Ошибка QR сканирования",
                "message": f"Ошибка запуска сканирования для камеры {entity_id}",
                "notification_id": f"qr_scan_error_{int(time.time())}"
            },
            blocking=True
        )

# ==================== OSD Services ====================

async def async_osd_set_text(call: ServiceCall, hass: HomeAssistant) -> None:
    """Set OSD text service."""
    _LOGGER.error(f"🔥🔥🔥 OSD_SET_TEXT CALLED in services_impl")
    _LOGGER.error(f"🔥 Full call.data: {call.data}")
    
    entity_id = call.data.get(CONF_ENTITY_ID)
    region = call.data.get("region", 0)
    text = call.data.get("text", "")
    font = call.data.get("font", "UbuntuMono-Regular")
    size = call.data.get("size", 32.0)
    color = call.data.get("color", "#ffffff")
    outline = call.data.get("outline", "#0")
    thickness = call.data.get("thickness", 0.0)
    opacity = call.data.get("opacity", 255)
    posx = call.data.get("posx")
    posy = call.data.get("posy")
    save = call.data.get("save", True)
    
    _LOGGER.error(f"🔥 Extracted entity_id: {entity_id}")
    _LOGGER.error(f"🔥 Extracted region: {region}")
    _LOGGER.error(f"🔥 Extracted text: {text}")
    _LOGGER.error(f"🔥 Extracted color: {color}")
    _LOGGER.error(f"🔥 Extracted size: {size}")
    
    if not entity_id:
        _LOGGER.error(f"❌ No entity_id provided in call.data: {call.data}")
        return
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    
    if not coordinator:
        _LOGGER.error(f"❌ Coordinator not found for {entity_id}")
        return
    
    _LOGGER.error(f"🔥 coordinator found: {coordinator is not None}")
    _LOGGER.error(f"🔥 has osd_manager: {hasattr(coordinator, 'osd_manager')}")
    
    if not hasattr(coordinator, 'osd_manager') or not coordinator.osd_manager:
        _LOGGER.error(f"❌ OSD manager not available for {entity_id}")
        return
    
    _LOGGER.error(f"🔥 osd_manager available: {coordinator.osd_manager.available}")
    
    if not coordinator.osd_manager.available:
        _LOGGER.error(f"❌ OSD API not available for {entity_id}")
        return
    
    success = await coordinator.osd_manager.async_set_region_text(
        region=region,
        text=text,
        font=font,
        size=size,
        color=color,
        outline=outline,
        thickness=thickness,
        opacity=opacity,
        posx=posx,
        posy=posy,
        save=save
    )
    
    if success:
        _LOGGER.info(f"✅ OSD text set on {entity_id} region {region}")
    else:
        _LOGGER.error(f"❌ Failed to set OSD text on {entity_id}")

async def async_osd_clear(call: ServiceCall, hass: HomeAssistant) -> None:
    """Clear OSD region service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    region = call.data.get("region", 0)
    save = call.data.get("save", True)
    
    _LOGGER.error(f"🔥🔥🔥 OSD_CLEAR CALLED for {entity_id} region {region}")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not hasattr(coordinator, 'osd_manager') or not coordinator.osd_manager:
        _LOGGER.error(f"❌ OSD manager not available for {entity_id}")
        return
    
    if not coordinator.osd_manager.available:
        _LOGGER.error(f"❌ OSD API not available for {entity_id}")
        return
    
    success = await coordinator.osd_manager.async_clear_region(region, save)
    
    if success:
        _LOGGER.info(f"✅ OSD region {region} cleared on {entity_id}")
    else:
        _LOGGER.error(f"❌ Failed to clear OSD region on {entity_id}")

async def async_osd_set_time_format(call: ServiceCall, hass: HomeAssistant) -> None:
    """Set OSD time format service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    format_str = call.data.get("format", "%d.%m.%Y %H:%M:%S")
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not hasattr(coordinator, 'osd_manager') or not coordinator.osd_manager:
        _LOGGER.error(f"OSD manager not available for {entity_id}")
        return
    
    if not coordinator.osd_manager.available:
        _LOGGER.error(f"OSD API not available for {entity_id}")
        return
    
    success = await coordinator.osd_manager.async_set_time_format(format_str)
    
    if success:
        _LOGGER.info(f"✅ OSD time format set on {entity_id}")
    else:
        _LOGGER.error(f"❌ Failed to set OSD time format on {entity_id}")

async def async_osd_upload_image(call: ServiceCall, hass: HomeAssistant) -> None:
    """Upload image to OSD region service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    region = call.data.get("region", 0)
    image_path = call.data.get("image_path")
    opacity = call.data.get("opacity", 255)
    posx = call.data.get("posx")
    posy = call.data.get("posy")
    
    if not image_path or not os.path.exists(image_path):
        _LOGGER.error(f"Image file not found: {image_path}")
        return
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not hasattr(coordinator, 'osd_manager') or not coordinator.osd_manager:
        _LOGGER.error(f"OSD manager not available for {entity_id}")
        return
    
    if not coordinator.osd_manager.available:
        _LOGGER.error(f"OSD API not available for {entity_id}")
        return
    
    success = await coordinator.osd_manager.async_set_region_image(
        region=region,
        image_path=image_path,
        opacity=opacity,
        posx=posx,
        posy=posy
    )
    
    if success:
        _LOGGER.info(f"✅ Image uploaded to OSD region {region} on {entity_id}")
    else:
        _LOGGER.error(f"❌ Failed to upload image to OSD on {entity_id}")

async def async_osd_get_config(call: ServiceCall, hass: HomeAssistant) -> None:
    """Get OSD configuration service."""
    entity_id = call.data.get(CONF_ENTITY_ID)
    
    coordinator = await find_coordinator_by_entity_id(hass, entity_id)
    if not coordinator or not hasattr(coordinator, 'osd_manager') or not coordinator.osd_manager:
        _LOGGER.error(f"OSD manager not available for {entity_id}")
        return
    
    if not coordinator.osd_manager.available:
        _LOGGER.error(f"OSD API not available for {entity_id}")
        return
    
    configs = await coordinator.osd_manager.async_update_all_configs()
    
    message = f"📺 **OSD Configuration for {entity_id}**\n\n"
    for region, config in configs.items():
        message += f"**Region {region}:**\n"
        message += f"  • Text: {config.get('text', 'none') or 'none'}\n"
        message += f"  • Image: {config.get('img', 'none')}\n"
        message += f"  • Position: {config.get('pos', [0,0])}\n"
        message += f"  • Font: {config.get('font', 'default')} ({config.get('size', 0)}px)\n"
        message += f"  • Color: {config.get('color', '#ffffff')}\n\n"
    
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": f"OSD Configuration",
            "message": message,
            "notification_id": f"openipc_osd_config_{int(time.time())}"
        },
        blocking=True
    )