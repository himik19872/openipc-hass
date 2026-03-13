"""Services for OpenIPC integration."""
import logging
import voluptuous as vol
import aiohttp
from functools import partial

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
import homeassistant.helpers.service as service_helper

from .const import DOMAIN
from .helpers import find_coordinator_by_entity_id, find_media_player, find_button, find_switch

_LOGGER = logging.getLogger(__name__)

# Схемы сервисов
START_QR_SCAN_SCHEMA = vol.Schema({
    vol.Required('entity_id'): cv.entity_id,
    vol.Optional('expected_code', default='a4625vol'): cv.string,
    vol.Optional('timeout', default=300): vol.Coerce(int),
})

# Список всех сервисов для удаления при выгрузке
ALL_SERVICES = [
    "play_audio", "test_audio", "reboot", "set_ir_mode", "scan_devices",
    "start_recording", "stop_recording", "timed_recording", "get_recordings",
    "delete_recording", "record_and_send_telegram", "diagnose_rtsp", 
    "diagnose_telegram", "test_telegram", "get_recordings_stats",
    "delete_all_recordings", "get_video_thumbnail", "record_with_osd", "list_fonts",
    "beward_open_door", "beward_play_beep", "beward_play_ringtone", 
    "beward_enable_audio", "beward_test",
    "lnpr_get_list", "lnpr_add_plate", "lnpr_delete_plate", "lnpr_export_events",
    "lnpr_clear_events", "lnpr_clear_list", "lnpr_get_picture",
    "ptz_move", "ptz_goto_preset", "ptz_set_preset",
    "qr_scan", "qr_set_mode", "qr_stop",
    "start_qr_scan",
    # OSD сервисы
    "osd_set_text", "osd_clear", "osd_set_time_format", "osd_upload_image", "osd_get_config",
]

async def async_register_services(hass: HomeAssistant) -> None:
    """Register all services for OpenIPC."""
    
    from .services_impl import (
        async_play_audio, async_test_audio, async_reboot, async_set_ir_mode,
        async_scan_devices, async_start_recording, async_stop_recording,
        async_timed_recording, async_get_recordings, async_delete_recording,
        async_record_and_send_telegram, async_diagnose_rtsp, async_diagnose_telegram,
        async_test_telegram, async_get_recordings_stats, async_delete_all_recordings,
        async_get_video_thumbnail, async_record_with_osd, async_list_fonts,
        async_beward_open_door, async_beward_play_beep, async_beward_play_ringtone,
        async_beward_enable_audio, async_beward_test,
        async_lnpr_get_list, async_lnpr_add_plate, async_lnpr_delete_plate,
        async_lnpr_export_events, async_lnpr_clear_events, async_lnpr_clear_list,
        async_lnpr_get_picture, async_ptz_move, async_ptz_goto_preset,
        async_ptz_set_preset, async_qr_scan, async_qr_set_mode, async_qr_stop,
        async_start_qr_scan,
        # OSD функции
        async_osd_set_text, async_osd_clear, async_osd_set_time_format,
        async_osd_upload_image, async_osd_get_config,
    )
    
    from .service_schemas import (
        PLAY_AUDIO_SCHEMA, TEST_AUDIO_SCHEMA, REBOOT_SCHEMA, SET_IR_MODE_SCHEMA,
        SCAN_DEVICES_SCHEMA, START_RECORDING_SCHEMA, STOP_RECORDING_SCHEMA,
        TIMED_RECORDING_SCHEMA, GET_RECORDINGS_SCHEMA, DELETE_RECORDING_SCHEMA,
        RECORD_AND_SEND_TELEGRAM_SCHEMA, DIAGNOSE_RTSP_SCHEMA, DIAGNOSE_TELEGRAM_SCHEMA,
        TEST_TELEGRAM_SCHEMA, GET_RECORDINGS_STATS_SCHEMA, DELETE_ALL_RECORDINGS_SCHEMA,
        GET_VIDEO_THUMBNAIL_SCHEMA, RECORD_WITH_OSD_SCHEMA,
        BEWARD_OPEN_DOOR_SCHEMA, BEWARD_PLAY_BEEP_SCHEMA, BEWARD_PLAY_RINGTONE_SCHEMA,
        BEWARD_ENABLE_AUDIO_SCHEMA, BEWARD_TEST_SCHEMA,
        LNPR_GET_LIST_SCHEMA, LNPR_ADD_PLATE_SCHEMA, LNPR_DELETE_PLATE_SCHEMA,
        LNPR_EXPORT_EVENTS_SCHEMA, LNPR_CLEAR_EVENTS_SCHEMA, LNPR_CLEAR_LIST_SCHEMA,
        LNPR_GET_PICTURE_SCHEMA, PTZ_MOVE_SCHEMA, PTZ_GOTO_PRESET_SCHEMA,
        PTZ_SET_PRESET_SCHEMA, QR_SCAN_SCHEMA, QR_SET_MODE_SCHEMA, QR_STOP_SCHEMA,
        START_QR_SCAN_SCHEMA,
        # OSD схемы
        OSD_SET_TEXT_SCHEMA, OSD_CLEAR_SCHEMA, OSD_SET_TIME_FORMAT_SCHEMA,
        OSD_UPLOAD_IMAGE_SCHEMA, OSD_GET_CONFIG_SCHEMA,
    )
    
    # Функция-обертка для всех сервисов
    async def async_service_handler(call: ServiceCall):
        """Direct handler that calls the appropriate service function."""
        service = call.service
        _LOGGER.error(f"📞 async_service_handler for {service} with call.data: {call.data}")
        
        # Определяем какую функцию вызвать по имени сервиса
        if service == "play_audio":
            await async_play_audio(call, hass)
        elif service == "test_audio":
            await async_test_audio(call, hass)
        elif service == "reboot":
            await async_reboot(call, hass)
        elif service == "set_ir_mode":
            await async_set_ir_mode(call, hass)
        elif service == "scan_devices":
            await async_scan_devices(call, hass)
        elif service == "start_recording":
            await async_start_recording(call, hass)
        elif service == "stop_recording":
            await async_stop_recording(call, hass)
        elif service == "timed_recording":
            await async_timed_recording(call, hass)
        elif service == "get_recordings":
            await async_get_recordings(call, hass)
        elif service == "delete_recording":
            await async_delete_recording(call, hass)
        elif service == "record_and_send_telegram":
            await async_record_and_send_telegram(call, hass)
        elif service == "diagnose_rtsp":
            await async_diagnose_rtsp(call, hass)
        elif service == "diagnose_telegram":
            await async_diagnose_telegram(call, hass)
        elif service == "test_telegram":
            await async_test_telegram(call, hass)
        elif service == "get_recordings_stats":
            await async_get_recordings_stats(call, hass)
        elif service == "delete_all_recordings":
            await async_delete_all_recordings(call, hass)
        elif service == "get_video_thumbnail":
            await async_get_video_thumbnail(call, hass)
        elif service == "record_with_osd":
            await async_record_with_osd(call, hass)
        elif service == "list_fonts":
            await async_list_fonts(call, hass)
        elif service == "beward_open_door":
            await async_beward_open_door(call, hass)
        elif service == "beward_play_beep":
            await async_beward_play_beep(call, hass)
        elif service == "beward_play_ringtone":
            await async_beward_play_ringtone(call, hass)
        elif service == "beward_enable_audio":
            await async_beward_enable_audio(call, hass)
        elif service == "beward_test":
            await async_beward_test(call, hass)
        elif service == "lnpr_get_list":
            await async_lnpr_get_list(call, hass)
        elif service == "lnpr_add_plate":
            await async_lnpr_add_plate(call, hass)
        elif service == "lnpr_delete_plate":
            await async_lnpr_delete_plate(call, hass)
        elif service == "lnpr_export_events":
            await async_lnpr_export_events(call, hass)
        elif service == "lnpr_clear_events":
            await async_lnpr_clear_events(call, hass)
        elif service == "lnpr_clear_list":
            await async_lnpr_clear_list(call, hass)
        elif service == "lnpr_get_picture":
            await async_lnpr_get_picture(call, hass)
        elif service == "ptz_move":
            await async_ptz_move(call, hass)
        elif service == "ptz_goto_preset":
            await async_ptz_goto_preset(call, hass)
        elif service == "ptz_set_preset":
            await async_ptz_set_preset(call, hass)
        elif service == "qr_scan":
            await async_qr_scan(call, hass)
        elif service == "qr_set_mode":
            await async_qr_set_mode(call, hass)
        elif service == "qr_stop":
            await async_qr_stop(call, hass)
        elif service == "start_qr_scan":
            await async_start_qr_scan(call, hass)
        elif service == "osd_set_text":
            await async_osd_set_text(call, hass)
        elif service == "osd_clear":
            await async_osd_clear(call, hass)
        elif service == "osd_set_time_format":
            await async_osd_set_time_format(call, hass)
        elif service == "osd_upload_image":
            await async_osd_upload_image(call, hass)
        elif service == "osd_get_config":
            await async_osd_get_config(call, hass)
        else:
            _LOGGER.error(f"Unknown service: {service}")
    
    # Регистрируем все сервисы через одну общую функцию
    for service_name in ALL_SERVICES:
        if not hass.services.has_service(DOMAIN, service_name):
            # Находим соответствующую схему
            schema = None
            if service_name == "start_qr_scan":
                schema = START_QR_SCAN_SCHEMA
            elif service_name == "play_audio":
                schema = PLAY_AUDIO_SCHEMA
            elif service_name == "test_audio":
                schema = TEST_AUDIO_SCHEMA
            elif service_name == "reboot":
                schema = REBOOT_SCHEMA
            elif service_name == "set_ir_mode":
                schema = SET_IR_MODE_SCHEMA
            elif service_name == "scan_devices":
                schema = SCAN_DEVICES_SCHEMA
            elif service_name == "start_recording":
                schema = START_RECORDING_SCHEMA
            elif service_name == "stop_recording":
                schema = STOP_RECORDING_SCHEMA
            elif service_name == "timed_recording":
                schema = TIMED_RECORDING_SCHEMA
            elif service_name == "get_recordings":
                schema = GET_RECORDINGS_SCHEMA
            elif service_name == "delete_recording":
                schema = DELETE_RECORDING_SCHEMA
            elif service_name == "record_and_send_telegram":
                schema = RECORD_AND_SEND_TELEGRAM_SCHEMA
            elif service_name == "diagnose_rtsp":
                schema = DIAGNOSE_RTSP_SCHEMA
            elif service_name == "diagnose_telegram":
                schema = DIAGNOSE_TELEGRAM_SCHEMA
            elif service_name == "test_telegram":
                schema = TEST_TELEGRAM_SCHEMA
            elif service_name == "get_recordings_stats":
                schema = GET_RECORDINGS_STATS_SCHEMA
            elif service_name == "delete_all_recordings":
                schema = DELETE_ALL_RECORDINGS_SCHEMA
            elif service_name == "get_video_thumbnail":
                schema = GET_VIDEO_THUMBNAIL_SCHEMA
            elif service_name == "record_with_osd":
                schema = RECORD_WITH_OSD_SCHEMA
            elif service_name == "list_fonts":
                schema = None
            elif service_name == "beward_open_door":
                schema = BEWARD_OPEN_DOOR_SCHEMA
            elif service_name == "beward_play_beep":
                schema = BEWARD_PLAY_BEEP_SCHEMA
            elif service_name == "beward_play_ringtone":
                schema = BEWARD_PLAY_RINGTONE_SCHEMA
            elif service_name == "beward_enable_audio":
                schema = BEWARD_ENABLE_AUDIO_SCHEMA
            elif service_name == "beward_test":
                schema = BEWARD_TEST_SCHEMA
            elif service_name == "lnpr_get_list":
                schema = LNPR_GET_LIST_SCHEMA
            elif service_name == "lnpr_add_plate":
                schema = LNPR_ADD_PLATE_SCHEMA
            elif service_name == "lnpr_delete_plate":
                schema = LNPR_DELETE_PLATE_SCHEMA
            elif service_name == "lnpr_export_events":
                schema = LNPR_EXPORT_EVENTS_SCHEMA
            elif service_name == "lnpr_clear_events":
                schema = LNPR_CLEAR_EVENTS_SCHEMA
            elif service_name == "lnpr_clear_list":
                schema = LNPR_CLEAR_LIST_SCHEMA
            elif service_name == "lnpr_get_picture":
                schema = LNPR_GET_PICTURE_SCHEMA
            elif service_name == "ptz_move":
                schema = PTZ_MOVE_SCHEMA
            elif service_name == "ptz_goto_preset":
                schema = PTZ_GOTO_PRESET_SCHEMA
            elif service_name == "ptz_set_preset":
                schema = PTZ_SET_PRESET_SCHEMA
            elif service_name == "qr_scan":
                schema = QR_SCAN_SCHEMA
            elif service_name == "qr_set_mode":
                schema = QR_SET_MODE_SCHEMA
            elif service_name == "qr_stop":
                schema = QR_STOP_SCHEMA
            elif service_name == "osd_set_text":
                schema = OSD_SET_TEXT_SCHEMA
            elif service_name == "osd_clear":
                schema = OSD_CLEAR_SCHEMA
            elif service_name == "osd_set_time_format":
                schema = OSD_SET_TIME_FORMAT_SCHEMA
            elif service_name == "osd_upload_image":
                schema = OSD_UPLOAD_IMAGE_SCHEMA
            elif service_name == "osd_get_config":
                schema = OSD_GET_CONFIG_SCHEMA
            
            hass.services.async_register(
                DOMAIN, 
                service_name, 
                async_service_handler, 
                schema=schema
            )
            _LOGGER.debug("Registered service: %s", service_name)
    
    _LOGGER.info("✅ All services registered")

async def async_remove_services(hass: HomeAssistant) -> None:
    """Remove all services when last entry is unloaded."""
    for service in ALL_SERVICES:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
            _LOGGER.debug("Removed service: %s", service)