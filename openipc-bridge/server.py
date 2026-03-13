#!/usr/bin/env python3
from flask import Flask, request, jsonify, render_template, send_from_directory, Response, redirect
import subprocess
import json
import os
import logging
import tempfile
import base64
from datetime import datetime, timedelta
import requests
import re
import time
import threading
import yaml
import glob
import shutil
from typing import Dict, Optional, List

# СОЗДАЕМ FLASK ПРИЛОЖЕНИЕ ПЕРВЫМ ДЕЛОМ!
app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URL для доступа к Home Assistant через Supervisor
HASS_URL = os.environ.get('HASS_URL', 'http://supervisor/core')
SUPERVISOR_TOKEN = os.environ.get('SUPERVISOR_TOKEN', '')
HASS_TOKEN = os.environ.get('HASSIO_TOKEN', SUPERVISOR_TOKEN)

# Пути к скриптам генерации TTS
TTS_GENERATE_SCRIPT = "/app/tts_generate_openipc.sh"
TTS_GENERATE_BEWARD_SCRIPT = "/app/tts_generate.sh"
TTS_GENERATE_RHVoice_SCRIPT = "/app/tts_generate_rhvoice.sh"

# Файлы конфигурации
QR_DEBUG_FILE = "/config/qr_debug.log"
CONFIG_FILE = "/config/openipc_bridge_config.yaml"
TRANSLATIONS_DIR = "/app/translations"

# Хранилище для заданий сканирования
scan_jobs: Dict[str, dict] = {}

# Статистика QR
qr_stats = {
    "total_requests": 0,
    "successful_scans": 0,
    "failed_scans": 0,
    "total_codes_found": 0,
    "by_camera": {},
    "by_type": {},
    "last_scan_time": None,
    "last_code": None
}

state = {
    "started_at": datetime.now().isoformat(),
    "requests": 0
}

# Счетчик для отладочных снимков
debug_counter = 0

# Конфигурация по умолчанию
DEFAULT_CONFIG = {
    "telegram": {
        "bot_token": "",
        "chat_id": ""
    },
    "cameras": [
        {
            "name": "OpenIPC SIP",
            "ip": "192.168.1.4",
            "type": "openipc",
            "username": "root",
            "password": "12345",
            "snapshot_endpoints": ["/image.jpg", "/cgi-bin/api.cgi?cmd=Snap&channel=0"],
            "tts_endpoint": "/play_audio",
            "tts_format": "pcm",
            "relay_endpoints": {
                "relay1_on": "",
                "relay1_off": "",
                "relay2_on": "",
                "relay2_off": ""
            },
            "osd": {
                "enabled": True,
                "port": 9000,
                "time_format": "%d.%m.%Y %H:%M:%S",
                "regions": {
                    "0": {"type": "image", "enabled": False, "image_path": "", "posx": 10, "posy": 10},
                    "1": {"type": "text", "enabled": True, "text": "ДВЕРЬ ОТКРЫТА $t", "color": "#ff0000", "size": 48, "posx": 50, "posy": 50, "font": "UbuntuMono-Regular", "opacity": 255},
                    "2": {"type": "text", "enabled": True, "text": "ЗАПИСЬ: 3 МИН", "color": "#ffff00", "size": 36, "posx": 50, "posy": 120, "font": "UbuntuMono-Regular", "opacity": 255},
                    "3": {"type": "text", "enabled": False, "text": "", "color": "#ffffff", "size": 32, "posx": 10, "posy": 200, "font": "UbuntuMono-Regular", "opacity": 255}
                }
            }
        },
        {
            "name": "Beward Doorbell",
            "ip": "192.168.1.10",
            "type": "beward",
            "username": "admin",
            "password": "Q96811621w",
            "snapshot_endpoints": ["/cgi-bin/jpg/image.cgi", "/cgi-bin/snapshot.cgi"],
            "tts_endpoint": "/cgi-bin/audio/transmit.cgi",
            "tts_format": "alaw",
            "relay_endpoints": {
                "relay1_on": "/cgi-bin/alarmout_cgi?action=set&Output=0&Status=1",
                "relay1_off": "/cgi-bin/alarmout_cgi?action=set&Output=0&Status=0",
                "relay2_on": "/cgi-bin/alarmout_cgi?action=set&Output=1&Status=1",
                "relay2_off": "/cgi-bin/alarmout_cgi?action=set&Output=1&Status=0"
            },
            "osd": {
                "enabled": False,
                "port": 9000,
                "regions": {}
            }
        }
    ],
    "tts": {
        "provider": "google",
        "google": {
            "language": "ru",
            "slow": False
        },
        "rhvoice": {
            "voice": "anna",
            "language": "ru",
            "speed": 1.0
        },
        "yandex": {
            "api_key": "",
            "language": "ru",
            "emotion": "neutral",
            "speed": 1.0
        }
    },
    "logging": {
        "level": "INFO",
        "debug_qr": True,
        "max_debug_images": 100
    }
}

# Загружаем конфигурацию
config = DEFAULT_CONFIG.copy()

def load_config():
    """Загрузить конфигурацию из файла"""
    global config
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                file_config = yaml.safe_load(f)
                if file_config:
                    config = deep_merge(config, file_config)
                    level = config['logging'].get('level', 'INFO')
                    logger.setLevel(getattr(logging, level))
                    logger.info(f"✅ Configuration loaded from {CONFIG_FILE}")
                    logger.info(f"   Cameras: {len(config['cameras'])}")
                    logger.info(f"   TTS Provider: {config['tts']['provider']}")
        else:
            save_default_config()
            logger.info(f"✅ Created default configuration at {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"❌ Failed to load config: {e}")

def deep_merge(base, update):
    """Рекурсивное слияние словарей"""
    for key, value in update.items():
        if isinstance(value, dict) and key in base and isinstance(base[key], dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base

def save_default_config():
    """Сохранить конфигурацию по умолчанию"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(DEFAULT_CONFIG, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    except Exception as e:
        logger.error(f"❌ Failed to save default config: {e}")

def get_camera_config(camera_ip: str) -> Optional[Dict]:
    """Получить конфигурацию камеры по IP"""
    for cam in config['cameras']:
        if cam['ip'] == camera_ip:
            return cam
    return None

def get_camera_config_by_name(camera_name: str) -> Optional[Dict]:
    """Получить конфигурацию камеры по имени"""
    for cam in config['cameras']:
        if cam['name'] == camera_name:
            return cam
    return None

def write_qr_debug(msg):
    """Запись в отладочный файл QR"""
    if not config['logging'].get('debug_qr', True):
        return
    try:
        with open(QR_DEBUG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now()}: {msg}\n")
    except:
        pass

def load_translations(lang='en'):
    """Загрузить переводы"""
    try:
        trans_file = os.path.join(TRANSLATIONS_DIR, f"{lang}.yaml")
        if os.path.exists(trans_file):
            with open(trans_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load translations: {e}")
    return {}

# ==================== Основные эндпоинты ====================

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

@app.route('/config')
def config_page():
    """Страница конфигурации камер"""
    return render_template('config.html')

@app.route('/osd')
def osd_page():
    """Страница настройки OSD"""
    return render_template('osd.html')

@app.route('/qr')
def qr_page():
    """Страница QR-сканера и генератора"""
    return render_template('qr.html')

@app.route('/tts')
def tts_page():
    """Страница настройки TTS"""
    return render_template('tts.html')

# ==================== API для статуса и статистики ====================

@app.route('/api/status')
def api_status():
    """Общая статистика сервиса"""
    uptime = datetime.now() - datetime.fromisoformat(state["started_at"])
    hours = uptime.total_seconds() // 3600
    minutes = (uptime.total_seconds() % 3600) // 60
    
    return jsonify({
        "uptime": f"{int(hours)}ч {int(minutes)}м",
        "requests": state["requests"],
        "cameras_count": len(config['cameras']),
        "active_scans": len([j for j in scan_jobs.values() if j['status'] in ['starting', 'running']]),
        "qr_stats": qr_stats
    })

@app.route('/api/cameras/status')
def cameras_status():
    """Статус всех камер (исправленная версия)"""
    cameras = []
    for cam in config['cameras']:
        online = False
        # Пробуем разные способы проверки
        try:
            # Сначала пробуем получить снимок (самый надежный способ)
            endpoints = cam.get('snapshot_endpoints', ['/image.jpg'])
            for endpoint in endpoints:
                try:
                    url = f"http://{cam['ip']}{endpoint}"
                    response = requests.get(url, 
                                          auth=(cam['username'], cam['password']), 
                                          timeout=2)
                    if response.status_code == 200:
                        online = True
                        break
                except:
                    continue
                    
            # Если не получили снимок, пробуем просто проверить доступность
            if not online:
                response = requests.get(f"http://{cam['ip']}/", timeout=2)
                online = response.status_code == 200
        except:
            online = False
        
        osd_enabled = cam.get('osd', {}).get('enabled', False)
        
        cameras.append({
            "ip": cam['ip'],
            "name": cam['name'],
            "type": cam['type'],
            "online": online,
            "osd_enabled": osd_enabled,
            "osd_port": cam.get('osd', {}).get('port', 9000)
        })
    
    return jsonify({"cameras": cameras})

@app.route('/api/active_jobs')
def active_jobs():
    """Активные задачи"""
    jobs = []
    for scan_id, job in scan_jobs.items():
        if job['status'] in ['starting', 'running']:
            elapsed = time.time() - job['start_time']
            progress = min(100, int((elapsed / job['timeout']) * 100))
            jobs.append({
                "id": scan_id,
                "camera": job['camera_id'],
                "type": "QR Scan",
                "progress": progress,
                "status": job['status'],
                "expected_code": job['expected_code']
            })
    return jsonify({"jobs": jobs})

@app.route('/api/server_time')
def server_time():
    """Серверное время"""
    return jsonify({"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

@app.route('/api/check_updates')
def check_updates():
    """Проверка обновлений (заглушка)"""
    return jsonify({"message": "Текущая версия актуальна"})

@app.route('/api/camera/<path:camera_ip>/snapshot')
def camera_snapshot(camera_ip):
    """Получить снимок с камеры для предпросмотра"""
    snapshot = capture_snapshot_from_camera(camera_ip)
    if snapshot:
        return Response(snapshot, mimetype='image/jpeg')
    return '', 404

# ==================== API для работы с конфигурацией ====================

@app.route('/api/config', methods=['GET'])
def get_config_api():
    """Получить текущую конфигурацию"""
    return jsonify({
        "success": True,
        "config": config
    })

@app.route('/api/config/save', methods=['POST'])
def save_config():
    """Сохранить конфигурацию"""
    try:
        new_config = request.json
        
        if os.path.exists(CONFIG_FILE):
            backup_file = f"{CONFIG_FILE}.backup"
            shutil.copy2(CONFIG_FILE, backup_file)
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(new_config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        global config
        config = new_config
        
        level = config['logging'].get('level', 'INFO')
        logger.setLevel(getattr(logging, level))
        
        logger.info("✅ Configuration saved successfully")
        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"❌ Failed to save config: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/config/reload', methods=['POST'])
def reload_config_api():
    """Перезагрузить конфигурацию"""
    try:
        load_config()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== ИНТЕГРАЦИЯ С HOME ASSISTANT ====================

@app.route('/api/ha/import_cameras', methods=['POST'])
def import_cameras_from_ha():
    """Импортировать камеры из интеграции OpenIPC в Home Assistant"""
    try:
        headers = {
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        }
        
        url = f"{HASS_URL}/api/openipc/cameras"
        logger.info(f"📡 Requesting cameras from HA: {url}")
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"❌ Failed to get cameras from HA: HTTP {response.status_code}")
            return jsonify({
                "success": False, 
                "error": f"HTTP {response.status_code}"
            }), 500
        
        data = response.json()
        
        if not data.get('success'):
            return jsonify({"success": False, "error": "Invalid response from HA"}), 500
        
        ha_cameras = data.get('cameras', [])
        logger.info(f"📸 Found {len(ha_cameras)} cameras in HA")
        
        imported = []
        skipped = []
        
        for ha_cam in ha_cameras:
            existing = None
            for cam in config['cameras']:
                if cam['ip'] == ha_cam['ip']:
                    existing = cam
                    break
            
            if existing:
                existing['name'] = ha_cam['name']
                existing['type'] = ha_cam.get('device_type', 'openipc')
                existing['username'] = ha_cam['username']
                existing['password'] = ha_cam['password']
                if 'osd' not in existing:
                    existing['osd'] = {
                        "enabled": True,
                        "port": 9000,
                        "regions": {}
                    }
                skipped.append(ha_cam['name'])
            else:
                new_camera = {
                    "name": ha_cam['name'],
                    "ip": ha_cam['ip'],
                    "type": ha_cam.get('device_type', 'openipc'),
                    "username": ha_cam['username'],
                    "password": ha_cam['password'],
                    "snapshot_endpoints": ["/image.jpg", "/cgi-bin/api.cgi?cmd=Snap&channel=0"],
                    "tts_endpoint": "/play_audio",
                    "tts_format": "pcm",
                    "osd": {
                        "enabled": True,
                        "port": 9000,
                        "time_format": "%d.%m.%Y %H:%M:%S",
                        "regions": {
                            "0": {"type": "image", "enabled": False, "image_path": "", "posx": 10, "posy": 10},
                            "1": {"type": "text", "enabled": True, "text": "ДВЕРЬ ОТКРЫТА $t", "color": "#ff0000", "size": 48, "posx": 50, "posy": 50, "font": "UbuntuMono-Regular", "opacity": 255},
                            "2": {"type": "text", "enabled": True, "text": "ЗАПИСЬ: 3 МИН", "color": "#ffff00", "size": 36, "posx": 50, "posy": 120, "font": "UbuntuMono-Regular", "opacity": 255},
                            "3": {"type": "text", "enabled": False, "text": "", "color": "#ffffff", "size": 32, "posx": 10, "posy": 200, "font": "UbuntuMono-Regular", "opacity": 255}
                        }
                    }
                }
                
                if ha_cam.get('device_type') == 'beward':
                    new_camera['tts_format'] = 'alaw'
                    new_camera['tts_endpoint'] = '/cgi-bin/audio/transmit.cgi'
                    new_camera['snapshot_endpoints'] = ['/cgi-bin/jpg/image.cgi', '/cgi-bin/snapshot.cgi']
                    new_camera['relay_endpoints'] = {
                        "relay1_on": "/cgi-bin/alarmout_cgi?action=set&Output=0&Status=1",
                        "relay1_off": "/cgi-bin/alarmout_cgi?action=set&Output=0&Status=0",
                        "relay2_on": "/cgi-bin/alarmout_cgi?action=set&Output=1&Status=1",
                        "relay2_off": "/cgi-bin/alarmout_cgi?action=set&Output=1&Status=0"
                    }
                elif ha_cam.get('device_type') == 'vivotek':
                    new_camera['snapshot_endpoints'] = ['/cgi-bin/viewer/video.jpg', '/cgi-bin/video.jpg']
                
                config['cameras'].append(new_camera)
                imported.append(ha_cam['name'])
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        logger.info(f"✅ Imported {len(imported)} new cameras, updated {len(skipped)} existing")
        
        return jsonify({
            "success": True,
            "imported": imported,
            "skipped": skipped,
            "total": len(config['cameras'])
        })
        
    except Exception as e:
        logger.error(f"❌ Error importing cameras: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/ha/cameras', methods=['GET'])
def get_ha_cameras_list():
    """Получить список камер из HA без импорта"""
    try:
        headers = {
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        }
        
        url = f"{HASS_URL}/api/openipc/cameras"
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code != 200:
            return jsonify({"success": False, "error": f"HTTP {response.status_code}"}), 500
        
        data = response.json()
        return jsonify(data)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== OSD API ====================

@app.route('/api/osd/cameras', methods=['GET'])
def list_osd_cameras():
    """Список камер с поддержкой OSD"""
    cameras = []
    for cam in config['cameras']:
        if 'osd' in cam:
            cameras.append({
                "ip": cam['ip'],
                "name": cam['name'],
                "type": cam['type'],
                "osd_enabled": cam['osd'].get('enabled', False),
                "osd_port": cam['osd'].get('port', 9000)
            })
        else:
            cameras.append({
                "ip": cam['ip'],
                "name": cam['name'],
                "type": cam['type'],
                "osd_enabled": False,
                "osd_port": 9000
            })
    return jsonify({"success": True, "cameras": cameras})

@app.route('/api/osd/camera/<path:camera_ip>', methods=['GET'])
def get_camera_osd_config(camera_ip):
    """Получить конфигурацию OSD для камеры"""
    cam_config = get_camera_config(camera_ip)
    if not cam_config:
        return jsonify({"success": False, "error": "Camera not found"}), 404
    
    if 'osd' not in cam_config:
        cam_config['osd'] = {
            "enabled": True,
            "port": 9000,
            "time_format": "%d.%m.%Y %H:%M:%S",
            "regions": {}
        }
    
    try:
        osd_port = cam_config['osd'].get('port', 9000)
        auth = (cam_config['username'], cam_config['password'])
        
        for region in range(4):
            url = f"http://{camera_ip}:{osd_port}/api/osd/{region}"
            try:
                response = requests.get(url, auth=auth, timeout=2)
                if response.status_code == 200:
                    cam_config['osd']['regions'][str(region)] = response.json()
            except Exception as e:
                logger.debug(f"Failed to get OSD state for region {region}: {e}")
    except Exception as e:
        logger.error(f"Failed to get OSD state: {e}")
    
    return jsonify({"success": True, "config": cam_config['osd']})

@app.route('/api/osd/camera/<path:camera_ip>/region/<int:region>', methods=['POST'])
def set_osd_region(camera_ip, region):
    """Установить параметры региона OSD"""
    data = request.json
    
    cam_config = get_camera_config(camera_ip)
    if not cam_config:
        return jsonify({"success": False, "error": "Camera not found"}), 404
    
    osd_port = cam_config.get('osd', {}).get('port', 9000)
    auth = (cam_config['username'], cam_config['password'])
    
    params = []
    
    if 'text' in data:
        text = data['text']
        if text == "":
            params.append("text=")
        else:
            params.append(f"text={requests.utils.quote(text)}")
    
    if 'color' in data:
        color = data['color'].replace('#', '')
        params.append(f"color=%23{color}")
    
    if 'size' in data:
        params.append(f"size={data['size']}")
    
    if 'posx' in data:
        params.append(f"posx={data['posx']}")
    
    if 'posy' in data:
        params.append(f"posy={data['posy']}")
    
    if 'opacity' in data:
        params.append(f"opacity={data['opacity']}")
    
    if 'font' in data:
        params.append(f"font={data['font']}")
    
    if 'outline' in data:
        outline = data['outline'].replace('#', '')
        params.append(f"outl=%23{outline}")
    
    if 'thickness' in data:
        params.append(f"thick={data['thickness']}")
    
    if not params:
        return jsonify({"success": False, "error": "No parameters"}), 400
    
    url = f"http://{camera_ip}:{osd_port}/api/osd/{region}?{'&'.join(params)}"
    logger.info(f"Setting OSD region {region}: {url}")
    
    try:
        response = requests.get(url, auth=auth, timeout=5)
        return jsonify({
            "success": response.status_code == 200,
            "status": response.status_code,
            "response": response.text
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/osd/camera/<path:camera_ip>/region/<int:region>/clear', methods=['POST'])
def clear_osd_region(camera_ip, region):
    """Очистить регион OSD"""
    cam_config = get_camera_config(camera_ip)
    if not cam_config:
        return jsonify({"success": False, "error": "Camera not found"}), 404
    
    osd_port = cam_config.get('osd', {}).get('port', 9000)
    auth = (cam_config['username'], cam_config['password'])
    
    url = f"http://{camera_ip}:{osd_port}/api/osd/{region}?text="
    
    try:
        response = requests.get(url, auth=auth, timeout=5)
        return jsonify({
            "success": response.status_code == 200,
            "status": response.status_code
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/osd/camera/<path:camera_ip>/time', methods=['POST'])
def set_osd_time_format(camera_ip):
    """Установить формат времени для $t"""
    data = request.json
    time_format = data.get('format', '%d.%m.%Y %H:%M:%S')
    
    cam_config = get_camera_config(camera_ip)
    if not cam_config:
        return jsonify({"success": False, "error": "Camera not found"}), 404
    
    osd_port = cam_config.get('osd', {}).get('port', 9000)
    auth = (cam_config['username'], cam_config['password'])
    
    escaped_format = time_format.replace('%', '%25')
    url = f"http://{camera_ip}:{osd_port}/api/time?fmt={escaped_format}"
    
    try:
        response = requests.get(url, auth=auth, timeout=5)
        return jsonify({
            "success": response.status_code == 200,
            "status": response.status_code,
            "format": time_format
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/osd/camera/<path:camera_ip>/logo', methods=['POST'])
def upload_osd_logo(camera_ip):
    """Загрузить логотип в OSD"""
    data = request.json
    region = data.get('region', 0)
    logo_path = data.get('logo_path')
    posx = data.get('posx', 10)
    posy = data.get('posy', 10)
    
    if not logo_path or not os.path.exists(logo_path):
        return jsonify({"success": False, "error": "Logo file not found"}), 404
    
    cam_config = get_camera_config(camera_ip)
    if not cam_config:
        return jsonify({"success": False, "error": "Camera not found"}), 404
    
    osd_port = cam_config.get('osd', {}).get('port', 9000)
    auth = (cam_config['username'], cam_config['password'])
    
    url = f"http://{camera_ip}:{osd_port}/api/osd/{region}?posx={posx}&posy={posy}"
    
    try:
        with open(logo_path, 'rb') as f:
            files = {'data': f}
            response = requests.post(url, files=files, auth=auth, timeout=10)
        
        return jsonify({
            "success": response.status_code == 200,
            "status": response.status_code
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ==================== QR API ====================

@app.route('/api/debug/clear', methods=['POST'])
def clear_debug():
    """Очистить отладочные снимки"""
    try:
        debug_files = glob.glob("/config/www/qr_debug_*.jpg")
        marked_files = glob.glob("/config/www/qr_marked_*.jpg")
        
        for f in debug_files + marked_files:
            try:
                os.remove(f)
            except:
                pass
        
        logger.info(f"✅ Cleared {len(debug_files) + len(marked_files)} debug images")
        return jsonify({"success": True, "count": len(debug_files) + len(marked_files)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/qr/stats', methods=['GET'])
def qr_statistics():
    """Получить статистику QR сканирования"""
    return jsonify({
        "success": True,
        "stats": qr_stats
    })

@app.route('/api/qr/debug', methods=['GET'])
def qr_debug():
    """Получить последние 50 строк отладки QR"""
    try:
        if os.path.exists(QR_DEBUG_FILE):
            with open(QR_DEBUG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-50:]
            return jsonify({
                "success": True,
                "debug": lines
            })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    return jsonify({"success": True, "debug": []})

@app.route('/api/send_telegram_photo', methods=['POST'])
def send_telegram_photo():
    """Отправить фото в Telegram"""
    data = request.json
    photo_base64 = data.get('photo')
    caption = data.get('caption', 'QR-код')
    chat_id = data.get('chat_id')
    
    if not photo_base64:
        return jsonify({"success": False, "error": "No photo data"}), 400
    
    if not chat_id:
        chat_id = config.get('telegram', {}).get('chat_id')
    
    if not chat_id:
        return jsonify({"success": False, "error": "No chat_id configured"}), 400
    
    try:
        photo_bytes = base64.b64decode(photo_base64)
        
        bot_token = config.get('telegram', {}).get('bot_token')
        if not bot_token:
            return jsonify({"success": False, "error": "Telegram bot not configured"}), 400
        
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        
        files = {
            'photo': ('qr.png', photo_bytes, 'image/png')
        }
        data = {
            'chat_id': chat_id,
            'caption': caption
        }
        
        response = requests.post(url, files=files, data=data, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            logger.info(f"✅ Photo sent to Telegram chat {chat_id}")
            return jsonify({"success": True})
        else:
            logger.error(f"❌ Telegram error: {result}")
            return jsonify({"success": False, "error": result.get('description', 'Unknown error')}), 500
            
    except Exception as e:
        logger.error(f"Error sending to Telegram: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/translations/<lang>')
def get_translations(lang):
    """Получить переводы для указанного языка"""
    return jsonify(load_translations(lang))

def capture_snapshot_from_camera(camera_ip: str) -> Optional[bytes]:
    """Получить снимок с камеры используя конфигурацию"""
    global debug_counter
    
    try:
        cam_config = get_camera_config(camera_ip)
        if not cam_config:
            logger.error(f"❌ No configuration found for camera {camera_ip}")
            return None
        
        camera_type = cam_config.get('type', 'openipc')
        username = cam_config.get('username', 'root')
        password = cam_config.get('password', '12345')
        endpoints = cam_config.get('snapshot_endpoints', ['/image.jpg'])
        
        auth = (username, password)
        
        for endpoint in endpoints:
            url = f"http://{camera_ip}{endpoint}"
            logger.info(f"📸 Capturing {camera_type} snapshot from {url}")
            
            try:
                response = requests.get(url, timeout=5, auth=auth)
                if response.status_code == 200:
                    data = response.content
                    if len(data) > 1000:
                        logger.info(f"✅ Snapshot captured: {len(data)} bytes from {endpoint}")
                        
                        if config['logging'].get('debug_qr', True):
                            debug_counter += 1
                            max_debug = config['logging'].get('max_debug_images', 100)
                            
                            if debug_counter <= max_debug and debug_counter % 3 == 0:
                                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                debug_path = f"/config/www/qr_debug_{camera_type}_{timestamp}.jpg"
                                try:
                                    with open(debug_path, 'wb') as f:
                                        f.write(data)
                                    logger.info(f"💾 Debug snapshot saved: {debug_path}")
                                    capture_snapshot_from_camera.last_debug_path = debug_path
                                except Exception as e:
                                    logger.error(f"Failed to save debug snapshot: {e}")
                        
                        return data
                    else:
                        logger.warning(f"Snapshot too small: {len(data)} bytes from {endpoint}")
                else:
                    logger.warning(f"HTTP {response.status_code} from {endpoint}")
            except Exception as e:
                logger.debug(f"Failed to connect to {endpoint}: {e}")
                continue
        
        logger.warning(f"❌ All snapshot attempts failed for {camera_ip}")
        return None
        
    except Exception as e:
        logger.error(f"Failed to capture snapshot: {e}")
        return None

def get_camera_entity_id(camera_ip: str) -> str:
    """Получить entity_id камеры по IP"""
    cam_config = get_camera_config(camera_ip)
    if cam_config:
        name = cam_config.get('name', '').lower().replace(' ', '_')
        return f"camera.{name}"
    return f"camera.openipc_{camera_ip.replace('.', '_')}"

def scan_qr_from_image(image_bytes: bytes) -> Optional[Dict]:
    """Сканировать QR код на изображении"""
    try:
        import cv2
        import numpy as np
        from pyzbar.pyzbar import decode
        
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            logger.error("Failed to decode image")
            return None
        
        height, width = img.shape[:2]
        logger.debug(f"Image size: {width}x{height}")
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        barcodes = decode(gray)
        
        if barcodes:
            barcode = barcodes[0]
            qr_data = barcode.data.decode('utf-8')
            qr_type = barcode.type
            
            logger.info(f"✅ QR Code found: {qr_data}")
            
            if hasattr(capture_snapshot_from_camera, "last_debug_path"):
                try:
                    points = barcode.polygon
                    if len(points) == 4:
                        pts = np.array([(p.x, p.y) for p in points], np.int32)
                        pts = pts.reshape((-1, 1, 2))
                        cv2.polylines(img, [pts], True, (0, 255, 0), 3)
                        
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        marked_path = f"/config/www/qr_marked_{timestamp}.jpg"
                        cv2.imwrite(marked_path, img)
                        logger.info(f"💾 Marked image saved: {marked_path}")
                except Exception as e:
                    logger.error(f"Failed to draw rectangle: {e}")
            
            return {
                "data": qr_data,
                "type": qr_type,
                "rect": {
                    "left": barcode.rect.left,
                    "top": barcode.rect.top,
                    "width": barcode.rect.width,
                    "height": barcode.rect.height
                }
            }
        else:
            logger.debug("No QR codes found in image")
            return None
            
    except Exception as e:
        logger.error(f"QR scan error: {e}")
        return None

def send_event_to_ha(event_type: str, event_data: dict):
    """Отправить событие в Home Assistant"""
    try:
        headers = {
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        }
        
        url = f"{HASS_URL}/api/events/{event_type}"
        logger.info(f"📤 Sending event {event_type} to HA")
        
        response = requests.post(url, headers=headers, json=event_data, timeout=2)
        
        if response.status_code == 200:
            logger.info(f"✅ Event {event_type} sent to HA")
        else:
            logger.warning(f"Failed to send event: HTTP {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending event: {e}")

def continuous_scan(scan_id: str, camera_id: str, expected_code: str, timeout: int):
    """Непрерывное сканирование QR в фоновом потоке"""
    logger.info(f"🔄 Starting continuous scan {scan_id} for {camera_id}")
    
    start_time = time.time()
    scan_count = 0
    failed_attempts = 0
    
    while time.time() - start_time < timeout:
        scan_count += 1
        elapsed = int(time.time() - start_time)
        remaining = timeout - elapsed
        
        logger.info(f"📸 Scan #{scan_count} - {remaining}s remaining")
        
        try:
            snapshot = capture_snapshot_from_camera(camera_id)
            
            if snapshot:
                failed_attempts = 0
                qr_result = scan_qr_from_image(snapshot)
                
                if qr_result:
                    qr_data = qr_result.get('data', '')
                    
                    logger.info(f"🎯🎯🎯 QR CODE DETECTED: {qr_data}")
                    write_qr_debug(f"🎯 QR CODE DETECTED: {qr_data}")
                    
                    event_data = {
                        "camera": get_camera_entity_id(camera_id),
                        "data": qr_data,
                        "type": qr_result.get('type', 'QRCODE'),
                        "scan_id": scan_id,
                        "expected_code": expected_code,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    send_event_to_ha("openipc_qr_detected", event_data)
                    
                    scan_jobs[scan_id].update({
                        "status": "completed",
                        "end_time": time.time(),
                        "result": qr_result,
                        "scan_count": scan_count
                    })
                    
                    logger.info(f"✅ Scan {scan_id} completed - code detected")
                    return
                else:
                    logger.debug("No QR code in this frame")
            else:
                failed_attempts += 1
                logger.warning(f"Failed to capture snapshot (attempt {failed_attempts})")
                
                if failed_attempts > 5:
                    logger.error(f"Camera {camera_id} seems unavailable - too many failed attempts")
                    break
            
            scan_jobs[scan_id].update({
                "scan_count": scan_count,
                "last_scan": time.time(),
                "status": "running"
            })
            
        except Exception as e:
            logger.error(f"Error in scan {scan_id}: {e}")
            write_qr_debug(f"❌ Error in scan: {e}")
        
        time.sleep(2)
    
    camera_entity = get_camera_entity_id(camera_id)
    scan_jobs[scan_id].update({
        "status": "timeout",
        "end_time": time.time(),
        "result": None,
        "scan_count": scan_count
    })
    
    event_data = {
        "camera": camera_entity,
        "scan_id": scan_id,
        "expected_code": expected_code,
        "timeout": timeout,
        "timestamp": datetime.now().isoformat()
    }
    send_event_to_ha("openipc_qr_timeout", event_data)
    
    logger.info(f"⏱️ Scan {scan_id} timed out after {timeout}s")
    write_qr_debug(f"⏱️ Scan timed out")

@app.route('/api/start_scan', methods=['POST'])
def start_scan():
    """Запуск непрерывного сканирования QR для камеры"""
    state["requests"] += 1
    data = request.json
    
    camera_id = data.get('camera_id')
    expected_code = data.get('expected_code', 'a4625vol')
    timeout = data.get('timeout', 300)
    
    cam_config = get_camera_config(camera_id)
    if not cam_config:
        logger.warning(f"⚠️ No configuration found for camera {camera_id}, using defaults")
    
    logger.info(f"🎯 Starting continuous scan for {camera_id}")
    logger.info(f"🎯 Expected code: {expected_code}")
    write_qr_debug(f"🎯 Starting continuous scan for {camera_id} with expected code: {expected_code}")
    
    scan_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    
    scan_jobs[scan_id] = {
        "scan_id": scan_id,
        "camera_id": camera_id,
        "expected_code": expected_code,
        "timeout": timeout,
        "start_time": time.time(),
        "status": "starting",
        "result": None,
        "scan_count": 0
    }
    
    thread = threading.Thread(
        target=continuous_scan,
        args=(scan_id, camera_id, expected_code, timeout)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({
        "success": True,
        "scan_id": scan_id,
        "message": f"Scan started for {camera_id}"
    })

@app.route('/api/scan_status/<scan_id>', methods=['GET'])
def scan_status(scan_id):
    """Получить статус сканирования"""
    state["requests"] += 1
    
    if scan_id in scan_jobs:
        return jsonify({
            "success": True,
            "scan": scan_jobs[scan_id]
        })
    
    return jsonify({
        "success": False,
        "error": "Scan not found"
    }), 404

@app.route('/api/stop_scan/<scan_id>', methods=['POST'])
def stop_scan(scan_id):
    """Остановить сканирование"""
    state["requests"] += 1
    
    if scan_id in scan_jobs:
        scan_jobs[scan_id].update({
            "status": "stopped",
            "end_time": time.time()
        })
        return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Scan not found"}), 404

@app.route('/api/barcode', methods=['POST'])
def barcode():
    """Распознавание штрих-кода с диагностикой"""
    state["requests"] += 1
    qr_stats["total_requests"] += 1
    
    data = request.json
    
    if not data:
        return jsonify({"success": False, "error": "No JSON data"}), 400
    
    image_data = data.get('image', '')
    camera_id = data.get('camera_id', 'unknown')
    
    if not image_data:
        qr_stats["failed_scans"] += 1
        return jsonify({"success": False, "error": "No image data"}), 400
    
    start_time = time.time()
    
    try:
        import cv2
        import numpy as np
        from pyzbar.pyzbar import decode
        
        try:
            img_bytes = base64.b64decode(image_data)
            logger.info(f"Decoded {len(img_bytes)} bytes")
        except Exception as e:
            qr_stats["failed_scans"] += 1
            return jsonify({"success": False, "error": f"Base64 decode failed: {e}"}), 400
        
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            qr_stats["failed_scans"] += 1
            return jsonify({"success": False, "error": "Failed to decode image"}), 400
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        barcodes = decode(gray)
        
        process_time = time.time() - start_time
        
        if barcodes:
            qr_stats["successful_scans"] += 1
            qr_stats["last_scan_time"] = datetime.now().isoformat()
            
            results = []
            for barcode in barcodes:
                barcode_data = barcode.data.decode('utf-8')
                barcode_type = barcode.type
                
                qr_stats["total_codes_found"] += 1
                qr_stats["by_type"][barcode_type] = qr_stats["by_type"].get(barcode_type, 0) + 1
                
                if camera_id not in qr_stats["by_camera"]:
                    qr_stats["by_camera"][camera_id] = {"scans": 0, "codes": 0}
                qr_stats["by_camera"][camera_id]["codes"] += 1
                
                qr_stats["last_code"] = barcode_data
                
                results.append({
                    "data": barcode_data,
                    "type": barcode_type,
                    "rect": {
                        "left": barcode.rect.left,
                        "top": barcode.rect.top,
                        "width": barcode.rect.width,
                        "height": barcode.rect.height
                    }
                })
            
            if camera_id not in qr_stats["by_camera"]:
                qr_stats["by_camera"][camera_id] = {"scans": 0, "codes": 0}
            qr_stats["by_camera"][camera_id]["scans"] += 1
            
            logger.info(f"✅ Found {len(results)} barcodes in {process_time:.2f}s")
            
            return jsonify({
                "success": True,
                "barcodes": results,
                "stats": {
                    "process_time_ms": int(process_time * 1000),
                    "codes_found": len(results)
                }
            })
        else:
            qr_stats["failed_scans"] += 1
            
            if camera_id not in qr_stats["by_camera"]:
                qr_stats["by_camera"][camera_id] = {"scans": 0, "codes": 0}
            qr_stats["by_camera"][camera_id]["scans"] += 1
            
            logger.debug(f"No barcodes found in {process_time:.2f}s")
            
            return jsonify({
                "success": True,
                "barcodes": [],
                "stats": {
                    "process_time_ms": int(process_time * 1000),
                    "codes_found": 0
                }
            })
        
    except Exception as e:
        qr_stats["failed_scans"] += 1
        logger.error(f"Barcode error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/camera/<path:camera_id>/barcode', methods=['POST'])
def camera_barcode(camera_id):
    """Endpoint для QR сканирования конкретной камеры"""
    logger.info(f"Camera barcode endpoint called for: {camera_id}")
    data = request.json or {}
    data['camera_id'] = camera_id
    return barcode()

# ==================== TTS API (С ПОДДЕРЖКОЙ РАЗНЫХ ПРОВАЙДЕРОВ) ====================

@app.route('/api/tts', methods=['POST'])
def tts():
    state["requests"] += 1
    data = request.json
    
    camera_id = data.get('camera_id')
    text = data.get('text', '')
    lang = data.get('lang', 'ru')
    provider = data.get('provider', config['tts']['provider'])
    
    logger.info(f"TTS request: camera={camera_id}, text={text}, provider={provider}")
    
    if not camera_id or not text:
        return jsonify({"success": False, "error": "Missing camera_id or text"}), 400
    
    # Получаем конфигурацию камеры
    cam_config = get_camera_config(camera_id)
    if not cam_config:
        cam_config = get_camera_config_by_name(camera_id)
    
    if cam_config:
        camera_ip = cam_config['ip']
        camera_type = cam_config['type']
        username = cam_config['username']
        password = cam_config['password']
        tts_format = cam_config.get('tts_format', 'pcm' if camera_type == 'openipc' else 'alaw')
        tts_endpoint = cam_config.get('tts_endpoint', '/cgi-bin/audio/transmit.cgi' if camera_type == 'beward' else '/play_audio')
    else:
        # Fallback на старую логику
        if camera_id == '192.168.1.10' or 'beward' in str(camera_id).lower():
            camera_type = 'beward'
            username = 'admin'
            password = 'Q96811621w'
            camera_ip = '192.168.1.10'
            tts_format = 'alaw'
            tts_endpoint = '/cgi-bin/audio/transmit.cgi'
        else:
            camera_type = 'openipc'
            username = 'root'
            password = '12345'
            ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', camera_id)
            camera_ip = ip_match.group(1) if ip_match else '192.168.1.4'
            tts_format = 'pcm'
            tts_endpoint = '/play_audio'
    
    camera_data = {
        "ip": camera_ip,
        "type": camera_type,
        "username": username,
        "password": password,
        "format": tts_format,
        "endpoint": tts_endpoint
    }
    
    if camera_type == 'beward' or tts_format == 'alaw':
        return _tts_for_beward(camera_data, text, lang)
    else:
        return _tts_for_openipc(camera_data, text, lang, provider)

@app.route('/api/camera/<path:camera_id>/tts', methods=['POST'])
def camera_tts(camera_id):
    logger.info(f"Camera TTS endpoint called: {camera_id}")
    data = request.json or {}
    data['camera_id'] = camera_id
    return tts()

def _tts_for_beward(camera, text, lang):
    logger.info(f"Beward TTS to {camera['ip']}")
    
    with tempfile.NamedTemporaryFile(suffix='.alaw', delete=False) as tmp:
        alaw_path = tmp.name
    
    try:
        if not os.path.exists(TTS_GENERATE_BEWARD_SCRIPT):
            logger.error(f"Beward script not found: {TTS_GENERATE_BEWARD_SCRIPT}")
            return jsonify({"success": False, "error": "Beward script not found"}), 500
        
        # Генерируем A-law файл
        cmd = ["bash", TTS_GENERATE_BEWARD_SCRIPT, text, lang, alaw_path]
        logger.debug(f"Running command: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"TTS generation failed: {result.stderr}")
            return jsonify({"success": False, "error": "TTS generation failed"}), 500
            
        if not os.path.exists(alaw_path):
            logger.error("TTS file not created")
            return jsonify({"success": False, "error": "TTS file not created"}), 500
        
        # Читаем аудио файл
        with open(alaw_path, 'rb') as f:
            audio_data = f.read()
        
        logger.info(f"Generated {len(audio_data)} bytes of A-law audio")
        
        # Сохраняем копию для отладки
        if debug_counter % 5 == 0:
            debug_audio_path = f"/config/www/tts_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.alaw"
            try:
                shutil.copy2(alaw_path, debug_audio_path)
                logger.info(f"💾 Debug audio saved to {debug_audio_path}")
            except Exception as e:
                logger.error(f"Failed to save debug audio: {e}")
        
        # Формируем правильные заголовки как в документации Beward
        endpoint = camera.get('endpoint', '/cgi-bin/audio/transmit.cgi')
        url = f"http://{camera['ip']}{endpoint}"
        
        # Создаем базовую аутентификацию
        auth_str = base64.b64encode(f"{camera['username']}:{camera['password']}".encode()).decode()
        
        headers = {
            "Content-Type": "audio/basic",
            "Content-Length": str(len(audio_data)),
            "Connection": "Keep-Alive",
            "Cache-Control": "no-cache",
            "Authorization": f"Basic {auth_str}"
        }
        
        logger.debug(f"Sending to {url}")
        logger.debug(f"Headers: {headers}")
        
        # Отправляем POST запрос
        response = requests.post(url, headers=headers, data=audio_data, timeout=10)
        
        logger.info(f"Response status: {response.status_code}")
        logger.debug(f"Response headers: {response.headers}")
        
        if response.status_code == 200:
            logger.info(f"✅ TTS sent successfully to Beward")
            return jsonify({"success": True})
        else:
            logger.error(f"❌ TTS failed: HTTP {response.status_code}")
            try:
                error_text = response.text
                logger.error(f"Response body: {error_text[:200]}")
            except:
                pass
            return jsonify({"success": False, "error": f"HTTP {response.status_code}"}), 500
            
    except subprocess.TimeoutExpired:
        logger.error("TTS generation timeout")
        return jsonify({"success": False, "error": "TTS generation timeout"}), 500
    except Exception as e:
        logger.error(f"TTS error: {e}")
        logger.exception(e)
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        # Очищаем временный файл
        if os.path.exists(alaw_path):
            try:
                os.unlink(alaw_path)
            except:
                pass

def _tts_for_openipc(camera, text, lang, provider='google'):
    logger.info(f"OpenIPC TTS to {camera['ip']} with provider {provider}")
    
    with tempfile.NamedTemporaryFile(suffix='.pcm', delete=False) as tmp:
        pcm_path = tmp.name
    
    try:
        # Выбираем провайдера
        if provider == 'rhvoice':
            if not os.path.exists(TTS_GENERATE_RHVoice_SCRIPT):
                return jsonify({"success": False, "error": "RHVoice script not found"}), 500
            cmd = ["bash", TTS_GENERATE_RHVoice_SCRIPT, text, lang, pcm_path]
        
        elif provider == 'yandex':
            # Для Yandex нужно будет добавить отдельный скрипт
            return jsonify({"success": False, "error": "Yandex TTS not implemented yet"}), 500
        
        else:  # google по умолчанию
            if not os.path.exists(TTS_GENERATE_SCRIPT):
                return jsonify({"success": False, "error": "Google TTS script not found"}), 500
            cmd = ["bash", TTS_GENERATE_SCRIPT, text, lang, pcm_path]
        
        logger.debug(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"TTS generation failed: {result.stderr}")
            return jsonify({"success": False, "error": "TTS generation failed"}), 500
            
        if not os.path.exists(pcm_path):
            logger.error("TTS file not created")
            return jsonify({"success": False, "error": "TTS file not created"}), 500
        
        with open(pcm_path, 'rb') as f:
            audio_data = f.read()
        
        logger.info(f"Generated {len(audio_data)} bytes of PCM audio")
        
        # Сохраняем копию для отладки
        debug_audio_path = f"/config/www/tts_debug_{provider}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pcm"
        try:
            shutil.copy2(pcm_path, debug_audio_path)
            logger.info(f"💾 Debug audio saved to {debug_audio_path}")
        except Exception as e:
            logger.error(f"Failed to save debug audio: {e}")
        
        endpoint = camera.get('endpoint', '/play_audio')
        url = f"http://{camera['ip']}{endpoint}"
        auth = (camera['username'], camera['password'])
        
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(audio_data))
        }
        
        response = requests.post(url, headers=headers, data=audio_data, auth=auth, timeout=10)
        
        if response.status_code == 200:
            logger.info(f"✅ TTS sent successfully to OpenIPC")
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": f"HTTP {response.status_code}"}), 500
            
    finally:
        if os.path.exists(pcm_path):
            os.unlink(pcm_path)

# ==================== Запуск приложения ====================

if __name__ == '__main__':
    logger.info("="*60)
    logger.info("Starting OpenIPC Bridge with Web UI and RHVoice support")
    logger.info("="*60)
    
    # Загружаем конфигурацию
    load_config()
    
    # Очищаем debug файл при старте
    if config['logging'].get('debug_qr', True):
        try:
            with open(QR_DEBUG_FILE, 'w', encoding='utf-8') as f:
                f.write(f"QR Debug started at {datetime.now()}\n")
        except:
            pass
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)