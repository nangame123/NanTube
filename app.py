import os
import re
import sqlite3
import random
from flask import Flask, request, render_template, send_file, redirect, url_for, flash, jsonify, session
from urllib.parse import quote, unquote
import threading
import time
from datetime import datetime, timedelta
import psutil
import socket
import platform
import subprocess
import json

def get_all_videos():
    """Получает все видео из базы данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename, display_name, orientation 
        FROM videos 
        WHERE banned = 0 
        ORDER BY created_at DESC
    ''')
    videos = cursor.fetchall()
    conn.close()
    return videos

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

db_lock = threading.Lock()

try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("OpenCV не установлен. Автоматическое определение ориентации видео недоступно.")

# Конфигурация
VIDEO_FOLDER = r'E:\videos'  # Измените на абсолютный путь к папке с видео
ALLOWED_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'webm'}
DATABASE_PATH = 'video_database.db'

# Добавляем переменную для хранения статуса админского доступа
admin_access = False

@app.route('/random_vertical')
def random_vertical():
    """Открывает случайное вертикальное видео"""
    vertical_videos = get_all_vertical_videos()
    
    if vertical_videos:
        random_video = random.choice(vertical_videos)
        return redirect(url_for('vertical_video', filename=random_video))
    else:
        flash('Нет вертикальных видео')
        return redirect(url_for('index'))

def get_video_file_path(filename):
    """Получает безопасный путь к видеофайлу"""
    try:
        # Декодируем имя файла
        decoded_filename = unquote(filename)
    except:
        decoded_filename = filename
    
    # Безопасно объединяем пути
    file_path = os.path.join(VIDEO_FOLDER, decoded_filename)
    
    # Проверяем, что файл существует
    if not os.path.exists(file_path):
        # Ищем файл с другим кодированием
        for file in os.listdir(VIDEO_FOLDER):
            if file.split('.')[-1].lower() in ALLOWED_EXTENSIONS:
                try:
                    if unquote(file) == decoded_filename:
                        return os.path.join(VIDEO_FOLDER, file)
                except:
                    if file == decoded_filename:
                        return os.path.join(VIDEO_FOLDER, file)
        return None
    
    return file_path

def get_videos_with_orientation():
    """Получает видео с информацией об ориентации"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename, display_name, orientation 
        FROM videos 
        WHERE banned = 0 
        ORDER BY created_at DESC
    ''')
    videos = cursor.fetchall()
    conn.close()
    
    # Отладочный вывод
    print(f"Найдено видео: {len(videos)}")
    horizontal_count = sum(1 for v in videos if v[2] != 'vertical')
    vertical_count = sum(1 for v in videos if v[2] == 'vertical')
    print(f"Горизонтальных: {horizontal_count}, Вертикальных: {vertical_count}")
    
    return videos

def search_videos_with_orientation(search_term):
    """Поиск видео по названию с возвратом ориентации"""
    search_term = search_term.lower()
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename, display_name, orientation 
        FROM videos 
        WHERE banned = 0 
        AND (LOWER(display_name) LIKE ? OR LOWER(filename) LIKE ?)
        ORDER BY created_at DESC
    ''', ('%' + search_term + '%', '%' + search_term + '%'))
    videos = cursor.fetchall()
    conn.close()
    return videos

def get_sorted_videos(sort_by='filename', sort_order='asc'):
    """Получает видео с сортировкой"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Определяем направление сортировки
    order = 'ASC' if sort_order == 'asc' else 'DESC'
    
    # Выбираем поле для сортировки
    if sort_by == 'filename':
        order_by = f'filename {order}'
    elif sort_by == 'created_at':
        order_by = f'created_at {order}'
    elif sort_by == 'views':
        order_by = f'views {order}'
    elif sort_by == 'likes':
        order_by = f'likes {order}'
    else:
        order_by = f'filename {order}'
    
    cursor.execute(f'''
        SELECT filename, display_name FROM videos 
        WHERE banned = 0 
        ORDER BY {order_by}
    ''')
    videos = cursor.fetchall()
    conn.close()
    
    return videos

def search_videos(search_term):
    """Поиск видео по названию"""
    videos = get_videos()
    search_term = search_term.lower()
    
    results = []
    for filename, display_name in videos:
        # Проверяем, не забанено ли видео
        if not is_video_banned(filename):
            # Ищем в отображаемом имени и оригинальном имени файла
            if (search_term in display_name.lower() or 
                search_term in filename.lower()):
                results.append((filename, display_name))
    
    return results

def init_database():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            filename TEXT PRIMARY KEY,
            orientation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            banned INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            display_name TEXT,
            duration REAL DEFAULT 0,
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            filename TEXT,
            watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reason TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            details TEXT,
            performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS video_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            filename TEXT,
            rating INTEGER,
            rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, filename)
        )
    ''')
    conn.commit()
    conn.close()

def get_video_orientation(filename):
    """Получить ориентацию видео из базы данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT orientation FROM videos WHERE filename = ?', (filename,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_video_orientation(filename, orientation):
    """Установить ориентацию видео в базе данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO videos (filename, orientation, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    ''', (filename, orientation))
    conn.commit()
    conn.close()

def get_all_vertical_videos():
    """Получить все вертикальные видео из базы данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT filename FROM videos WHERE orientation = "vertical" AND banned = 0')
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return result

def add_to_history(session_id, filename):
    """Добавить видео в историю просмотров"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO video_history (session_id, filename)
        VALUES (?, ?)
    ''', (session_id, filename))
    
    # Увеличиваем счетчик просмотров
    cursor.execute('''
        UPDATE videos SET views = views + 1 WHERE filename = ?
    ''', (filename,))
    
    conn.commit()
    conn.close()

def get_watch_history(session_id, limit=10):
    """Получить историю просмотров"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename FROM video_history 
        WHERE session_id = ? 
        ORDER BY watched_at DESC 
        LIMIT ?
    ''', (session_id, limit))
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return result

def scan_videos_folder():
    """Сканирование папки с видео и обновление базы данных с определением ориентации"""
    print("=" * 60)
    print("Сканирование папки с видео и определение ориентации...")
    
    # Проверяем, существует ли папка
    if not os.path.exists(VIDEO_FOLDER):
        print(f"ОШИБКА: Папка {VIDEO_FOLDER} не существует!")
        return
    
    print(f"Сканируемая папка: {VIDEO_FOLDER}")
    print(f"Файлы в папке: {os.listdir(VIDEO_FOLDER)[:10]}...")
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Получаем существующие файлы в базе
    cursor.execute('SELECT filename FROM videos')
    existing_files = {row[0] for row in cursor.fetchall()}
    print(f"Существующих файлов в БД: {len(existing_files)}")
    
    # Получаем актуальные файлы в папке
    current_files = set()
    video_files = []
    
    for file in os.listdir(VIDEO_FOLDER):
        if '.' in file:
            ext = file.rsplit('.', 1)[-1].lower()
            if ext in ALLOWED_EXTENSIONS:
                current_files.add(file)
                video_files.append(file)
    
    print(f"Найдено видеофайлов в папке: {len(video_files)}")
    
    # Добавляем новые файлы с автоматическим определением ориентации
    new_files = current_files - existing_files
    print(f"Новых файлов для добавления: {len(new_files)}")
    
    for filename in new_files:
        # Автоматически определяем ориентацию и размеры
        orientation, width, height, duration = detect_video_info(filename)
        
        # Создаем отображаемое имя
        try:
            display_name = unquote(filename)
        except:
            display_name = filename
        
        cursor.execute('''
            INSERT OR IGNORE INTO videos (filename, orientation, display_name, width, height, duration)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (filename, orientation, display_name, width, height, duration))
        print(f"  Добавлено: {filename} - {orientation} ({width}x{height}) - {duration}сек")
    
    # Для существующих файлов проверяем и обновляем информацию
    for filename in existing_files:
        if filename in current_files:  # Проверяем, что файл все еще существует
            # Проверяем, есть ли информация о размерах и длительности
            cursor.execute('SELECT width, height, duration FROM videos WHERE filename = ?', (filename,))
            result = cursor.fetchone()
            
            if result and (result[0] == 0 or result[1] == 0 or result[2] == 0):
                # Если информация неполная, обновляем
                orientation, width, height, duration = detect_video_info(filename)
                if orientation != "unknown":
                    cursor.execute('''
                        UPDATE videos SET orientation = ?, width = ?, height = ?, duration = ? WHERE filename = ?
                    ''', (orientation, width, height, duration, filename))
                    print(f"  Обновлено: {filename} - {orientation} ({width}x{height}) - {duration}сек")
    
    # Удаляем удаленные файлы
    deleted_files = existing_files - current_files
    for filename in deleted_files:
        cursor.execute('DELETE FROM videos WHERE filename = ?', (filename,))
        print(f"  Удалено: {filename}")
    
    conn.commit()
    conn.close()
    print(f"Сканирование завершено. Новых файлов: {len(new_files)}, удаленных: {len(deleted_files)}")
    print("=" * 60)

@app.route('/admin/redetect_orientations', methods=['POST'])
def admin_redetect_orientations():
    """Принудительное переопределение ориентации всех видео"""
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    # Получаем все видео
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT filename FROM videos')
    all_videos = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    # Переопределяем ориентацию для каждого видео
    updated_count = 0
    for filename in all_videos:
        orientation, width, height, duration = detect_video_info(filename)
        if orientation != "unknown":
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE videos SET orientation = ?, width = ?, height = ?, duration = ? WHERE filename = ?', 
                          (orientation, width, height, duration, filename))
            conn.commit()
            conn.close()
            updated_count += 1
    
    log_admin_action("Переопределение ориентаций", 
                    f"Обновлено {updated_count} видео")
    flash(f'Ориентация переопределена для {updated_count} видео')
    
    return redirect(url_for('admin'))

def background_scanner():
    """Фоновая задача для сканирования папки с видео"""
    while True:
        try:
            scan_videos_folder()
        except Exception as e:
            print(f"Ошибка при сканировании папки: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(1800)  # 30 минут

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def detect_video_info(filename):
    """Автоматически определяет ориентацию, размеры и длительность видео"""
    video_path = os.path.join(VIDEO_FOLDER, filename)
    
    print(f"Определение ориентации для: {filename}")
    
    # Сначала пробуем использовать OpenCV, так как он проще
    if OPENCV_AVAILABLE:
        try:
            cap = cv2.VideoCapture(video_path)
            
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                
                if fps > 0:
                    duration = frame_count / fps
                else:
                    duration = 0
                
                cap.release()
                
                # УЛУЧШЕННЫЙ АЛГОРИТМ ОПРЕДЕЛЕНИЯ ОРИЕНТАЦИИ
                aspect_ratio = width / height if height > 0 else 1
                
                print(f"  Размеры: {width}x{height}, соотношение: {aspect_ratio:.2f}")
                
                # Вертикальное видео: высота значительно больше ширины
                if aspect_ratio < 0.75:  # Более строгий критерий: 3:4 или уже
                    orientation = "vertical"
                # Горизонтальное видео: ширина значительно больше высоты
                elif aspect_ratio > 1.33:  # Более строгий критерий: 4:3 или шире
                    orientation = "horizontal"
                # Квадратное или почти квадратное видео
                else:
                    orientation = "square"
                
                print(f"  Определена ориентация: {orientation}")
                return orientation, width, height, duration
        except Exception as e:
            print(f"  Ошибка при использовании OpenCV для {filename}: {e}")
    
    # Пытаемся использовать ffprobe для получения информации о видео
    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            video_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', env=env)
        
        if result.returncode == 0 and result.stdout:
            info = json.loads(result.stdout)
            
            # Ищем видеопоток
            video_stream = None
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    video_stream = stream
                    break
            
            if video_stream:
                width = video_stream.get('width', 0)
                height = video_stream.get('height', 0)
                
                # Пытаемся получить длительность из формата или потока
                duration_str = info.get('format', {}).get('duration')
                if duration_str:
                    try:
                        duration = float(duration_str)
                    except:
                        duration = 0
                else:
                    duration = 0
                
                # УЛУЧШЕННЫЙ АЛГОРИТМ ОПРЕДЕЛЕНИЯ ОРИЕНТАЦИИ
                if width > 0 and height > 0:
                    aspect_ratio = width / height
                    
                    if aspect_ratio < 0.75:  # Более строгий критерий
                        orientation = "vertical"
                    elif aspect_ratio > 1.33:  # Более строгий критерий
                        orientation = "horizontal"
                    else:
                        orientation = "square"
                else:
                    orientation = "unknown"
                
                print(f"  FFprobe: {orientation} ({width}x{height}, соотношение: {aspect_ratio:.2f}) - {duration:.2f}сек")
                return orientation, width, height, duration
    except Exception as e:
        print(f"  Ошибка при использовании ffprobe для {filename}: {e}")
    
    # Если ничего не сработало, пробуем простой анализ файла
    try:
        filename_lower = filename.lower()
        # УЛУЧШЕННЫЙ ПОИСК ПРИЗНАКОВ В ИМЕНИ ФАЙЛА
        vertical_keywords = ['vertical', 'portrait', 'вертика', 'верт', 'vert', 'tiktok', 'reels', 'shorts', 'story']
        horizontal_keywords = ['horizontal', 'landscape', 'горизонт', 'гор', 'horiz', 'fullhd', 'hd', '4k']
        
        for keyword in vertical_keywords:
            if keyword in filename_lower:
                print(f"  По ключевым словам определена вертикальная ориентация")
                return "vertical", 1080, 1920, 0
        
        for keyword in horizontal_keywords:
            if keyword in filename_lower:
                print(f"  По ключевым словам определена горизонтальная ориентация")
                return "horizontal", 1920, 1080, 0
    except:
        pass
    
    print(f"  Не удалось определить информацию для видео")
    return "unknown", 0, 0, 0

def get_videos():
    """Получает видео из базы данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename, display_name 
        FROM videos 
        WHERE banned = 0 
        ORDER BY created_at DESC
    ''')
    videos = cursor.fetchall()
    conn.close()
    return videos

def get_other_videos(current_filename):
    """Получает список видео, исключая текущее"""
    videos = get_videos()
    return [v for v in videos if v[0] != current_filename]

def safe_filename(filename):
    """Создает безопасное имя файла, сохраняя кириллицу и другие символы"""
    # Получаем расширение файла
    name, ext = os.path.splitext(filename)
    
    # Убираем небезопасные символы, но сохраняем кириллицу и другие Unicode-символы
    # Заменяем только действительно опасные символы
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    
    # Убираем начальные и конечные точки и пробелы
    safe_name = safe_name.strip(' .')
    
    # Если имя стало пустым, используем "video"
    if not safe_name:
        safe_name = 'video'
    
    return safe_name + ext

def get_unique_filename(directory, filename):
    """Генерирует уникальное имя файла, если файл с таким именем уже существует"""
    safe_name = safe_filename(filename)
    base, ext = os.path.splitext(safe_name)
    counter = 1
    new_filename = safe_name
    
    while os.path.exists(os.path.join(directory, new_filename)):
        new_filename = f"{base}_{counter}{ext}"
        counter += 1
    
    return new_filename

def is_video_banned(filename):
    """Проверяет, забанено ли видео"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT banned FROM videos WHERE filename = ?', (filename,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1

def ban_video(filename, reason=""):
    """Блокирует видео"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE videos SET banned = 1 WHERE filename = ?', (filename,))
    cursor.execute('INSERT OR REPLACE INTO banned_videos (filename, reason) VALUES (?, ?)', (filename, reason))
    conn.commit()
    conn.close()

def unban_video(filename):
    """Разблокирует видео"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE videos SET banned = 0 WHERE filename = ?', (filename,))
    cursor.execute('DELETE FROM banned_videos WHERE filename = ?', (filename,))
    conn.commit()
    conn.close()

def delete_video(filename):
    """Удаляет видео"""
    try:
        # Удаляем файл
        file_path = os.path.join(VIDEO_FOLDER, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # Удаляем из базы данных
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM videos WHERE filename = ?', (filename,))
        cursor.execute('DELETE FROM banned_videos WHERE filename = ?', (filename,))
        cursor.execute('DELETE FROM video_ratings WHERE filename = ?', (filename,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Ошибка при удалении видео: {e}")
        return False

def rename_video_file(old_filename, new_filename):
    """Переименовывает видео файл"""
    try:
        old_path = os.path.join(VIDEO_FOLDER, old_filename)
        new_path = os.path.join(VIDEO_FOLDER, new_filename)
        
        if os.path.exists(old_path):
            os.rename(old_path, new_path)
            return True
        return False
    except Exception as e:
        print(f"Ошибка при переименовании файла: {e}")
        return False

def update_video_filename_in_database(old_filename, new_filename):
    """Обновляет имя файла в базе данных"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    try:
        # Обновляем основную таблицу videos
        cursor.execute('UPDATE videos SET filename = ? WHERE filename = ?', (new_filename, old_filename))
        
        # Обновляем историю просмотров
        cursor.execute('UPDATE video_history SET filename = ? WHERE filename = ?', (new_filename, old_filename))
        
        # Обновляем таблицу забаненных видео
        cursor.execute('UPDATE banned_videos SET filename = ? WHERE filename = ?', (new_filename, old_filename))
        
        # Обновляем рейтинги
        cursor.execute('UPDATE video_ratings SET filename = ? WHERE filename = ?', (new_filename, old_filename))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Ошибка при обновлении базы данных: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_video_stats():
    """Получает статистику по видео"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Общее количество видео
    cursor.execute('SELECT COUNT(*) FROM videos')
    total_videos = cursor.fetchone()[0]
    
    # Забаненные видео
    cursor.execute('SELECT COUNT(*) FROM videos WHERE banned = 1')
    banned_videos = cursor.fetchone()[0]
    
    # Вертикальные видео
    cursor.execute('SELECT COUNT(*) FROM videos WHERE orientation = "vertical"')
    vertical_videos = cursor.fetchone()[0]
    
    # Горизонтальные видео
    cursor.execute('SELECT COUNT(*) FROM videos WHERE orientation = "horizontal"')
    horizontal_videos = cursor.fetchone()[0]
    
    # Неопределенные видео
    cursor.execute('SELECT COUNT(*) FROM videos WHERE orientation = "unknown"')
    unknown_videos = cursor.fetchone()[0]
    
    # Общее количество просмотров
    cursor.execute('SELECT SUM(views) FROM videos')
    total_views = cursor.fetchone()[0] or 0
    
    # Популярные видео
    cursor.execute('SELECT filename, views FROM videos ORDER BY views DESC LIMIT 5')
    popular_videos = cursor.fetchall()
    
    # Общее количество лайков и дизлайков
    cursor.execute('SELECT SUM(likes), SUM(dislikes) FROM videos')
    likes_dislikes = cursor.fetchone()
    total_likes = likes_dislikes[0] or 0
    total_dislikes = likes_dislikes[1] or 0
    
    # Общая длительность всех видео
    cursor.execute('SELECT SUM(duration) FROM videos')
    total_duration = cursor.fetchone()[0] or 0
    total_duration_hours = total_duration / 3600
    
    conn.close()
    
    return {
        'total_videos': total_videos,
        'banned_videos': banned_videos,
        'vertical_videos': vertical_videos,
        'horizontal_videos': horizontal_videos,
        'unknown_videos': unknown_videos,
        'total_views': total_views,
        'total_likes': total_likes,
        'total_dislikes': total_dislikes,
        'total_duration_hours': round(total_duration_hours, 2),
        'popular_videos': popular_videos
    }

def get_all_videos_with_info():
    """Получает все видео с дополнительной информацией"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT filename, orientation, banned, views, likes, dislikes, created_at, duration, width, height 
        FROM videos 
        ORDER BY created_at DESC
    ''')
    videos = cursor.fetchall()
    conn.close()
    return videos

def get_banned_videos():
    """Получает список забаненных видео"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT v.filename, v.orientation, v.views, b.reason, b.banned_at 
        FROM videos v 
        JOIN banned_videos b ON v.filename = b.filename 
        ORDER BY b.banned_at DESC
    ''')
    videos = cursor.fetchall()
    conn.close()
    return videos

def log_admin_action(action, details):
    """Логирует действия администратора"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO admin_logs (action, details) VALUES (?, ?)', (action, details))
    conn.commit()
    conn.close()

def get_admin_logs(limit=50):
    """Получает логи администратора"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admin_logs ORDER BY performed_at DESC LIMIT ?', (limit,))
    logs = cursor.fetchall()
    conn.close()
    return logs

def force_reorientation(filename, orientation):
    """Принудительно устанавливает ориентацию видео"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE videos SET orientation = ? WHERE filename = ?', (orientation, filename))
    conn.commit()
    conn.close()

def get_system_info():
    """Получает информацию о системе"""
    try:
        # Информация о диске
        # Замените эту строку:
        # disk_usage = psutil.disk_usage(VIDEO_FOLDER)
        # На этот блок:
        try:
            # Пытаемся использовать стандартный метод
            disk_usage = psutil.disk_usage(VIDEO_FOLDER)
        except SystemError:
            # Если возникает ошибка Python 3.12+, используем обходной путь
            import ctypes
            import os
            import sys

            # Получаем диск из пути к папке с видео (например, 'E:\\')
            drive = os.path.splitdrive(VIDEO_FOLDER)[0]

            if sys.platform == 'win32':
                # Используем WinAPI GetDiskFreeSpaceEx для Windows
                free_bytes = ctypes.c_ulonglong()
                total_bytes = ctypes.c_ulonglong()
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p(drive),
                    None,
                    ctypes.pointer(total_bytes),
                    ctypes.pointer(free_bytes)
                )

                disk_total_gb = total_bytes.value / (1024**3)
                disk_free_gb = free_bytes.value / (1024**3)
                disk_used_gb = disk_total_gb - disk_free_gb
                disk_percent = (disk_used_gb / disk_total_gb * 100) if disk_total_gb > 0 else 0

                # Создаем объект, похожий на namedtuple от psutil
                class SimpleDiskUsage:
                    def __init__(self, total, used, free, percent):
                        self.total = total
                        self.used = used
                        self.free = free
                        self.percent = percent

                disk_usage = SimpleDiskUsage(
                    total=disk_total_gb * (1024**3),  # Возвращаем в байтах для совместимости
                    used=disk_used_gb * (1024**3),
                    free=disk_free_gb * (1024**3),
                    percent=disk_percent
                )
            else:
                # Для Linux/Mac используем команду df
                import subprocess
                result = subprocess.run(['df', '-k', VIDEO_FOLDER], 
                                      capture_output=True, text=True)
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 5:
                        total_kb = int(parts[1])
                        used_kb = int(parts[2])
                        free_kb = int(parts[3])
                        percent = int(parts[4].replace('%', ''))

                        class SimpleDiskUsage:
                            def __init__(self, total, used, free, percent):
                                self.total = total * 1024  # Конвертируем в байты
                                self.used = used * 1024
                                self.free = free * 1024
                                self.percent = percent

                        disk_usage = SimpleDiskUsage(total_kb, used_kb, free_kb, percent)
                    else:
                        raise Exception("Не удалось получить информацию о диске")
                else:
                    raise Exception("Не удалось получить информацию о диске")
        disk_total_gb = disk_usage.total / (1024**3)
        disk_used_gb = disk_usage.used / (1024**3)
        disk_free_gb = disk_usage.free / (1024**3)
        disk_percent = disk_usage.percent
        
        # Информация о памяти
        memory = psutil.virtual_memory()
        memory_total_gb = memory.total / (1024**3)
        memory_used_gb = memory.used / (1024**3)
        memory_percent = memory.percent
        
        # Информация о CPU
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # IP адрес
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
        except:
            local_ip = "Не удалось определить"
        
        return {
            'disk_total': round(disk_total_gb, 2),
            'disk_used': round(disk_used_gb, 2),
            'disk_free': round(disk_free_gb, 2),
            'disk_percent': disk_percent,
            'memory_total': round(memory_total_gb, 2),
            'memory_used': round(memory_used_gb, 2),
            'memory_percent': memory_percent,
            'cpu_percent': cpu_percent,
            'hostname': hostname,
            'local_ip': local_ip,
            'video_folder': VIDEO_FOLDER
        }
    except Exception as e:
        print(f"Ошибка при получении системной информации: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'disk_total': 0,
            'disk_used': 0,
            'disk_free': 0,
            'disk_percent': 0,
            'memory_total': 0,
            'memory_used': 0,
            'memory_percent': 0,
            'cpu_percent': 0,
            'hostname': "Неизвестно",
            'local_ip': "Не удалось определить",
            'video_folder': VIDEO_FOLDER
        }

@app.before_request
def before_request():
    """Инициализация сессии перед каждым запросом"""
    if 'session_id' not in session:
        session['session_id'] = os.urandom(16).hex()

@app.route('/')
def index():
    search_term = request.args.get('search', '').strip()
    
    if search_term:
        videos = search_videos_with_orientation(search_term)
    else:
        videos = get_videos_with_orientation()
    
    return render_template('index.html', 
                         videos=videos, 
                         search_term=search_term)
#def index():
#    search_term = request.args.get('search', '').strip()
#    
#    if search_term:
#        videos = search_videos_with_orientation(search_term)
#        return render_template('index.html', 
#                             videos=videos, 
#                             search_term=search_term,
#                             show_separately=False)
#    else:
#        # Без поиска разделяем видео
#        videos = get_videos_with_orientation()
#        
#        # Разделяем на горизонтальные и вертикальные
#        horizontal_videos = []
#        vertical_videos = []
#        
#        for video in videos:
#            filename, display_name, orientation = video
#            if orientation == 'vertical':
#                vertical_videos.append(video)
#            else:
#                horizontal_videos.append(video)
#        
#        return render_template('index.html', 
#                             horizontal_videos=horizontal_videos,
#                             vertical_videos=vertical_videos,
#                             search_term=search_term,
#                             show_separately=True)

@app.route('/video/<filename>', endpoint='serve_video')  # Добавьте endpoint явно
def serve_video(filename):  # Изменено с video на serve_video
    """Маршрут для отдачи видеофайлов"""
    # Проверяем, не забанено ли видео
    if is_video_banned(filename):
        return jsonify({'error': 'Video is banned'}), 403
    
    # Проверяем, существует ли файл
    file_path = get_video_file_path(filename)
    if file_path is None or not os.path.exists(file_path):
        return jsonify({'error': 'Video not found'}), 404
    
    # Определяем MIME-тип
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    mime_types = {
        'mp4': 'video/mp4',
        'avi': 'video/x-msvideo',
        'mov': 'video/quicktime',
        'mkv': 'video/x-matroska',
        'webm': 'video/webm'
    }
    
    mime_type = mime_types.get(ext, 'application/octet-stream')
    
    return send_file(
        file_path,
        mimetype=mime_type,
        as_attachment=False,
        conditional=True
    )

@app.route('/watch/<filename>')
def watch_video(filename):
    # Проверяем, не забанено ли видео
    if is_video_banned(filename):
        flash('Доступ к этому видео запрещен администратором')
        return redirect(url_for('index'))
    
    # Проверяем, существует ли файл
    file_path = get_video_file_path(filename)
    if file_path is None or not os.path.exists(file_path):
        flash('Видео не найдено')
        return redirect(url_for('index'))
    
    # Декодируем имя файла для отображения
    try:
        display_name = unquote(filename)
    except:
        display_name = filename
    
    # Добавляем в историю просмотров
    add_to_history(session['session_id'], filename)
    
    # Получаем ориентацию видео из базы данных
    orientation = get_video_orientation(filename)
    
    # Если видео вертикальное - перенаправляем на специальную страницу
    if orientation == 'vertical':
        return redirect(url_for('vertical_video', filename=filename))
    
    # Получаем список других видео для рекомендаций (только для горизонтальных)
    other_videos = get_other_videos(filename)
    
    return render_template('watch.html', 
                         filename=filename,
                         display_name=display_name,
                         other_videos=other_videos[:5])  # Ограничиваем до 5 рекомендаций

@app.route('/vertical/<filename>')
def vertical_video(filename):
    # Проверяем, не забанено ли видео
    if is_video_banned(filename):
        flash('Доступ к этому видео запрещен администратором')
        return redirect(url_for('index'))
    
    # Проверяем, существует ли файл
    file_path = get_video_file_path(filename)
    if file_path is None or not os.path.exists(file_path):
        flash('Видео не найдено')
        return redirect(url_for('index'))
    
    # Декодируем имя файла для отображения
    try:
        display_name = unquote(filename)
    except:
        display_name = filename
    
    # Добавляем в историю просмотров
    add_to_history(session['session_id'], filename)
    
    # Проверяем, что видео действительно вертикальное
    orientation = get_video_orientation(filename)
    if orientation != 'vertical':
        return redirect(url_for('watch_video', filename=filename))
    
    return render_template('vertical_watch.html', 
                         filename=filename,
                         display_name=display_name)

@app.route('/api/random_vertical_video')
def random_vertical_video():
    """API для получения случайного вертикального видео"""
    vertical_videos = get_all_vertical_videos()
    
    # Получаем текущее видео из параметра запроса
    current_filename = request.args.get('current')
    if current_filename:
        try:
            current_filename = unquote(current_filename)
        except:
            pass
    
    # Исключаем текущее видео из списка
    if current_filename and current_filename in vertical_videos:
        vertical_videos = [v for v in vertical_videos if v != current_filename]
    
    if vertical_videos:
        random_video = random.choice(vertical_videos)
        return jsonify({'filename': random_video})
    else:
        return jsonify({'error': 'No vertical videos found'}), 404

@app.route('/api/vertical_videos_list')
def vertical_videos_list():
    """API для получения списка всех вертикальных видео в алфавитном порядке"""
    vertical_videos = get_all_vertical_videos()
    # Сортируем видео по алфавиту
    sorted_videos = sorted(vertical_videos)
    return jsonify({'videos': sorted_videos})

@app.route('/settings')
def settings():
    return render_template('settings.html')

@app.route('/admin')
def admin():
    global admin_access
    if not admin_access:
        return redirect(url_for('settings'))
    
    # Получаем статистику и список видео для админки
    stats = get_video_stats()
    videos = get_all_videos_with_info()
    banned_videos = get_banned_videos()
    logs = get_admin_logs(20)
    system_info = get_system_info()
    
    return render_template('admin.html', 
                         stats=stats, 
                         videos=videos, 
                         banned_videos=banned_videos,
                         logs=logs,
                         system_info=system_info)

@app.route('/grant_admin')
def grant_admin():
    global admin_access
    admin_access = True
    log_admin_action("Вход в админ-панель", f"Сессия: {session['session_id']}")
    flash('Админский доступ предоставлен!')
    return redirect(url_for('admin'))

@app.route('/admin/ban_video', methods=['POST'])
def admin_ban_video():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    filename = request.form.get('filename')
    reason = request.form.get('reason', '')
    
    if filename:
        ban_video(filename, reason)
        log_admin_action("Блокировка видео", f"Файл: {filename}, Причина: {reason}")
        flash(f'Видео {filename} заблокировано')
    
    return redirect(url_for('admin'))

@app.route('/admin/unban_video', methods=['POST'])
def admin_unban_video():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    filename = request.form.get('filename')
    
    if filename:
        unban_video(filename)
        log_admin_action("Разблокировка видео", f"Файл: {filename}")
        flash(f'Видео {filename} разблокировано')
    
    return redirect(url_for('admin'))

@app.route('/admin/delete_video', methods=['POST'])
def admin_delete_video():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    filename = request.form.get('filename')
    
    if filename:
        if delete_video(filename):
            log_admin_action("Удаление видео", f"Файл: {filename}")
            flash(f'Видео {filename} удалено')
        else:
            flash(f'Ошибка при удалении видео {filename}', 'error')
    
    return redirect(url_for('admin'))

@app.route('/admin/rename_video', methods=['POST'])
def admin_rename_video():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    old_filename = request.form.get('old_filename')
    new_filename = request.form.get('new_filename')
    
    if not old_filename or not new_filename:
        flash('Не указано старое или новое имя файла', 'error')
        return redirect(url_for('admin'))
    
    # Проверяем, что новое имя не пустое
    new_filename = new_filename.strip()
    if not new_filename:
        flash('Новое имя файла не может быть пустым', 'error')
        return redirect(url_for('admin'))
    
    # Добавляем расширение, если его нет
    if '.' not in new_filename:
        old_ext = os.path.splitext(old_filename)[1]
        new_filename += old_ext
    
    # Проверяем, что файл с новым именем не существует
    new_file_path = os.path.join(VIDEO_FOLDER, new_filename)
    if os.path.exists(new_file_path):
        flash(f'Файл с именем {new_filename} уже существует', 'error')
        return redirect(url_for('admin'))
    
    # Переименовываем файл
    if rename_video_file(old_filename, new_filename):
        # Обновляем базу данных
        if update_video_filename_in_database(old_filename, new_filename):
            log_admin_action("Переименование видео", f"Старое имя: {old_filename}, Новое имя: {new_filename}")
            flash(f'Видео успешно переименовано: {old_filename} → {new_filename}')
        else:
            # Если не удалось обновить БД, возвращаем старое имя файла
            rename_video_file(new_filename, old_filename)
            flash('Ошибка при обновлении базы данных', 'error')
    else:
        flash('Ошибка при переименовании файла', 'error')
    
    return redirect(url_for('admin'))

@app.route('/admin/force_reorientation', methods=['POST'])
def admin_force_reorientation():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    filename = request.form.get('filename')
    orientation = request.form.get('orientation')
    
    if filename and orientation in ['horizontal', 'vertical']:
        force_reorientation(filename, orientation)
        log_admin_action("Принудительное изменение ориентации", 
                        f"Файл: {filename}, Ориентация: {orientation}")
        flash(f'Ориентация видео {filename} изменена на {orientation}')
    
    return redirect(url_for('admin'))

@app.route('/admin/clear_logs', methods=['POST'])
def admin_clear_logs():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM admin_logs')
    conn.commit()
    conn.close()
    
    log_admin_action("Очистка логов", "Все логи администратора очищены")
    flash('Логи администратора очищены')
    
    return redirect(url_for('admin'))

@app.route('/admin/rescan_videos', methods=['POST'])
def admin_rescan_videos():
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    # Запускаем сканирование в отдельном потоке
    threading.Thread(target=scan_videos_folder, daemon=True).start()
    
    log_admin_action("Принудительное сканирование видео", "Запущено сканирование папки с видео")
    flash('Сканирование видео запущено')
    
    return redirect(url_for('admin'))

@app.route('/api/previous_vertical_video')
def previous_vertical_video():
    """API для получения предыдущего вертикального видео из истории"""
    current_filename = request.args.get('current')
    if current_filename:
        try:
            current_filename = unquote(current_filename)
        except:
            pass
    
    # Получаем историю просмотров
    history = get_watch_history(session['session_id'])
    
    if current_filename in history:
        current_index = history.index(current_filename)
        if current_index > 0:
            previous_video = history[current_index - 1]
            return jsonify({'filename': previous_video})
    
    # Если предыдущего видео нет, возвращаем случайное
    vertical_videos = get_all_vertical_videos()
    if vertical_videos:
        random_video = random.choice(vertical_videos)
        return jsonify({'filename': random_video})
    else:
        return jsonify({'error': 'No vertical videos found'}), 404

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "Не удалось определить IP"

@app.route('/NanBelle_Help_11154786358')
def help_NanBelle():
    return render_template('help.html')

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Файл не выбран')
            return redirect(request.url)
        
        file = request.files['file']
        orientation = request.form.get('orientation', 'auto')
        
        if file.filename == '':
            flash('Файл не выбран')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            # Сохраняем оригинальное название с поддержкой кириллицы
            original_name = file.filename
            unique_filename = get_unique_filename(VIDEO_FOLDER, original_name)
            
            file_path = os.path.join(VIDEO_FOLDER, unique_filename)
            file.save(file_path)
            
            # Определяем информацию о видео
            detected_orientation, width, height, duration = detect_video_info(unique_filename)
            
            # Используем выбранную ориентацию или определенную автоматически
            if orientation == 'auto':
                final_orientation = detected_orientation
            else:
                final_orientation = orientation
            
            # Сохраняем информацию в базе данных
            conn = sqlite3.connect(DATABASE_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO videos 
                (filename, orientation, display_name, width, height, duration, banned, views, likes, dislikes)
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0)
            ''', (unique_filename, final_orientation, original_name, width, height, duration))
            conn.commit()
            conn.close()
            
            log_admin_action("Загрузка видео", f"Файл: {unique_filename}, Ориентация: {final_orientation}, Размеры: {width}x{height}, Длительность: {duration}сек")
            flash('Файл успешно загружен и проанализирован')
            return redirect(url_for('index'))
        else:
            flash('Недопустимый тип файла. Разрешены: mp4, avi, mov, mkv, webm')
    
    return render_template('upload.html')

@app.route('/admin/fix_orientations', methods=['POST'])
def admin_fix_orientations():
    """Исправление ориентации видео, которые неправильно определены"""
    global admin_access
    if not admin_access:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    # Получаем все видео
    with db_lock:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT filename, orientation FROM videos')
        all_videos = cursor.fetchall()
        conn.close()
    
    # Исправляем ориентацию для каждого видео
    fixed_count = 0
    for filename, current_orientation in all_videos:
        # Определяем правильную ориентацию
        orientation, width, height, duration = detect_video_info(filename)
        
        # Если ориентация определена и отличается от текущей
        if orientation != "unknown" and orientation != current_orientation:
            with db_lock:
                conn = sqlite3.connect(DATABASE_PATH)
                cursor = conn.cursor()
                cursor.execute('UPDATE videos SET orientation = ?, width = ?, height = ?, duration = ? WHERE filename = ?', 
                              (orientation, width, height, duration, filename))
                conn.commit()
                conn.close()
                fixed_count += 1
                print(f"Исправлена ориентация: {filename} - было '{current_orientation}', стало '{orientation}'")
    
    # log_admin_action("Исправление ориентаций", 
    #                 f"Исправлено {fixed_count} видео")
    flash(f'Ориентация исправлена для {fixed_count} видео')
    
    return redirect(url_for('index'))  # Возвращаем на главную страницу

if __name__ == '__main__':
    # Инициализация базы данных
    init_database()
    
    # Запуск фонового сканирования
    scanner_thread = threading.Thread(target=background_scanner, daemon=True)
    scanner_thread.start()
    
    local_ip = get_local_ip()
    print("=" * 60)
    print(f"Сервер запускается...")
    print(f"Главная: http://{local_ip}:5000")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
