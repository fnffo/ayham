# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import sqlite3
import logging
import threading
import subprocess
import shutil
import re
import hashlib
import secrets
import psutil
import signal
import requests
import tempfile
import atexit
import base64
import zipfile
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Union
from collections import defaultdict
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from io import BytesIO

import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ==================== إعدادات Flask ====================
from flask import Flask, jsonify
from threading import Thread

flask_app = Flask('')

@flask_app.route('/')
def home():
    return jsonify({
        'status': 'online',
        'bot': 'Python Hosting Bot',
        'version': '3.0',
        'uptime': datetime.now().isoformat()
    })

@flask_app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'processes': len(bot_data.get('active_processes', {})),
        'users': len(bot_data.get('users', {}))
    })

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ==================== إعدادات متقدمة ====================

class Config:
    """فئة الإعدادات المركزية"""
    
    # توكن البوت
    TOKEN = "8656750337:AAF2A-41L8hoRknEUc_lZIbpyYcnvWIRZFs"
    
    # المالك الوحيد (يمكنك تعديله)
    OWNER_ID = 8373644537  # ضع ايديك هنا
    
    # معلومات التواصل
    YOUR_USERNAME = "@fnffo"
    UPDATE_CHANNEL = "@threecode"
    
    # إعدادات المجلدات
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads')
    LOGS_DIR = os.path.join(BASE_DIR, 'logs')
    TEMP_DIR = os.path.join(BASE_DIR, 'temp')
    DATABASE_PATH = os.path.join(BASE_DIR, 'bot_data.db')
    REQUIREMENTS_DIR = os.path.join(BASE_DIR, 'requirements')
    
    # إعدادات النظام
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_LOG_SIZE = 100 * 1024  # 100KB
    MAX_MESSAGE_LENGTH = 4096
    PROCESS_TIMEOUT = 3600  # ساعة واحدة
    BATCH_SIZE = 25
    DELAY_BETWEEN_BATCHES = 1.5
    
    # حدود المستخدمين
    FREE_USER_LIMIT = 2
    VIP_USER_LIMIT = 20
    ADMIN_LIMIT = 100
    OWNER_LIMIT = float('inf')
    
    # إعدادات النقاط
    POINTS_PER_REFERRAL = 2
    POINTS_PER_FILE = 1
    POINTS_FOR_JOINING = 5
    
    # إعدادات VIP
    VIP_PRICES = {
        'week': 50,
        'month': 150,
        'year': 500
    }
    
    # الوحدات الممنوعة
    BLOCKED_MODULES = [
        'os.system', 'subprocess', 'eval', 'exec', 'compile',
        '__import__', 'globals', 'locals', 'socket',
        'ctypes', 'win32api', 'pyautogui', 'keyboard',
        'pynput', 'scapy', 'imp', 'importlib', '__builtins__'
    ]
    
    # أنماط خطيرة
    DANGEROUS_PATTERNS = [
        r'base64\.b64decode\(.*\)',
        r'exec\(.*\)',
        r'eval\(.*\)',
        r'__import__\(.*\)',
        r'compile\(.*\)',
        r'open\(.*,.*[wr]',
        r'requests\.get\(.*\)',
        r'urllib\.request',
        r'ftp://',
        r'rm\s+-rf',
        r'format\s+C:',
        r'del\s+C:',
        r'shutdown',
        r'reboot',
        r'chmod\s+777',
        r'base64_decode'
    ]

# إنشاء المجلدات
for dir_path in [Config.UPLOAD_DIR, Config.LOGS_DIR, Config.TEMP_DIR, Config.REQUIREMENTS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# ==================== إعداد التسجيل ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(Config.LOGS_DIR, 'bot.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== تهيئة البوت ====================

bot = telebot.TeleBot(Config.TOKEN)

# ==================== قفل قاعدة البيانات ====================

DB_LOCK = threading.RLock()

# ==================== هيكل البيانات الرئيسي ====================

class BotData:
    """إدارة بيانات البوت في الذاكرة"""
    
    def __init__(self):
        self.users = {}  # بيانات المستخدمين
        self.active_processes = {}  # العمليات النشطة
        self.user_files = defaultdict(list)  # ملفات المستخدمين
        self.user_points = defaultdict(int)  # نقاط المستخدمين
        self.user_referrals = defaultdict(list)  # إحصائيات الدعوات
        self.referral_codes = {}  # رموز الدعوة
        self.mandatory_channels = {}  # القنوات الإجبارية
        self.pending_approvals = {}  # الملفات المعلقة
        self.admin_ids = {Config.OWNER_ID}  # قائمة الأدمن
        self.bot_locked = False  # حالة القفل
        self.broadcast_status = {}  # حالة البث
        self.stats = {
            'total_uploads': 0,
            'total_users': 0,
            'total_processes': 0,
            'blocked_attempts': 0
        }

bot_data = BotData()

# ==================== دوال قاعدة البيانات ====================

def init_database():
    """تهيئة قاعدة البيانات"""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            
            # تفعيل الميزات
            c.execute('PRAGMA foreign_keys = ON')
            c.execute('PRAGMA journal_mode = WAL')
            c.execute('PRAGMA synchronous = NORMAL')
            
            # جدول المستخدمين
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                points INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,
                vip_expiry TEXT,
                is_banned INTEGER DEFAULT 0,
                join_date TEXT,
                last_active TEXT,
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                total_referred INTEGER DEFAULT 0
            )''')
            
            # جدول الإعدادات
            c.execute('''CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # جدول القنوات الإجبارية
            c.execute('''CREATE TABLE IF NOT EXISTS channels (
                channel_id TEXT PRIMARY KEY,
                channel_username TEXT,
                channel_name TEXT,
                added_by INTEGER,
                added_date TEXT
            )''')
            
            # جدول الملفات
            c.execute('''CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                file_name TEXT,
                file_path TEXT,
                file_size INTEGER,
                upload_date TEXT,
                status TEXT DEFAULT 'active',
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
            
            # جدول العمليات النشطة
            c.execute('''CREATE TABLE IF NOT EXISTS processes (
                process_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                file_name TEXT,
                pid INTEGER,
                start_time TEXT,
                status TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
            
            # جدول الدعوات
            c.execute('''CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                join_date TEXT,
                points_awarded INTEGER DEFAULT 1,
                UNIQUE(referred_id),
                FOREIGN KEY(referrer_id) REFERENCES users(user_id),
                FOREIGN KEY(referred_id) REFERENCES users(user_id)
            )''')
            
            # جدول المعاملات
            c.execute('''CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                description TEXT,
                timestamp TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )''')
            
            # الإعدادات الافتراضية
            default_settings = [
                ('welcome_message', '👋 أهلاً بك في بوت الاستضافة!'),
                ('protection_level', 'high'),
                ('bot_enabled', '1'),
                ('vip_enabled', '1'),
                ('force_subscription', '0'),
                ('points_per_file', str(Config.POINTS_PER_FILE)),
                ('points_per_referral', str(Config.POINTS_PER_REFERRAL)),
                ('new_user_notification', '1'),
                ('auto_approve_vip', '0'),
                ('max_file_size', str(Config.MAX_FILE_SIZE)),
                ('max_files_per_user', str(Config.FREE_USER_LIMIT)),
                ('backup_enabled', '1'),
                ('backup_interval', '24')  # ساعات
            ]
            
            c.executemany(
                'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)',
                default_settings
            )
            
            # إضافة المالك
            c.execute('''INSERT OR IGNORE INTO users 
                (user_id, username, first_name, points, is_vip, join_date, last_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (Config.OWNER_ID, 'owner', 'المالك', 999999, 1,
                 datetime.now().isoformat(), datetime.now().isoformat()))
            
            conn.commit()
            
            # تحميل البيانات
            load_from_db(c)
            
            conn.close()
            logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")
            
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة قاعدة البيانات: {e}", exc_info=True)
        raise

def load_from_db(cursor):
    """تحميل البيانات من قاعدة البيانات"""
    try:
        # تحميل المستخدمين
        cursor.execute('SELECT * FROM users')
        for row in cursor.fetchall():
            user_data = dict(row)
            bot_data.users[user_data['user_id']] = user_data
            bot_data.user_points[user_data['user_id']] = user_data['points']
            
            if user_data['referral_code']:
                bot_data.referral_codes[user_data['referral_code']] = user_data['user_id']
        
        # تحميل القنوات
        cursor.execute('SELECT * FROM channels')
        for row in cursor.fetchall():
            channel = dict(row)
            bot_data.mandatory_channels[channel['channel_id']] = channel
        
        # تحميل الملفات
        cursor.execute('SELECT * FROM files WHERE status = "active"')
        for row in cursor.fetchall():
            file_data = dict(row)
            bot_data.user_files[file_data['user_id']].append(file_data)
        
        # تحميل الدعوات
        cursor.execute('SELECT referrer_id, referred_id FROM referrals')
        for row in cursor.fetchall():
            bot_data.user_referrals[row['referrer_id']].append(row['referred_id'])
        
        # تحميل الإحصائيات
        cursor.execute('SELECT COUNT(*) as count FROM users')
        bot_data.stats['total_users'] = cursor.fetchone()['count']
        
        cursor.execute('SELECT COUNT(*) as count FROM files')
        bot_data.stats['total_uploads'] = cursor.fetchone()['count']
        
        logger.info(f"✅ تم تحميل {len(bot_data.users)} مستخدم, "
                   f"{len(bot_data.user_files)} ملف, "
                   f"{len(bot_data.mandatory_channels)} قناة")
        
    except Exception as e:
        logger.error(f"❌ خطأ في تحميل البيانات: {e}")

# تهيئة قاعدة البيانات
init_database()

# ==================== دوال المساعدة العامة ====================

def get_setting(key, default=None):
    """الحصول على إعداد"""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('SELECT value FROM settings WHERE key = ?', (key,))
            result = c.fetchone()
            conn.close()
            return result[0] if result else default
    except:
        return default

def update_setting(key, value):
    """تحديث إعداد"""
    try:
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)',
                     (key, str(value)))
            conn.commit()
            conn.close()
            return True
    except:
        return False

def get_user(user_id):
    """الحصول على بيانات مستخدم"""
    return bot_data.users.get(user_id)

def update_user_activity(user_id):
    """تحديث آخر نشاط للمستخدم"""
    if user_id in bot_data.users:
        bot_data.users[user_id]['last_active'] = datetime.now().isoformat()
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET last_active = ? WHERE user_id = ?',
                     (datetime.now().isoformat(), user_id))
            conn.commit()
            conn.close()

def is_admin(user_id):
    """التحقق من الأدمن"""
    return user_id in bot_data.admin_ids or user_id == Config.OWNER_ID

def is_banned(user_id):
    """التحقق من الحظر"""
    user = get_user(user_id)
    return user and user.get('is_banned', 0) == 1

def is_vip(user_id):
    """التحقق من VIP"""
    if user_id == Config.OWNER_ID or is_admin(user_id):
        return True
        
    user = get_user(user_id)
    if not user or not user.get('is_vip'):
        return False
        
    if user.get('vip_expiry'):
        expiry = datetime.fromisoformat(user['vip_expiry'])
        if expiry < datetime.now():
            # انتهت صلاحية VIP
            with DB_LOCK:
                conn = sqlite3.connect(Config.DATABASE_PATH)
                c = conn.cursor()
                c.execute('UPDATE users SET is_vip = 0, vip_expiry = NULL WHERE user_id = ?',
                         (user_id,))
                conn.commit()
                conn.close()
            
            if user_id in bot_data.users:
                bot_data.users[user_id]['is_vip'] = 0
                bot_data.users[user_id]['vip_expiry'] = None
            
            return False
    
    return True

def get_user_limit(user_id):
    """الحصول على حد رفع الملفات"""
    if user_id == Config.OWNER_ID:
        return Config.OWNER_LIMIT
    if is_admin(user_id):
        return Config.ADMIN_LIMIT
    if is_vip(user_id):
        return Config.VIP_USER_LIMIT
    return Config.FREE_USER_LIMIT

def get_user_files_count(user_id):
    """عدد ملفات المستخدم"""
    return len(bot_data.user_files.get(user_id, []))

def can_upload(user_id):
    """التحقق من إمكانية الرفع"""
    if is_banned(user_id):
        return False, "🚫 أنت محظور"
    
    if bot_data.bot_locked and not is_admin(user_id):
        return False, "🔒 البوت في وضع الصيانة"
    
    current = get_user_files_count(user_id)
    limit = get_user_limit(user_id)
    
    if current >= limit:
        limit_str = "∞" if limit == float('inf') else str(limit)
        return False, f"⚠️ وصلت للحد الأقصى ({current}/{limit_str})"
    
    return True, "✅ يمكنك الرفع"

# ==================== نظام النقاط والدعوات ====================

class PointsSystem:
    """نظام النقاط المتقدم"""
    
    @staticmethod
    def generate_referral_code(user_id):
        """إنشاء رمز دعوة"""
        unique = f"{user_id}_{datetime.now().timestamp()}_{secrets.token_hex(4)}"
        code = hashlib.md5(unique.encode()).hexdigest()[:8].upper()
        
        bot_data.referral_codes[code] = user_id
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('UPDATE users SET referral_code = ? WHERE user_id = ?',
                     (code, user_id))
            conn.commit()
            conn.close()
        
        return code
    
    @staticmethod
    def get_user_points(user_id):
        """الحصول على نقاط المستخدم"""
        return bot_data.user_points.get(user_id, 0)
    
    @staticmethod
    def add_points(user_id, amount, description=""):
        """إضافة نقاط"""
        current = PointsSystem.get_user_points(user_id)
        new_total = current + amount
        
        bot_data.user_points[user_id] = new_total
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            
            # تحديث النقاط
            c.execute('UPDATE users SET points = ? WHERE user_id = ?',
                     (new_total, user_id))
            
            # تسجيل المعاملة
            c.execute('''INSERT INTO transactions 
                (user_id, amount, type, description, timestamp)
                VALUES (?, ?, ?, ?, ?)''',
                (user_id, amount, 'add', description, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
        
        logger.info(f"💰 تمت إضافة {amount} نقطة للمستخدم {user_id} - {description}")
        return new_total
    
    @staticmethod
    def deduct_points(user_id, amount, description=""):
        """خصم نقاط"""
        current = PointsSystem.get_user_points(user_id)
        
        if current < amount:
            return False, current
        
        new_total = current - amount
        bot_data.user_points[user_id] = new_total
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            
            c.execute('UPDATE users SET points = ? WHERE user_id = ?',
                     (new_total, user_id))
            
            c.execute('''INSERT INTO transactions 
                (user_id, amount, type, description, timestamp)
                VALUES (?, ?, ?, ?, ?)''',
                (user_id, -amount, 'deduct', description, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
        
        logger.info(f"💰 تم خصم {amount} نقطة من المستخدم {user_id} - {description}")
        return True, new_total
    
    @staticmethod
    def get_referral_link(user_id):
        """الحصول على رابط الدعوة"""
        user = get_user(user_id)
        
        if not user:
            return None
        
        if not user.get('referral_code'):
            code = PointsSystem.generate_referral_code(user_id)
        else:
            code = user['referral_code']
        
        bot_username = bot.get_me().username
        return f"https://t.me/{bot_username}?start=ref_{code}"
    
    @staticmethod
    def process_referral(referee_id, code):
        """معالجة الدعوة"""
        referrer_id = bot_data.referral_codes.get(code)
        
        if not referrer_id or referrer_id == referee_id:
            return None
        
        # التحقق من عدم التكرار
        if referee_id in bot_data.user_referrals.get(referrer_id, []):
            return None
        
        # تسجيل الدعوة
        bot_data.user_referrals.setdefault(referrer_id, []).append(referee_id)
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            
            c.execute('''INSERT INTO referrals 
                (referrer_id, referred_id, join_date, points_awarded)
                VALUES (?, ?, ?, ?)''',
                (referrer_id, referee_id, datetime.now().isoformat(), 1))
            
            c.execute('UPDATE users SET total_referred = total_referred + 1 WHERE user_id = ?',
                     (referrer_id,))
            
            conn.commit()
            conn.close()
        
        # منح النقاط
        points = int(get_setting('points_per_referral', Config.POINTS_PER_REFERRAL))
        PointsSystem.add_points(referrer_id, points, f"دعوة المستخدم {referee_id}")
        PointsSystem.add_points(referee_id, points, "انضمام عن طريق دعوة")
        
        return referrer_id
    
    @staticmethod
    def get_transactions(user_id, limit=10):
        """الحصول على آخر المعاملات"""
        try:
            with DB_LOCK:
                conn = sqlite3.connect(Config.DATABASE_PATH)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute('''SELECT * FROM transactions 
                    WHERE user_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT ?''', (user_id, limit))
                results = [dict(row) for row in c.fetchall()]
                conn.close()
                return results
        except:
            return []

# ==================== نظام الأمان المتقدم ====================

class SecurityManager:
    """إدارة الأمان والحماية"""
    
    @staticmethod
    def scan_file(file_path):
        """فحص الملف بالكامل"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            results = {
                'safe': True,
                'warnings': [],
                'dangerous': [],
                'score': 100
            }
            
            # فحص الوحدات الممنوعة
            for module in Config.BLOCKED_MODULES:
                if module in content:
                    results['dangerous'].append(f"استخدام {module}")
                    results['safe'] = False
                    results['score'] -= 20
            
            # فحص الأنماط الخطيرة
            for pattern in Config.DANGEROUS_PATTERNS:
                if re.search(pattern, content, re.IGNORECASE):
                    results['warnings'].append(f"نمط مشبوه: {pattern}")
                    results['score'] -= 10
            
            # فحص الـ Base64 المشبوه
            base64_pattern = r'base64\.(b64decode|decode)\s*\(\s*["\']([^"\']+)["\']\s*\)'
            for match in re.finditer(base64_pattern, content):
                try:
                    encoded = match.group(2)
                    decoded = base64.b64decode(encoded).decode('utf-8', errors='ignore')
                    if any(word in decoded for word in ['exec', 'eval', 'system']):
                        results['dangerous'].append("كود مشفر ضار")
                        results['safe'] = False
                        results['score'] -= 30
                except:
                    pass
            
            # فحص الروابط الخارجية
            url_pattern = r'https?://[^\s"\'<>]+'
            urls = re.findall(url_pattern, content)
            suspicious_urls = [url for url in urls if 'telegram.org' not in url and 't.me' not in url]
            if suspicious_urls:
                results['warnings'].append(f"روابط خارجية: {len(suspicious_urls)}")
                results['score'] -= 5 * len(suspicious_urls)
            
            return results
            
        except Exception as e:
            logger.error(f"خطأ في فحص الملف: {e}")
            return {'safe': False, 'error': str(e), 'score': 0}
    
    @staticmethod
    def check_file_size(file_size):
        """فحص حجم الملف"""
        max_size = int(get_setting('max_file_size', Config.MAX_FILE_SIZE))
        return file_size <= max_size, max_size
    
    @staticmethod
    def check_file_type(filename):
        """فحص نوع الملف"""
        allowed = ['.py', '.txt', '.json', '.md']
        ext = os.path.splitext(filename)[1].lower()
        return ext in allowed, allowed
    
    @staticmethod
    def quarantine_file(file_path, reason):
        """عزل ملف ضار"""
        quarantine_dir = os.path.join(Config.BASE_DIR, 'quarantine')
        os.makedirs(quarantine_dir, exist_ok=True)
        
        filename = os.path.basename(file_path)
        new_path = os.path.join(quarantine_dir, f"{int(time.time())}_{filename}")
        
        shutil.move(file_path, new_path)
        
        # تسجيل الحادثة
        with open(os.path.join(quarantine_dir, 'log.txt'), 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat()} - {filename} - {reason}\n")
        
        bot_data.stats['blocked_attempts'] += 1
        
        return new_path

# ==================== نظام الملفات ====================

class FileManager:
    """إدارة ملفات المستخدمين"""
    
    @staticmethod
    def get_user_dir(user_id, create=True):
        """الحصول على مجلد المستخدم"""
        user_dir = os.path.join(Config.UPLOAD_DIR, str(user_id))
        if create and not os.path.exists(user_dir):
            os.makedirs(user_dir, exist_ok=True)
        return user_dir
    
    @staticmethod
    def save_file(user_id, file_data, filename):
        """حفظ ملف المستخدم"""
        user_dir = FileManager.get_user_dir(user_id)
        file_path = os.path.join(user_dir, filename)
        
        # حفظ الملف
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        # تسجيل الملف في قاعدة البيانات
        file_size = len(file_data)
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('''INSERT INTO files 
                (user_id, file_name, file_path, file_size, upload_date)
                VALUES (?, ?, ?, ?, ?)''',
                (user_id, filename, file_path, file_size, datetime.now().isoformat()))
            file_id = c.lastrowid
            conn.commit()
            conn.close()
        
        # تحديث الذاكرة
        file_record = {
            'id': file_id,
            'user_id': user_id,
            'file_name': filename,
            'file_path': file_path,
            'file_size': file_size,
            'upload_date': datetime.now().isoformat(),
            'status': 'active'
        }
        
        bot_data.user_files[user_id].append(file_record)
        bot_data.stats['total_uploads'] += 1
        
        return file_path, file_record
    
    @staticmethod
    def get_user_files(user_id):
        """الحصول على ملفات المستخدم"""
        return bot_data.user_files.get(user_id, [])
    
    @staticmethod
    def get_file(user_id, filename):
        """الحصول على ملف محدد"""
        files = FileManager.get_user_files(user_id)
        for file in files:
            if file['file_name'] == filename and file['status'] == 'active':
                return file
        return None
    
    @staticmethod
    def delete_file(user_id, filename):
        """حذف ملف"""
        file_record = FileManager.get_file(user_id, filename)
        
        if not file_record:
            return False, "الملف غير موجود"
        
        # حذف من القرص
        try:
            if os.path.exists(file_record['file_path']):
                os.remove(file_record['file_path'])
        except:
            pass
        
        # تحديث قاعدة البيانات
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('UPDATE files SET status = "deleted" WHERE id = ?',
                     (file_record['id'],))
            conn.commit()
            conn.close()
        
        # تحديث الذاكرة
        bot_data.user_files[user_id] = [
            f for f in bot_data.user_files[user_id] 
            if f['id'] != file_record['id']
        ]
        
        return True, "تم الحذف"
    
    @staticmethod
    def delete_all_user_files(user_id):
        """حذف جميع ملفات المستخدم"""
        files = FileManager.get_user_files(user_id)
        deleted = 0
        
        for file in files:
            try:
                if os.path.exists(file['file_path']):
                    os.remove(file['file_path'])
                deleted += 1
            except:
                pass
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('UPDATE files SET status = "deleted" WHERE user_id = ? AND status = "active"',
                     (user_id,))
            conn.commit()
            conn.close()
        
        bot_data.user_files[user_id] = []
        
        return deleted

# ==================== نظام تشغيل السكريبتات ====================

class ScriptRunner:
    """تشغيل وإدارة السكريبتات"""
    
    @staticmethod
    def is_running(user_id, filename):
        """التحقق من تشغيل سكريبت"""
        process_key = f"{user_id}_{filename}"
        process_info = bot_data.active_processes.get(process_key)
        
        if not process_info:
            return False
        
        try:
            proc = psutil.Process(process_info['pid'])
            running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            
            if not running:
                ScriptRunner.cleanup_process(process_key)
                return False
            
            return True
            
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            ScriptRunner.cleanup_process(process_key)
            return False
    
    @staticmethod
    def cleanup_process(process_key):
        """تنظيف العملية"""
        process_info = bot_data.active_processes.pop(process_key, None)
        if process_info and 'log_file' in process_info:
            try:
                process_info['log_file'].close()
            except:
                pass
    
    @staticmethod
    def kill_process(process_info):
        """قتل العملية وجميع أطفالها"""
        try:
            if 'log_file' in process_info:
                try:
                    process_info['log_file'].close()
                except:
                    pass
            
            if 'pid' not in process_info:
                return
            
            try:
                parent = psutil.Process(process_info['pid'])
                
                # قتل الأطفال
                for child in parent.children(recursive=True):
                    try:
                        child.terminate()
                    except:
                        try:
                            child.kill()
                        except:
                            pass
                
                # قتل الأب
                try:
                    parent.terminate()
                    parent.wait(timeout=2)
                except:
                    parent.kill()
                    
            except psutil.NoSuchProcess:
                pass
                
        except Exception as e:
            logger.error(f"خطأ في قتل العملية: {e}")
    
    @staticmethod
    def get_logs(user_id, filename, lines=100):
        """الحصول على سجلات التشغيل"""
        user_dir = FileManager.get_user_dir(user_id, create=False)
        log_path = os.path.join(user_dir, f"{os.path.splitext(filename)[0]}.log")
        
        if not os.path.exists(log_path):
            return "لا توجد سجلات بعد"
        
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # أخذ آخر lines سطر
            all_lines = content.split('\n')
            last_lines = all_lines[-lines:]
            
            return '\n'.join(last_lines)
            
        except Exception as e:
            return f"خطأ في قراءة السجلات: {e}"
    
    @staticmethod
    def install_requirements(user_id, filename):
        """تثبيت متطلبات الملف"""
        user_dir = FileManager.get_user_dir(user_id, create=False)
        req_path = os.path.join(user_dir, 'requirements.txt')
        
        if not os.path.exists(req_path):
            return True, "لا توجد متطلبات"
        
        try:
            with open(req_path, 'r') as f:
                requirements = f.read().splitlines()
            
            installed = []
            failed = []
            
            for req in requirements:
                if req.strip() and not req.startswith('#'):
                    try:
                        result = subprocess.run(
                            [sys.executable, '-m', 'pip', 'install', req],
                            capture_output=True,
                            text=True,
                            timeout=60
                        )
                        
                        if result.returncode == 0:
                            installed.append(req)
                        else:
                            failed.append(req)
                            
                    except subprocess.TimeoutExpired:
                        failed.append(f"{req} (مهلة)")
                    except Exception as e:
                        failed.append(f"{req} ({str(e)[:30]})")
            
            if failed:
                return False, f"نجح: {len(installed)}، فشل: {len(failed)}\n{', '.join(failed[:5])}"
            
            return True, f"تم تثبيت {len(installed)} مكتبة"
            
        except Exception as e:
            return False, f"خطأ: {e}"
    
    @staticmethod
    def run_script(user_id, filename, message):
        """تشغيل سكريبت"""
        # التحقق من الملف
        file_record = FileManager.get_file(user_id, filename)
        
        if not file_record:
            return False, "الملف غير موجود"
        
        if not os.path.exists(file_record['file_path']):
            return False, "الملف غير موجود على القرص"
        
        # التحقق من التشغيل المسبق
        if ScriptRunner.is_running(user_id, filename):
            return False, "الملف يعمل بالفعل"
        
        process_key = f"{user_id}_{filename}"
        user_dir = FileManager.get_user_dir(user_id, create=False)
        log_path = os.path.join(user_dir, f"{os.path.splitext(filename)[0]}.log")
        
        try:
            # فتح ملف السجل
            log_file = open(log_path, 'w', encoding='utf-8', errors='ignore')
            
            # تشغيل العملية
            process = subprocess.Popen(
                [sys.executable, file_record['file_path']],
                cwd=user_dir,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.PIPE,
                start_new_session=True
            )
            
            # تسجيل العملية
            process_info = {
                'pid': process.pid,
                'process': process,
                'log_file': log_file,
                'user_id': user_id,
                'filename': filename,
                'start_time': datetime.now(),
                'process_key': process_key
            }
            
            bot_data.active_processes[process_key] = process_info
            bot_data.stats['total_processes'] += 1
            
            # تسجيل في قاعدة البيانات
            with DB_LOCK:
                conn = sqlite3.connect(Config.DATABASE_PATH)
                c = conn.cursor()
                c.execute('''INSERT INTO processes 
                    (process_id, user_id, file_name, pid, start_time, status)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (process_key, user_id, filename, process.pid, 
                     datetime.now().isoformat(), 'running'))
                conn.commit()
                conn.close()
            
            logger.info(f"🚀 تم تشغيل {filename} للمستخدم {user_id} (PID: {process.pid})")
            
            # إشعار المستخدم
            bot.send_message(
                message.chat.id,
                f"✅ تم تشغيل `{filename}`\n🆔 PID: `{process.pid}`",
                parse_mode='Markdown'
            )
            
            return True, f"تم التشغيل (PID: {process.pid})"
            
        except Exception as e:
            logger.error(f"خطأ في تشغيل {filename}: {e}")
            return False, f"خطأ: {e}"
    
    @staticmethod
    def stop_script(user_id, filename):
        """إيقاف سكريبت"""
        process_key = f"{user_id}_{filename}"
        
        if not ScriptRunner.is_running(user_id, filename):
            return False, "الملف غير قيد التشغيل"
        
        process_info = bot_data.active_processes.get(process_key)
        
        if process_info:
            ScriptRunner.kill_process(process_info)
            ScriptRunner.cleanup_process(process_key)
            
            # تحديث قاعدة البيانات
            with DB_LOCK:
                conn = sqlite3.connect(Config.DATABASE_PATH)
                c = conn.cursor()
                c.execute('UPDATE processes SET status = "stopped" WHERE process_id = ?',
                         (process_key,))
                conn.commit()
                conn.close()
            
            logger.info(f"🛑 تم إيقاف {filename} للمستخدم {user_id}")
            
            return True, "تم الإيقاف"
        
        return False, "خطأ في الإيقاف"
    
    @staticmethod
    def stop_all_user_scripts(user_id):
        """إيقاف جميع سكريبتات المستخدم"""
        stopped = 0
        
        for process_key, process_info in list(bot_data.active_processes.items()):
            if process_info['user_id'] == user_id:
                ScriptRunner.kill_process(process_info)
                ScriptRunner.cleanup_process(process_key)
                stopped += 1
        
        if stopped > 0:
            with DB_LOCK:
                conn = sqlite3.connect(Config.DATABASE_PATH)
                c = conn.cursor()
                c.execute('UPDATE processes SET status = "stopped" WHERE user_id = ?',
                         (user_id,))
                conn.commit()
                conn.close()
        
        return stopped

# ==================== نظام القنوات الإجبارية ====================

class ChannelManager:
    """إدارة القنوات الإجبارية"""
    
    @staticmethod
    def check_membership(user_id):
        """التحقق من عضوية المستخدم في جميع القنوات"""
        if not bot_data.mandatory_channels or is_admin(user_id):
            return True, []
        
        not_joined = []
        
        for channel_id, info in bot_data.mandatory_channels.items():
            try:
                member = bot.get_chat_member(channel_id, user_id)
                if member.status in ['left', 'kicked']:
                    not_joined.append(info)
            except Exception as e:
                logger.error(f"خطأ في التحقق من القناة {channel_id}: {e}")
                not_joined.append(info)
        
        return len(not_joined) == 0, not_joined
    
    @staticmethod
    def add_channel(channel_id, username, name, added_by):
        """إضافة قناة إجبارية"""
        channel_data = {
            'channel_id': channel_id,
            'channel_username': username,
            'channel_name': name,
            'added_by': added_by,
            'added_date': datetime.now().isoformat()
        }
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO channels 
                (channel_id, channel_username, channel_name, added_by, added_date)
                VALUES (?, ?, ?, ?, ?)''',
                (channel_id, username, name, added_by, datetime.now().isoformat()))
            conn.commit()
            conn.close()
        
        bot_data.mandatory_channels[channel_id] = channel_data
        
        return True
    
    @staticmethod
    def remove_channel(channel_id):
        """حذف قناة إجبارية"""
        if channel_id not in bot_data.mandatory_channels:
            return False
        
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('DELETE FROM channels WHERE channel_id = ?', (channel_id,))
            conn.commit()
            conn.close()
        
        del bot_data.mandatory_channels[channel_id]
        
        return True
    
    @staticmethod
    def get_channels():
        """الحصول على جميع القنوات"""
        return bot_data.mandatory_channels
    
    @staticmethod
    def get_subscription_markup(not_joined):
        """إنشاء أزرار الاشتراك"""
        markup = InlineKeyboardMarkup(row_width=1)
        
        for channel in not_joined:
            username = channel.get('channel_username', '')
            name = channel.get('channel_name', 'قناة')
            
            if username and not username.startswith('-'):
                url = f"https://t.me/{username.replace('@', '')}"
            else:
                url = f"https://t.me/c/{channel['channel_id'].replace('-100', '')}"
            
            markup.add(InlineKeyboardButton(f"📢 {name}", url=url))
        
        markup.add(InlineKeyboardButton("✅ تحقق", callback_data="check_subscription"))
        
        return markup

# ==================== نظام البث ====================

class BroadcastManager:
    """إدارة البث للمستخدمين"""
    
    @staticmethod
    def start_broadcast(admin_id, message, message_obj):
        """بدء عملية البث"""
        broadcast_id = f"broadcast_{int(time.time())}"
        
        # الحصول على قائمة المستخدمين
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('SELECT user_id FROM users WHERE is_banned = 0')
            users = [row[0] for row in c.fetchall()]
            conn.close()
        
        broadcast_data = {
            'id': broadcast_id,
            'admin_id': admin_id,
            'message': message,
            'message_obj': message_obj,
            'users': users,
            'total': len(users),
            'sent': 0,
            'failed': 0,
            'blocked': 0,
            'status': 'running',
            'start_time': datetime.now().isoformat()
        }
        
        bot_data.broadcast_status[broadcast_id] = broadcast_data
        
        # بدء البث في thread منفصل
        thread = threading.Thread(
            target=BroadcastManager._execute_broadcast,
            args=(broadcast_id,)
        )
        thread.daemon = True
        thread.start()
        
        return broadcast_id, len(users)
    
    @staticmethod
    def _execute_broadcast(broadcast_id):
        """تنفيذ البث"""
        broadcast = bot_data.broadcast_status.get(broadcast_id)
        
        if not broadcast:
            return
        
        users = broadcast['users']
        message_obj = broadcast['message_obj']
        admin_id = broadcast['admin_id']
        
        for i, user_id in enumerate(users):
            try:
                if message_obj.text:
                    bot.send_message(user_id, message_obj.text, parse_mode='Markdown')
                elif message_obj.photo:
                    bot.send_photo(
                        user_id,
                        message_obj.photo[-1].file_id,
                        caption=message_obj.caption,
                        parse_mode='Markdown' if message_obj.caption else None
                    )
                elif message_obj.video:
                    bot.send_video(
                        user_id,
                        message_obj.video.file_id,
                        caption=message_obj.caption,
                        parse_mode='Markdown' if message_obj.caption else None
                    )
                elif message_obj.document:
                    bot.send_document(
                        user_id,
                        message_obj.document.file_id,
                        caption=message_obj.caption,
                        parse_mode='Markdown' if message_obj.caption else None
                    )
                
                broadcast['sent'] += 1
                
            except telebot.apihelper.ApiTelegramException as e:
                if "bot was blocked" in str(e).lower():
                    broadcast['blocked'] += 1
                else:
                    broadcast['failed'] += 1
            except Exception:
                broadcast['failed'] += 1
            
            # تحديث التقدم كل 10 مستخدمين
            if (i + 1) % 10 == 0:
                bot_data.broadcast_status[broadcast_id] = broadcast
                time.sleep(1)
        
        broadcast['status'] = 'completed'
        broadcast['end_time'] = datetime.now().isoformat()
        bot_data.broadcast_status[broadcast_id] = broadcast
        
        # إرسال التقرير
        report = (
            f"📊 **تقرير البث**\n\n"
            f"✅ تم الإرسال: {broadcast['sent']}\n"
            f"❌ فشل: {broadcast['failed']}\n"
            f"🚫 محظور: {broadcast['blocked']}\n"
            f"👥 الإجمالي: {broadcast['total']}"
        )
        
        try:
            bot.send_message(admin_id, report, parse_mode='Markdown')
        except:
            pass

# ==================== الديكورات ====================

def owner_only(func):
    """ديكور للمالك فقط"""
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        user_id = message_or_call.from_user.id
        
        if user_id != Config.OWNER_ID:
            if isinstance(message_or_call, types.Message):
                bot.reply_to(message_or_call, "⚠️ هذه الخاصية للمالك فقط!")
            else:
                bot.answer_callback_query(message_or_call.id, "⚠️ للمالك فقط!", show_alert=True)
            return
        
        return func(message_or_call, *args, **kwargs)
    return wrapper

def admin_only(func):
    """ديكور للأدمن فقط"""
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        user_id = message_or_call.from_user.id
        
        if not is_admin(user_id):
            if isinstance(message_or_call, types.Message):
                bot.reply_to(message_or_call, "⚠️ هذه الخاصية للأدمن فقط!")
            else:
                bot.answer_callback_query(message_or_call.id, "⚠️ للأدمن فقط!", show_alert=True)
            return
        
        return func(message_or_call, *args, **kwargs)
    return wrapper

def check_user(func):
    """ديكور للتحقق من المستخدم"""
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        user_id = message_or_call.from_user.id
        
        # التحقق من الحظر
        if is_banned(user_id):
            if isinstance(message_or_call, types.Message):
                bot.reply_to(message_or_call, "🚫 أنت محظور من استخدام البوت")
            else:
                bot.answer_callback_query(message_or_call.id, "🚫 أنت محظور", show_alert=True)
            return
        
        # تحديث آخر نشاط
        update_user_activity(user_id)
        
        return func(message_or_call, *args, **kwargs)
    return wrapper

def require_subscription(func):
    """ديكور للتحقق من الاشتراك الإجباري"""
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        user_id = message_or_call.from_user.id
        
        # الأدمن معفون
        if is_admin(user_id):
            return func(message_or_call, *args, **kwargs)
        
        # التحقق من تفعيل النظام
        if get_setting('force_subscription', '0') != '1':
            return func(message_or_call, *args, **kwargs)
        
        subscribed, not_joined = ChannelManager.check_membership(user_id)
        
        if not subscribed:
            markup = ChannelManager.get_subscription_markup(not_joined)
            
            msg = "🔒 **للوصول للبوت، يجب الاشتراك في القنوات التالية:**\n\n"
            for channel in not_joined:
                msg += f"• {channel.get('channel_name', 'قناة')}\n"
            
            if isinstance(message_or_call, types.Message):
                bot.reply_to(message_or_call, msg, reply_markup=markup, parse_mode='Markdown')
            else:
                bot.answer_callback_query(message_or_call.id)
                try:
                    bot.edit_message_text(
                        msg,
                        message_or_call.message.chat.id,
                        message_or_call.message.message_id,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
                except:
                    bot.send_message(
                        message_or_call.message.chat.id,
                        msg,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
            return
        
        return func(message_or_call, *args, **kwargs)
    return wrapper

def check_bot_lock(func):
    """ديكور للتحقق من قفل البوت"""
    @wraps(func)
    def wrapper(message_or_call, *args, **kwargs):
        if bot_data.bot_locked and not is_admin(message_or_call.from_user.id):
            if isinstance(message_or_call, types.Message):
                bot.reply_to(message_or_call, "🔒 البوت في وضع الصيانة حالياً")
            else:
                bot.answer_callback_query(message_or_call.id, "🔒 البوت في وضع الصيانة", show_alert=True)
            return
        
        return func(message_or_call, *args, **kwargs)
    return wrapper

# ==================== إنشاء القوائم ====================

class MenuBuilder:
    """بناء قوائم البوت"""
    
    @staticmethod
    def main_menu(user_id):
        """القائمة الرئيسية"""
        markup = InlineKeyboardMarkup(row_width=2)
        
        # أزرار عامة
        buttons = [
            InlineKeyboardButton('📤 رفع ملف', callback_data='upload'),
            InlineKeyboardButton('📂 ملفاتي', callback_data='my_files'),
            InlineKeyboardButton('💰 نقاطي', callback_data='my_points'),
            InlineKeyboardButton('🔗 دعوة', callback_data='invite'),
            InlineKeyboardButton('⚡ السرعة', callback_data='speed'),
            InlineKeyboardButton('📊 إحصائيات', callback_data='stats'),
            InlineKeyboardButton('📢 القناة', url=f'https://t.me/{get_setting("update_channel", Config.UPDATE_CHANNEL)}'),
            InlineKeyboardButton('📞 المطور', url=f'https://t.me/{get_setting("developer", Config.YOUR_USERNAME).replace("@", "")}')
        ]
        
        # إضافة الأزرار في صفوف
        markup.add(buttons[0], buttons[1])
        markup.add(buttons[2], buttons[3])
        markup.add(buttons[4], buttons[5])
        markup.add(buttons[6])
        markup.add(buttons[7])
        
        # أزرار الأدمن
        if is_admin(user_id):
            admin_buttons = [
                InlineKeyboardButton('👑 لوحة الأدمن', callback_data='admin_panel'),
                InlineKeyboardButton('📢 بث', callback_data='broadcast'),
                InlineKeyboardButton('🔒 قفل' if not bot_data.bot_locked else '🔓 فتح', 
                                    callback_data='lock' if not bot_data.bot_locked else 'unlock'),
                InlineKeyboardButton('📢 قنوات', callback_data='manage_channels'),
                InlineKeyboardButton('⏹️ إيقاف كل ملفاتي', callback_data='stop_my_files')
            ]
            
            markup.add(admin_buttons[0])
            markup.add(admin_buttons[1], admin_buttons[2])
            markup.add(admin_buttons[3])
            markup.add(admin_buttons[4])
        
        return markup
    
    @staticmethod
    def admin_panel():
        """لوحة تحكم الأدمن"""
        markup = InlineKeyboardMarkup(row_width=2)
        
        buttons = [
            InlineKeyboardButton('📊 إحصائيات', callback_data='admin_stats'),
            InlineKeyboardButton('👥 مستخدمين', callback_data='manage_users'),
            InlineKeyboardButton('💰 نقاط', callback_data='manage_points'),
            InlineKeyboardButton('⭐ VIP', callback_data='manage_vip'),
            InlineKeyboardButton('📢 قنوات', callback_data='manage_channels'),
            InlineKeyboardButton('⚙️ إعدادات', callback_data='settings'),
            InlineKeyboardButton('📁 ملفات معلقة', callback_data='pending_files'),
            InlineKeyboardButton('🔄 عمليات', callback_data='manage_processes'),
            InlineKeyboardButton('🔙 رجوع', callback_data='back_to_main')
        ]
        
        for i in range(0, len(buttons), 2):
            if i + 1 < len(buttons):
                markup.add(buttons[i], buttons[i + 1])
            else:
                markup.add(buttons[i])
        
        return markup
    
    @staticmethod
    def file_controls(user_id, filename, is_running):
        """أزرار التحكم بالملف"""
        markup = InlineKeyboardMarkup(row_width=2)
        
        if is_running:
            markup.add(
                InlineKeyboardButton('🔴 إيقاف', callback_data=f'stop_{user_id}_{filename}'),
                InlineKeyboardButton('🔄 إعادة', callback_data=f'restart_{user_id}_{filename}')
            )
        else:
            markup.add(
                InlineKeyboardButton('🟢 تشغيل', callback_data=f'start_{user_id}_{filename}')
            )
        
        markup.add(
            InlineKeyboardButton('📜 سجلات', callback_data=f'logs_{user_id}_{filename}'),
            InlineKeyboardButton('🗑️ حذف', callback_data=f'delete_{user_id}_{filename}')
        )
        
        markup.add(InlineKeyboardButton('🔙 رجوع', callback_data='my_files'))
        
        return markup
    
    @staticmethod
    def confirm_action(action, data):
        """تأكيد الإجراء"""
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton('✅ تأكيد', callback_data=f'confirm_{action}_{data}'),
            InlineKeyboardButton('❌ إلغاء', callback_data='cancel')
        )
        return markup

# ==================== معالجات الأوامر ====================

@bot.message_handler(commands=['start'])
@check_user
@require_subscription
def cmd_start(message):
    """معالج أمر /start"""
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name
    
    # معالجة الدعوة
    if len(message.text.split()) > 1:
        param = message.text.split()[1]
        if param.startswith('ref_'):
            code = param[4:]
            referrer = PointsSystem.process_referral(user_id, code)
            if referrer:
                try:
                    referrer_name = bot.get_chat(referrer).first_name
                    bot.reply_to(message, f"🎉 مرحباً! لقد انضممت عن طريق {referrer_name}")
                except:
                    bot.reply_to(message, "🎉 مرحباً! لقد انضممت عن طريق دعوة")
    
    # تسجيل المستخدم الجديد
    if user_id not in bot_data.users:
        # إنشاء رمز دعوة
        referral_code = PointsSystem.generate_referral_code(user_id)
        
        # حفظ في قاعدة البيانات
        with DB_LOCK:
            conn = sqlite3.connect(Config.DATABASE_PATH)
            c = conn.cursor()
            c.execute('''INSERT INTO users 
                (user_id, username, first_name, points, join_date, last_active, referral_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (user_id, username, first_name, Config.POINTS_FOR_JOINING,
                 datetime.now().isoformat(), datetime.now().isoformat(), referral_code))
            conn.commit()
            conn.close()
        
        # تحديث الذاكرة
        bot_data.users[user_id] = {
            'user_id': user_id,
            'username': username,
            'first_name': first_name,
            'points': Config.POINTS_FOR_JOINING,
            'is_vip': 0,
            'vip_expiry': None,
            'is_banned': 0,
            'join_date': datetime.now().isoformat(),
            'last_active': datetime.now().isoformat(),
            'referral_code': referral_code,
            'referred_by': None,
            'total_referred': 0
        }
        
        bot_data.user_points[user_id] = Config.POINTS_FOR_JOINING
        bot_data.stats['total_users'] += 1
        
        # إشعار المالك
        if get_setting('new_user_notification', '1') == '1':
            try:
                bot.send_message(
                    Config.OWNER_ID,
                    f"🎉 مستخدم جديد!\n👤 {first_name}\n🆔 `{user_id}`\n📌 @{username}",
                    parse_mode='Markdown'
                )
            except:
                pass
    
    # رسالة الترحيب
    points = PointsSystem.get_user_points(user_id)
    files_count = get_user_files_count(user_id)
    limit = get_user_limit(user_id)
    limit_str = "∞" if limit == float('inf') else str(limit)
    
    welcome = get_setting('welcome_message', '👋 أهلاً بك!')
    
    msg = (
        f"{welcome}\n\n"
        f"👤 {first_name}\n"
        f"🆔 `{user_id}`\n"
        f"💰 النقاط: {points}\n"
        f"📂 ملفات: {files_count}/{limit_str}\n\n"
        f"✨ استخدم الأزرار أدناه"
    )
    
    bot.send_message(
        message.chat.id,
        msg,
        reply_markup=MenuBuilder.main_menu(user_id),
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['points'])
@check_user
@require_subscription
def cmd_points(message):
    """معالج أمر النقاط"""
    user_id = message.from_user.id
    points = PointsSystem.get_user_points(user_id)
    referrals = len(bot_data.user_referrals.get(user_id, []))
    transactions = PointsSystem.get_transactions(user_id, 5)
    
    msg = f"💰 **نقاطك**\n\nالرصيد: `{points}`\nالدعوات: `{referrals}`\n\n"
    
    if transactions:
        msg += "**آخر المعاملات:**\n"
        for t in transactions:
            emoji = "➕" if t['amount'] > 0 else "➖"
            msg += f"{emoji} {abs(t['amount'])} - {t['description'][:30]}\n"
    
    msg += f"\n🔗 استخدم /invite للحصول على رابط دعوتك"
    
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['invite'])
@check_user
@require_subscription
def cmd_invite(message):
    """معالج أمر الدعوة"""
    user_id = message.from_user.id
    link = PointsSystem.get_referral_link(user_id)
    referrals = len(bot_data.user_referrals.get(user_id, []))
    
    msg = (
        f"🔗 **رابط دعوتك**\n\n"
        f"`{link}`\n\n"
        f"📊 الدعوات الناجحة: `{referrals}`\n"
        f"💰 النقاط لكل دعوة: `{get_setting('points_per_referral', Config.POINTS_PER_REFERRAL)}`"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(
        '📤 مشاركة',
        switch_inline_query=f"انضم لبوت الاستضافة عبر رابط دعوتي!"
    ))
    
    bot.reply_to(message, msg, reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(commands=['stats'])
@check_user
@require_subscription
def cmd_stats(message):
    """معالج أمر الإحصائيات"""
    user_id = message.from_user.id
    
    running = 0
    for key, info in bot_data.active_processes.items():
        try:
            if psutil.pid_exists(info['pid']):
                running += 1
        except:
            pass
    
    msg = (
        f"📊 **إحصائيات البوت**\n\n"
        f"👥 المستخدمين: `{bot_data.stats['total_users']}`\n"
        f"📂 الملفات: `{bot_data.stats['total_uploads']}`\n"
        f"🟢 قيد التشغيل: `{running}`\n"
        f"🚫 محاولات ضارة: `{bot_data.stats['blocked_attempts']}`\n"
        f"🔒 حالة البوت: `{'مقفل' if bot_data.bot_locked else 'مفتوح'}`\n"
    )
    
    if is_admin(user_id):
        user_running = sum(1 for key, info in bot_data.active_processes.items() 
                          if info.get('user_id') == user_id)
        msg += f"🤖 ملفاتك النشطة: `{user_running}`\n"
    
    bot.reply_to(message, msg, parse_mode='Markdown')

@bot.message_handler(commands=['ping'])
@check_user
@require_subscription
def cmd_ping(message):
    """معالج أمر اختبار السرعة"""
    start = time.time()
    msg = bot.reply_to(message, "🏓 Pong...")
    latency = round((time.time() - start) * 1000, 2)
    bot.edit_message_text(f"🏓 Pong! زمن الاستجابة: `{latency}ms`", 
                         msg.chat.id, msg.message_id, parse_mode='Markdown')

@bot.message_handler(commands=['stopmyfiles'])
@check_user
@require_subscription
def cmd_stop_my_files(message):
    """معالج أمر إيقاف ملفاتي"""
    user_id = message.from_user.id
    stopped = ScriptRunner.stop_all_user_scripts(user_id)
    bot.reply_to(message, f"⏹️ تم إيقاف `{stopped}` ملف/ملفات", parse_mode='Markdown')

@bot.message_handler(commands=['stopall'])
@owner_only
def cmd_stop_all(message):
    """معالج أمر إيقاف الكل (للمالك فقط)"""
    total = len(bot_data.active_processes)
    stopped = 0
    
    for key, info in list(bot_data.active_processes.items()):
        ScriptRunner.kill_process(info)
        ScriptRunner.cleanup_process(key)
        stopped += 1
    
    bot.reply_to(message, f"⏹️ تم إيقاف `{stopped}/{total}` ملف", parse_mode='Markdown')

@bot.message_handler(commands=['broadcast'])
@admin_only
def cmd_broadcast(message):
    """معالج أمر البث"""
    msg = bot.reply_to(
        message,
        "📢 أرسل الرسالة للبث (نص، صورة، فيديو، ملف)\nأو /cancel للإلغاء"
    )
    bot.register_next_step_handler(msg, process_broadcast_message)

# ==================== معالجات النص ====================

@bot.message_handler(func=lambda m: m.text and m.text.startswith('/'))
def handle_unknown_command(message):
    """معالج الأوامر غير المعروفة"""
    bot.reply_to(message, "❌ أمر غير معروف. استخدم /start")

@bot.message_handler(func=lambda m: m.text in ['📤 رفع ملف', 'رفع ملف'])
@check_user
@require_subscription
@check_bot_lock
def handle_upload_text(message):
    """معالج نص رفع ملف"""
    can, reason = can_upload(message.from_user.id)
    if not can:
        bot.reply_to(message, reason)
        return
    
    points = PointsSystem.get_user_points(message.from_user.id)
    needed = int(get_setting('points_per_file', Config.POINTS_PER_FILE))
    
    if points < needed:
        bot.reply_to(
            message,
            f"❌ نقاط غير كافية!\nلديك: `{points}`\nالمطلوب: `{needed}`",
            parse_mode='Markdown'
        )
        return
    
    bot.reply_to(message, "📤 أرسل ملف Python (.py) الآن")

@bot.message_handler(func=lambda m: m.text in ['📂 ملفاتي', 'ملفاتي'])
@check_user
@require_subscription
def handle_my_files_text(message):
    """معالج نص ملفاتي"""
    show_user_files(message)

@bot.message_handler(func=lambda m: m.text in ['💰 نقاطي', 'نقاطي'])
@check_user
@require_subscription
def handle_my_points_text(message):
    """معالج نص نقاطي"""
    cmd_points(message)

@bot.message_handler(func=lambda m: m.text in ['🔗 دعوة', 'دعوة'])
@check_user
@require_subscription
def handle_invite_text(message):
    """معالج نص دعوة"""
    cmd_invite(message)

@bot.message_handler(func=lambda m: m.text in ['⚡ السرعة', 'السرعة'])
@check_user
@require_subscription
def handle_speed_text(message):
    """معالج نص السرعة"""
    cmd_ping(message)

@bot.message_handler(func=lambda m: m.text in ['📊 إحصائيات', 'إحصائيات'])
@check_user
@require_subscription
def handle_stats_text(message):
    """معالج نص إحصائيات"""
    cmd_stats(message)

@bot.message_handler(func=lambda m: m.text in ['🔙 رجوع', 'رجوع'])
@check_user
def handle_back_text(message):
    """معالج نص رجوع"""
    cmd_start(message)

@bot.message_handler(content_types=['document'])
@check_user
@require_subscription
@check_bot_lock
def handle_document(message):
    """معالج رفع الملفات"""
    user_id = message.from_user.id
    
    # التحقق من إمكانية الرفع
    can, reason = can_upload(user_id)
    if not can:
        bot.reply_to(message, reason)
        return
    
    # التحقق من النقاط
    points = PointsSystem.get_user_points(user_id)
    needed = int(get_setting('points_per_file', Config.POINTS_PER_FILE))
    
    if points < needed and not is_admin(user_id) and not is_vip(user_id):
        bot.reply_to(
            message,
            f"❌ نقاط غير كافية!\nلديك: `{points}`\nالمطلوب: `{needed}`",
            parse_mode='Markdown'
        )
        return
    
    doc = message.document
    
    # التحقق من نوع الملف
    safe, allowed = SecurityManager.check_file_type(doc.file_name)
    if not safe:
        bot.reply_to(
            message,
            f"❌ نوع ملف غير مسموح. المسموح: {', '.join(allowed)}"
        )
        return
    
    # التحقق من الحجم
    safe, max_size = SecurityManager.check_file_size(doc.file_size)
    if not safe:
        bot.reply_to(
            message,
            f"❌ حجم الملف كبير! الحد الأقصى: {max_size // 1024 // 1024}MB"
        )
        return
    
    msg = bot.reply_to(message, "⏳ جاري تحميل الملف...")
    
    try:
        # تحميل الملف
        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # حفظ الملف
        file_path, file_record = FileManager.save_file(user_id, downloaded, doc.file_name)
        
        bot.edit_message_text("🔍 جاري فحص الملف...", msg.chat.id, msg.message_id)
        
        # فحص الأمان
        scan_result = SecurityManager.scan_file(file_path)
        
        # إذا كان المستخدم أدمن أو VIP، يتم التشغيل مباشرة
        if is_admin(user_id) or is_vip(user_id):
            if scan_result['score'] < 50:
                # ملف خطير حتى للأدمن
                quarantine_path = SecurityManager.quarantine_file(
                    file_path, 
                    f"نقاط الأمان: {scan_result['score']}"
                )
                
                FileManager.delete_file(user_id, doc.file_name)
                
                bot.edit_message_text(
                    f"❌ ملف ضار! تم عزله.\n"
                    f"النتيجة: {scan_result['score']}\n"
                    f"الأخطار: {', '.join(scan_result['dangerous'][:3])}",
                    msg.chat.id,
                    msg.message_id
                )
                
                # إبلاغ الأدمن
                for admin in bot_data.admin_ids:
                    try:
                        bot.send_message(
                            admin,
                            f"🚨 ملف ضار من أدمن!\n👤 {user_id}\n📁 {doc.file_name}\n📊 {scan_result['score']}"
                        )
                    except:
                        pass
                
                return
            
            # خصم النقاط
            if not is_admin(user_id) and not is_vip(user_id):
                PointsSystem.deduct_points(
                    user_id, 
                    needed, 
                    f"رفع {doc.file_name}"
                )
            
            bot.edit_message_text(
                f"✅ تم رفع الملف وجاري التشغيل...",
                msg.chat.id,
                msg.message_id
            )
            
            # تشغيل الملف
            threading.Thread(
                target=ScriptRunner.run_script,
                args=(user_id, doc.file_name, message)
            ).start()
            
        else:
            # المستخدمين العاديين: يتم إرسال للمراجعة
            if scan_result['safe'] and scan_result['score'] >= 70:
                # ملف آمن - تشغيل مباشر
                PointsSystem.deduct_points(
                    user_id, 
                    needed, 
                    f"رفع {doc.file_name}"
                )
                
                bot.edit_message_text(
                    f"✅ ملف آمن! جاري التشغيل...",
                    msg.chat.id,
                    msg.message_id
                )
                
                threading.Thread(
                    target=ScriptRunner.run_script,
                    args=(user_id, doc.file_name, message)
                ).start()
                
            elif scan_result['score'] >= 50:
                # ملف يحتاج مراجعة
                bot_data.pending_approvals[file_record['id']] = {
                    'user_id': user_id,
                    'file_name': doc.file_name,
                    'file_path': file_path,
                    'scan_result': scan_result,
                    'timestamp': datetime.now().isoformat()
                }
                
                # إبلاغ الأدمن
                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton('✅ موافقة', callback_data=f'approve_{file_record["id"]}'),
                    InlineKeyboardButton('❌ رفض', callback_data=f'reject_{file_record["id"]}')
                )
                
                for admin in bot_data.admin_ids:
                    try:
                        bot.send_document(
                            admin,
                            open(file_path, 'rb'),
                            caption=(
                                f"📥 ملف للمراجعة\n"
                                f"👤 {user_id}\n"
                                f"📁 {doc.file_name}\n"
                                f"📊 نقاط الأمان: {scan_result['score']}\n"
                                f"⚠️ تحذيرات: {len(scan_result['warnings'])}"
                            ),
                            reply_markup=markup
                        )
                    except:
                        pass
                
                bot.edit_message_text(
                    f"⏳ الملف قيد المراجعة الأمنية...",
                    msg.chat.id,
                    msg.message_id
                )
                
            else:
                # ملف ضار - رفض فوري
                quarantine_path = SecurityManager.quarantine_file(
                    file_path,
                    f"نقاط أمان منخفضة: {scan_result['score']}"
                )
                
                FileManager.delete_file(user_id, doc.file_name)
                
                bot.edit_message_text(
                    f"❌ ملف ضار! تم رفضه.\n"
                    f"النتيجة: {scan_result['score']}",
                    msg.chat.id,
                    msg.message_id
                )
                
                # إبلاغ الأدمن
                for admin in bot_data.admin_ids:
                    try:
                        bot.send_message(
                            admin,
                            f"🚨 محاولة رفع ملف ضار!\n"
                            f"👤 {user_id}\n"
                            f"📁 {doc.file_name}\n"
                            f"📊 {scan_result['score']}"
                        )
                    except:
                        pass
                
                bot_data.stats['blocked_attempts'] += 1
    
    except Exception as e:
        logger.error(f"خطأ في رفع الملف: {e}")
        bot.edit_message_text(f"❌ خطأ: {str(e)[:100]}", msg.chat.id, msg.message_id)

# ==================== معالجات الاستدعاء ====================

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    """معالج جميع الاستدعاءات"""
    user_id = call.from_user.id
    data = call.data
    
    try:
        # التحقق من الحظر
        if is_banned(user_id):
            bot.answer_callback_query(call.id, "🚫 أنت محظور", show_alert=True)
            return
        
        # تحديث آخر نشاط
        update_user_activity(user_id)
        
        # التحقق من الاشتراك لبعض الأزرار
        if data not in ['check_subscription', 'back_to_main'] and not is_admin(user_id):
            if get_setting('force_subscription', '0') == '1':
                subscribed, _ = ChannelManager.check_membership(user_id)
                if not subscribed:
                    bot.answer_callback_query(call.id, "🔒 يجب الاشتراك في القنوات أولاً", show_alert=True)
                    return
        
        # ========== أزرار عامة ==========
        if data == 'upload':
            bot.answer_callback_query(call.id)
            can, reason = can_upload(user_id)
            if not can:
                bot.send_message(call.message.chat.id, reason)
                return
            
            points = PointsSystem.get_user_points(user_id)
            needed = int(get_setting('points_per_file', Config.POINTS_PER_FILE))
            
            if points < needed and not is_admin(user_id) and not is_vip(user_id):
                bot.send_message(
                    call.message.chat.id,
                    f"❌ نقاط غير كافية!\nلديك: {points}\nالمطلوب: {needed}"
                )
                return
            
            bot.send_message(call.message.chat.id, "📤 أرسل ملف Python (.py) الآن")
        
        elif data == 'my_files':
            bot.answer_callback_query(call.id)
            show_user_files(call)
        
        elif data == 'my_points':
            bot.answer_callback_query(call.id)
            cmd_points(call.message)
        
        elif data == 'invite':
            bot.answer_callback_query(call.id)
            cmd_invite(call.message)
        
        elif data == 'speed':
            bot.answer_callback_query(call.id)
            cmd_ping(call.message)
        
        elif data == 'stats':
            bot.answer_callback_query(call.id)
            cmd_stats(call.message)
        
        elif data == 'stop_my_files':
            bot.answer_callback_query(call.id, "⏹️ جاري الإيقاف...")
            stopped = ScriptRunner.stop_all_user_scripts(user_id)
            bot.send_message(call.message.chat.id, f"⏹️ تم إيقاف {stopped} ملف")
        
        elif data == 'back_to_main':
            bot.answer_callback_query(call.id)
            cmd_start(call.message)
        
        elif data == 'check_subscription':
            bot.answer_callback_query(call.id)
            subscribed, not_joined = ChannelManager.check_membership(user_id)
            
            if subscribed:
                bot.answer_callback_query(call.id, "✅ أنت مشترك في جميع القنوات", show_alert=True)
                cmd_start(call.message)
            else:
                markup = ChannelManager.get_subscription_markup(not_joined)
                bot.edit_message_text(
                    "🔒 يجب الاشتراك في القنوات التالية:",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup
                )
        
        elif data == 'cancel':
            bot.answer_callback_query(call.id, "❌ تم الإلغاء")
            bot.delete_message(call.message.chat.id, call.message.message_id)
        
        # ========== أزرار الملفات ==========
        elif data.startswith('file_'):
            handle_file_callback(call)
        
        elif data.startswith('start_'):
            handle_start_callback(call)
        
        elif data.startswith('stop_'):
            handle_stop_callback(call)
        
        elif data.startswith('restart_'):
            handle_restart_callback(call)
        
        elif data.startswith('delete_'):
            handle_delete_callback(call)
        
        elif data.startswith('logs_'):
            handle_logs_callback(call)
        
        # ========== أزرار الأدمن ==========
        elif data == 'admin_panel' and is_admin(user_id):
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "👑 لوحة تحكم الأدمن",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=MenuBuilder.admin_panel()
            )
        
        elif data == 'admin_stats' and is_admin(user_id):
            show_admin_stats(call)
        
        elif data == 'manage_users' and is_admin(user_id):
            show_user_management(call)
        
        elif data == 'manage_points' and is_admin(user_id):
            show_points_management(call)
        
        elif data == 'manage_vip' and is_admin(user_id):
            show_vip_management(call)
        
        elif data == 'manage_channels' and is_admin(user_id):
            show_channel_management(call)
        
        elif data == 'settings' and is_admin(user_id):
            show_settings(call)
        
        elif data == 'pending_files' and is_admin(user_id):
            show_pending_files(call)
        
        elif data == 'manage_processes' and is_admin(user_id):
            show_processes(call)
        
        elif data == 'lock' and is_admin(user_id):
            bot_data.bot_locked = True
            bot.answer_callback_query(call.id, "🔒 تم قفل البوت")
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=MenuBuilder.main_menu(user_id)
            )
        
        elif data == 'unlock' and is_admin(user_id):
            bot_data.bot_locked = False
            bot.answer_callback_query(call.id, "🔓 تم فتح البوت")
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=MenuBuilder.main_menu(user_id)
            )
        
        elif data == 'broadcast' and is_admin(user_id):
            bot.answer_callback_query(call.id)
            msg = bot.send_message(
                call.message.chat.id,
                "📢 أرسل الرسالة للبث\nأو /cancel للإلغاء"
            )
            bot.register_next_step_handler(msg, process_broadcast_message)
        
        # ========== أزرار الموافقة ==========
        elif data.startswith('approve_') and is_admin(user_id):
            handle_approve_callback(call)
        
        elif data.startswith('reject_') and is_admin(user_id):
            handle_reject_callback(call)
        
        # ========== أزرار إدارة القنوات ==========
        elif data == 'add_channel' and is_admin(user_id):
            bot.answer_callback_query(call.id)
            msg = bot.send_message(
                call.message.chat.id,
                "📢 أرسل معرف القناة (مثال: @channel أو -1001234567890)"
            )
            bot.register_next_step_handler(msg, process_add_channel)
        
        elif data.startswith('remove_channel_') and is_admin(user_id):
            channel_id = data.replace('remove_channel_', '')
            if ChannelManager.remove_channel(channel_id):
                bot.answer_callback_query(call.id, "✅ تم حذف القناة")
                show_channel_management(call)
            else:
                bot.answer_callback_query(call.id, "❌ فشل الحذف", show_alert=True)
        
        elif data == 'toggle_force' and is_admin(user_id):
            current = get_setting('force_subscription', '0')
            new = '0' if current == '1' else '1'
            update_setting('force_subscription', new)
            bot.answer_callback_query(call.id, f"✅ تم {'تفعيل' if new == '1' else 'تعطيل'} الاشتراك الإجباري")
            show_channel_management(call)
        
        else:
            bot.answer_callback_query(call.id, "⚠️ إجراء غير معروف")
    
    except Exception as e:
        logger.error(f"خطأ في معالجة الاستدعاء {data}: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "❌ حدث خطأ", show_alert=True)

# ==================== دوال الملفات المساعدة ====================

def show_user_files(call_or_message):
    """عرض ملفات المستخدم"""
    user_id = call_or_message.from_user.id
    
    files = FileManager.get_user_files(user_id)
    
    if not files:
        if isinstance(call_or_message, types.CallbackQuery):
            bot.answer_callback_query(call_or_message.id, "📂 لا توجد ملفات", show_alert=True)
        else:
            bot.reply_to(call_or_message, "📂 لا توجد ملفات مرفوعة")
        return
    
    markup = InlineKeyboardMarkup(row_width=1)
    
    for file in files:
        is_running = ScriptRunner.is_running(user_id, file['file_name'])
        status = "🟢" if is_running else "🔴"
        size = file['file_size'] / 1024
        markup.add(InlineKeyboardButton(
            f"{status} {file['file_name']} ({size:.1f}KB)",
            callback_data=f"file_{user_id}_{file['file_name']}"
        ))
    
    markup.add(InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main"))
    
    if isinstance(call_or_message, types.CallbackQuery):
        try:
            bot.edit_message_text(
                "📂 ملفاتك:",
                call_or_message.message.chat.id,
                call_or_message.message.message_id,
                reply_markup=markup
            )
        except:
            bot.send_message(
                call_or_message.message.chat.id,
                "📂 ملفاتك:",
                reply_markup=markup
            )
    else:
        bot.send_message(
            call_or_message.chat.id,
            "📂 ملفاتك:",
            reply_markup=markup
        )

def handle_file_callback(call):
    """معالج اختيار ملف"""
    try:
        parts = call.data.split('_', 2)
        if len(parts) < 3:
            bot.answer_callback_query(call.id, "❌ بيانات غير صحيحة")
            return
        
        owner_id = int(parts[1])
        filename = parts[2]
        user_id = call.from_user.id
        
        if user_id != owner_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ هذا الملف ليس لك", show_alert=True)
            return
        
        file_record = FileManager.get_file(owner_id, filename)
        if not file_record:
            bot.answer_callback_query(call.id, "❌ الملف غير موجود", show_alert=True)
            return
        
        is_running = ScriptRunner.is_running(owner_id, filename)
        size = file_record['file_size'] / 1024
        upload_date = datetime.fromisoformat(file_record['upload_date']).strftime('%Y-%m-%d %H:%M')
        
        msg = (
            f"📁 **{filename}**\n\n"
            f"📊 الحجم: `{size:.1f}KB`\n"
            f"📅 الرفع: `{upload_date}`\n"
            f"🔄 الحالة: `{'🟢 يعمل' if is_running else '🔴 متوقف'}`\n"
        )
        
        bot.edit_message_text(
            msg,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=MenuBuilder.file_controls(owner_id, filename, is_running),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"خطأ في handle_file_callback: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

def handle_start_callback(call):
    """معالج تشغيل ملف"""
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        filename = parts[2]
        user_id = call.from_user.id
        
        if user_id != owner_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ غير مصرح", show_alert=True)
            return
        
        if ScriptRunner.is_running(owner_id, filename):
            bot.answer_callback_query(call.id, "⚠️ الملف يعمل بالفعل", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, "🔄 جاري التشغيل...")
        
        success, message = ScriptRunner.run_script(owner_id, filename, call.message)
        
        if not success:
            bot.send_message(call.message.chat.id, f"❌ {message}")
        
        # تحديث العرض
        time.sleep(1)
        is_running = ScriptRunner.is_running(owner_id, filename)
        
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=MenuBuilder.file_controls(owner_id, filename, is_running)
            )
        except:
            pass
        
    except Exception as e:
        logger.error(f"خطأ في handle_start_callback: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

def handle_stop_callback(call):
    """معالج إيقاف ملف"""
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        filename = parts[2]
        user_id = call.from_user.id
        
        if user_id != owner_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ غير مصرح", show_alert=True)
            return
        
        if not ScriptRunner.is_running(owner_id, filename):
            bot.answer_callback_query(call.id, "⚠️ الملف متوقف بالفعل", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, "⏹️ جاري الإيقاف...")
        
        success, message = ScriptRunner.stop_script(owner_id, filename)
        
        if success:
            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=MenuBuilder.file_controls(owner_id, filename, False)
                )
            except:
                pass
            
            bot.send_message(call.message.chat.id, f"⏹️ {message}")
        else:
            bot.send_message(call.message.chat.id, f"❌ {message}")
        
    except Exception as e:
        logger.error(f"خطأ في handle_stop_callback: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

def handle_restart_callback(call):
    """معالج إعادة تشغيل ملف"""
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        filename = parts[2]
        user_id = call.from_user.id
        
        if user_id != owner_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ غير مصرح", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, "🔄 جاري إعادة التشغيل...")
        
        # إيقاف إذا كان يعمل
        if ScriptRunner.is_running(owner_id, filename):
            ScriptRunner.stop_script(owner_id, filename)
            time.sleep(1)
        
        # تشغيل من جديد
        success, message = ScriptRunner.run_script(owner_id, filename, call.message)
        
        if not success:
            bot.send_message(call.message.chat.id, f"❌ {message}")
        
        # تحديث العرض
        time.sleep(1)
        is_running = ScriptRunner.is_running(owner_id, filename)
        
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id,
                call.message.message_id,
                reply_markup=MenuBuilder.file_controls(owner_id, filename, is_running)
            )
        except:
            pass
        
    except Exception as e:
        logger.error(f"خطأ في handle_restart_callback: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

def handle_delete_callback(call):
    """معالج حذف ملف"""
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        filename = parts[2]
        user_id = call.from_user.id
        
        if user_id != owner_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ غير مصرح", show_alert=True)
            return
        
        # إيقاف إذا كان يعمل
        if ScriptRunner.is_running(owner_id, filename):
            ScriptRunner.stop_script(owner_id, filename)
        
        # حذف الملف
        success, message = FileManager.delete_file(owner_id, filename)
        
        if success:
            bot.answer_callback_query(call.id, f"🗑️ تم حذف {filename}")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"✅ تم حذف {filename}")
        else:
            bot.answer_callback_query(call.id, f"❌ {message}", show_alert=True)
        
    except Exception as e:
        logger.error(f"خطأ في handle_delete_callback: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

def handle_logs_callback(call):
    """معالج عرض السجلات"""
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        filename = parts[2]
        user_id = call.from_user.id
        
        if user_id != owner_id and not is_admin(user_id):
            bot.answer_callback_query(call.id, "⚠️ غير مصرح", show_alert=True)
            return
        
        bot.answer_callback_query(call.id, "📜 جاري تحميل السجلات...")
        
        logs = ScriptRunner.get_logs(owner_id, filename)
        
        if len(logs) > Config.MAX_MESSAGE_LENGTH:
            # تقسيم السجلات
            parts = [logs[i:i+Config.MAX_MESSAGE_LENGTH] 
                    for i in range(0, len(logs), Config.MAX_MESSAGE_LENGTH)]
            
            for i, part in enumerate(parts[:3]):  # حد أقصى 3 أجزاء
                bot.send_message(
                    call.message.chat.id,
                    f"📜 سجلات {filename} (جزء {i+1}):\n```\n{part}\n```",
                    parse_mode='Markdown'
                )
            
            if len(parts) > 3:
                bot.send_message(
                    call.message.chat.id,
                    f"📜 ... و {len(parts) - 3} جزء آخر"
                )
        else:
            bot.send_message(
                call.message.chat.id,
                f"📜 سجلات {filename}:\n```\n{logs}\n```",
                parse_mode='Markdown'
            )
        
    except Exception as e:
        logger.error(f"خطأ في handle_logs_callback: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

# ==================== دوال الأدمن المساعدة ====================

def show_admin_stats(call):
    """عرض إحصائيات متقدمة للأدمن"""
    with DB_LOCK:
        conn = sqlite3.connect(Config.DATABASE_PATH)
        c = conn.cursor()
        
        # إحصائيات متقدمة
        c.execute('SELECT COUNT(*) FROM users WHERE is_vip = 1')
        vip_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM users WHERE is_banned = 1')
        banned_count = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM users WHERE date(join_date) = date("now")')
        new_today = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM users WHERE date(last_active) = date("now")')
        active_today = c.fetchone()[0]
        
        c.execute('SELECT SUM(points) FROM users')
        total_points = c.fetchone()[0] or 0
        
        c.execute('SELECT COUNT(*) FROM processes WHERE status = "running"')
        running_processes = c.fetchone()[0]
        
        conn.close()
    
    running = len(bot_data.active_processes)
    
    msg = (
        f"📊 **إحصائيات متقدمة**\n\n"
        f"👥 **المستخدمين:**\n"
        f"• الإجمالي: `{bot_data.stats['total_users']}`\n"
        f"• VIP: `{vip_count}`\n"
        f"• محظورين: `{banned_count}`\n"
        f"• جدد اليوم: `{new_today}`\n"
        f"• نشطين اليوم: `{active_today}`\n\n"
        f"💰 **النقاط:**\n"
        f"• الإجمالي: `{total_points}`\n"
        f"• متوسط: `{total_points // max(1, bot_data.stats['total_users'])}`\n\n"
        f"📂 **الملفات:**\n"
        f"• الإجمالي: `{bot_data.stats['total_uploads']}`\n"
        f"• قيد التشغيل: `{running}`\n"
        f"• في قاعدة البيانات: `{running_processes}`\n\n"
        f"🚫 **محاولات ضارة:** `{bot_data.stats['blocked_attempts']}`\n"
        f"🔒 **حالة البوت:** `{'مقفل' if bot_data.bot_locked else 'مفتوح'}`\n"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('🔄 تحديث', callback_data='admin_stats'))
    markup.add(InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel'))
    
    bot.edit_message_text(
        msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def show_user_management(call):
    """عرض إدارة المستخدمين"""
    markup = InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        InlineKeyboardButton('👥 قائمة', callback_data='list_users'),
        InlineKeyboardButton('🔍 بحث', callback_data='search_user'),
        InlineKeyboardButton('⛔ حظر', callback_data='ban_user'),
        InlineKeyboardButton('✅ فك حظر', callback_data='unban_user'),
        InlineKeyboardButton('📊 إحصائيات', callback_data='user_stats'),
        InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel')
    ]
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    
    bot.edit_message_text(
        "👥 إدارة المستخدمين",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def show_points_management(call):
    """عرض إدارة النقاط"""
    markup = InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        InlineKeyboardButton('➕ إضافة', callback_data='add_points'),
        InlineKeyboardButton('➖ خصم', callback_data='deduct_points'),
        InlineKeyboardButton('💰 تعديل', callback_data='set_points'),
        InlineKeyboardButton('📊 إحصائيات', callback_data='points_stats'),
        InlineKeyboardButton('⚙️ إعدادات', callback_data='points_settings'),
        InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel')
    ]
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    
    bot.edit_message_text(
        "💰 إدارة النقاط",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def show_vip_management(call):
    """عرض إدارة VIP"""
    markup = InlineKeyboardMarkup(row_width=2)
    
    buttons = [
        InlineKeyboardButton('⭐ إضافة', callback_data='add_vip'),
        InlineKeyboardButton('🚫 إزالة', callback_data='remove_vip'),
        InlineKeyboardButton('📋 قائمة', callback_data='vip_list'),
        InlineKeyboardButton('💰 أسعار', callback_data='vip_prices'),
        InlineKeyboardButton('⚙️ إعدادات', callback_data='vip_settings'),
        InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel')
    ]
    
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    
    bot.edit_message_text(
        "⭐ إدارة VIP",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def show_channel_management(call):
    """عرض إدارة القنوات"""
    channels = ChannelManager.get_channels()
    force_status = get_setting('force_subscription', '0')
    
    status_text = "✅ مفعل" if force_status == '1' else "❌ معطل"
    
    msg = f"📢 **إدارة القنوات الإجبارية**\n\n"
    msg += f"الحالة: {status_text}\n"
    msg += f"عدد القنوات: `{len(channels)}`\n\n"
    
    if channels:
        msg += "**القنوات الحالية:**\n"
        for ch_id, info in channels.items():
            name = info.get('channel_name', 'غير معروف')
            username = info.get('channel_username', '')
            msg += f"• {name}\n  {username or ch_id}\n"
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton('➕ إضافة', callback_data='add_channel'),
        InlineKeyboardButton('➖ حذف', callback_data='remove_channel')
    )
    markup.add(
        InlineKeyboardButton('🔔 تفعيل/تعطيل', callback_data='toggle_force')
    )
    markup.add(InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel'))
    
    bot.edit_message_text(
        msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def show_settings(call):
    """عرض الإعدادات"""
    settings = [
        ('bot_enabled', 'حالة البوت'),
        ('vip_enabled', 'نظام VIP'),
        ('force_subscription', 'الاشتراك الإجباري'),
        ('new_user_notification', 'إشعارات المستخدمين'),
        ('auto_approve_vip', 'موافقة تلقائية VIP'),
        ('backup_enabled', 'النسخ الاحتياطي')
    ]
    
    msg = "⚙️ **إعدادات البوت**\n\n"
    
    markup = InlineKeyboardMarkup(row_width=2)
    
    for key, name in settings:
        value = get_setting(key, '0')
        status = "✅" if value == '1' else "❌"
        msg += f"{status} {name}\n"
        markup.add(InlineKeyboardButton(
            f"تغيير {name}",
            callback_data=f'toggle_setting_{key}'
        ))
    
    markup.add(InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel'))
    
    bot.edit_message_text(
        msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def show_pending_files(call):
    """عرض الملفات المعلقة"""
    if not bot_data.pending_approvals:
        bot.answer_callback_query(call.id, "✅ لا توجد ملفات معلقة", show_alert=True)
        return
    
    msg = f"📁 **ملفات معلقة:** `{len(bot_data.pending_approvals)}`\n\n"
    
    for file_id, info in list(bot_data.pending_approvals.items())[:5]:
        msg += f"• {info['file_name']}\n  👤 {info['user_id']}\n  📊 {info['scan_result']['score']}\n\n"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel'))
    
    bot.edit_message_text(
        msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def show_processes(call):
    """عرض العمليات النشطة"""
    running = 0
    processes_info = []
    
    for key, info in bot_data.active_processes.items():
        try:
            if psutil.pid_exists(info['pid']):
                running += 1
                proc = psutil.Process(info['pid'])
                cpu = proc.cpu_percent()
                memory = proc.memory_percent()
                processes_info.append(
                    f"• {info['filename']}\n"
                    f"  👤 {info['user_id']}\n"
                    f"  🖥️ CPU: {cpu:.1f}% | RAM: {memory:.1f}%"
                )
        except:
            pass
    
    msg = f"🔄 **العمليات النشطة**\n\n"
    msg += f"قيد التشغيل: `{running}/{len(bot_data.active_processes)}`\n\n"
    
    if processes_info:
        msg += '\n'.join(processes_info[:5])
        if len(processes_info) > 5:
            msg += f"\n... و {len(processes_info) - 5} عملية أخرى"
    
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton('🔄 تحديث', callback_data='manage_processes'),
        InlineKeyboardButton('🔙 رجوع', callback_data='admin_panel')
    )
    
    bot.edit_message_text(
        msg,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode='Markdown'
    )

def handle_approve_callback(call):
    """معالج الموافقة على ملف"""
    try:
        file_id = int(call.data.replace('approve_', ''))
        pending = bot_data.pending_approvals.get(file_id)
        
        if not pending:
            bot.answer_callback_query(call.id, "❌ الملف غير موجود", show_alert=True)
            return
        
        user_id = pending['user_id']
        filename = pending['file_name']
        
        # خصم النقاط
        needed = int(get_setting('points_per_file', Config.POINTS_PER_FILE))
        PointsSystem.deduct_points(user_id, needed, f"رفع {filename} (موافقة أدمن)")
        
        # إخطار المستخدم
        try:
            bot.send_message(
                user_id,
                f"✅ تمت الموافقة على ملفك `{filename}` وجاري تشغيله",
                parse_mode='Markdown'
            )
        except:
            pass
        
        # تشغيل الملف
        threading.Thread(
            target=ScriptRunner.run_script,
            args=(user_id, filename, call.message)
        ).start()
        
        # حذف من المعلقة
        del bot_data.pending_approvals[file_id]
        
        bot.answer_callback_query(call.id, "✅ تمت الموافقة")
        bot.edit_message_text(
            f"✅ تمت الموافقة على ملف {filename} للمستخدم {user_id}",
            call.message.chat.id,
            call.message.message_id
        )
        
    except Exception as e:
        logger.error(f"خطأ في الموافقة: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

def handle_reject_callback(call):
    """معالج رفض ملف"""
    try:
        file_id = int(call.data.replace('reject_', ''))
        pending = bot_data.pending_approvals.get(file_id)
        
        if not pending:
            bot.answer_callback_query(call.id, "❌ الملف غير موجود", show_alert=True)
            return
        
        user_id = pending['user_id']
        filename = pending['file_name']
        
        # حذف الملف
        FileManager.delete_file(user_id, filename)
        
        # إخطار المستخدم
        try:
            bot.send_message(
                user_id,
                f"❌ تم رفض ملفك `{filename}` لأسباب أمنية",
                parse_mode='Markdown'
            )
        except:
            pass
        
        # حذف من المعلقة
        del bot_data.pending_approvals[file_id]
        
        bot.answer_callback_query(call.id, "❌ تم الرفض")
        bot.edit_message_text(
            f"❌ تم رفض ملف {filename} للمستخدم {user_id}",
            call.message.chat.id,
            call.message.message_id
        )
        
    except Exception as e:
        logger.error(f"خطأ في الرفض: {e}")
        bot.answer_callback_query(call.id, "❌ خطأ", show_alert=True)

# ==================== دوال إضافية ====================

def process_broadcast_message(message):
    """معالجة رسالة البث"""
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ تم إلغاء البث")
        return
    
    broadcast_id, total = BroadcastManager.start_broadcast(
        message.from_user.id,
        message.text if message.text else "رسالة وسائط",
        message
    )
    
    bot.reply_to(
        message,
        f"📢 بدء البث إلى {total} مستخدم...\nمعرف البث: `{broadcast_id}`",
        parse_mode='Markdown'
    )

def process_add_channel(message):
    """معالجة إضافة قناة"""
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "❌ تم الإلغاء")
        return
    
    try:
        chat = bot.get_chat(message.text.strip())
        
        # التحقق من صلاحيات البوت
        bot_member = bot.get_chat_member(chat.id, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            bot.reply_to(message, "❌ البوت ليس أدمن في القناة!")
            return
        
        username = f"@{chat.username}" if chat.username else ""
        ChannelManager.add_channel(
            str(chat.id),
            username,
            chat.title,
            message.from_user.id
        )
        
        bot.reply_to(
            message,
            f"✅ تمت إضافة القناة:\n**{chat.title}**\n{username or chat.id}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {str(e)}")

# ==================== تنظيف الإغلاق ====================

def cleanup():
    """تنظيف عند إغلاق البوت"""
    logger.warning("🛑 جاري إيقاف البوت وتنظيف العمليات...")
    
    # إيقاف جميع العمليات
    count = len(bot_data.active_processes)
    if count > 0:
        logger.info(f"جاري إيقاف {count} عملية...")
        
        for key, info in list(bot_data.active_processes.items()):
            try:
                ScriptRunner.kill_process(info)
            except:
                pass
    
    # تحديث قاعدة البيانات
    with DB_LOCK:
        conn = sqlite3.connect(Config.DATABASE_PATH)
        c = conn.cursor()
        c.execute("UPDATE processes SET status = 'stopped' WHERE status = 'running'")
        conn.commit()
        conn.close()
    
    logger.info("✅ تم التنظيف بنجاح")

atexit.register(cleanup)

# ==================== التشغيل الرئيسي ====================

if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🚀 بدء تشغيل بوت الاستضافة المتطور...")
    logger.info(f"🐍 Python: {sys.version.split()[0]}")
    logger.info(f"👑 المالك: {Config.OWNER_ID}")
    logger.info(f"📊 المستخدمين: {bot_data.stats['total_users']}")
    logger.info(f"📂 الملفات: {bot_data.stats['total_uploads']}")
    logger.info(f"🔄 العمليات: {len(bot_data.active_processes)}")
    logger.info("="*60)
    
    # تشغيل Flask
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("✅ تم تشغيل خادم Flask")
    
    # تشغيل البوت
    logger.info("🚀 بدء استقبال الرسائل...")
    
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("⚠️ انتهت مهلة الاتصال، إعادة المحاولة...")
            time.sleep(5)
        except requests.exceptions.ConnectionError:
            logger.warning("⚠️ خطأ في الاتصال، إعادة المحاولة...")
            time.sleep(15)
        except Exception as e:
            logger.error(f"💥 خطأ غير متوقع: {e}", exc_info=True)
            time.sleep(30)