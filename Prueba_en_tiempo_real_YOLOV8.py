from flask import Flask, render_template, Response
import cv2
from ultralytics import YOLO
import numpy as np
import requests
import firebase_admin
from firebase_admin import credentials, storage, db
import os
from datetime import datetime
import threading
import time

# Inicialización de Firebase usando el archivo de credenciales
firebase_credentials_path = "D:\\laura-24a17-firebase-adminsdk-jswzg-3e63b04f07.json"
if os.path.exists(firebase_credentials_path):
    cred = credentials.Certificate(firebase_credentials_path)
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'laura-24a17.appspot.com',
        'databaseURL': 'https://laura-24a17-default-rtdb.firebaseio.com'
    })
    print("Firebase inicializado correctamente.")
else:
    raise FileNotFoundError(f"No se encontró el archivo de credenciales en la ruta {firebase_credentials_path}.")

# Cargar el modelo YOLO
model = YOLO("yolov8n.pt")
classesFile = "coco.names"
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')
    COLORS = np.random.uniform(0, 255, size=(len(classes), 3))

# Configuración de la URL de la ESP32-CAM
url = 'http://192.168.137.117/640x480.jpg'

# Configuración de Telegram
CHAT_ID = '6452057967'
BOT_TOKEN = '7240445682:AAFxrSGBk1uhT37_KNC8w28TZGMW8kxZqf8'

detection_start_time = None

# Configuración de OpenWeatherMap
WEATHER_API_KEY = "4a92eda98011245f51fba0809a556998"
WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather"
CITY = "Puno,PE"

# Función para obtener la temperatura de Puno
def get_puno_temperature():
    try:
        params = {"q": CITY, "appid": WEATHER_API_KEY, "units": "metric"}
        response = requests.get(WEATHER_API_URL, params=params, timeout=10)
        response.raise_for_status()
        temperature = response.json()["main"]["temp"]
        print(f"Temperatura en Puno: {temperature}°C")
        return temperature
    except requests.RequestException as e:
        print(f"Error al obtener la temperatura: {e}")
        return None

# Hilo para actualizar la temperatura cada 10 minutos
def update_temperature_periodically():
    while True:
        get_puno_temperature()
        time.sleep(600)

# Función para subir fotos a Firebase
def upload_photo_to_firebase(photo_path):
    if not os.path.exists(photo_path):
        print(f"Error: No se encontró el archivo {photo_path}")
        return None
    try:
        bucket = storage.bucket()
        blob = bucket.blob(f'fotos/{os.path.basename(photo_path)}')
        blob.upload_from_filename(photo_path)
        blob.make_public()
        print(f"Foto subida a Firebase: {photo_path}")
        return blob.public_url
    except Exception as e:
        print(f"Error al subir la foto a Firebase: {e}")
        return None

# Función para guardar datos en Firebase
def save_detection_to_firebase(photo_url, timestamp, temperature):
    if photo_url and temperature is not None:
        try:
            ref = db.reference('detecciones')
            ref.push({
                'url_foto': photo_url,
                'fecha_hora': timestamp,
                'temperatura': temperature
            })
            print("Datos guardados en Firebase.")
        except Exception as e:
            print(f"Error al guardar en Firebase: {e}")

# Función para enviar fotos a Telegram
def send_photo_to_telegram(photo_path, chat_id, bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    if not os.path.exists(photo_path):
        print(f"Error: No se encontró el archivo {photo_path}")
        return
    try:
        with open(photo_path, 'rb') as photo:
            response = requests.post(url, data={'chat_id': chat_id}, files={'photo': photo})
            if response.status_code == 200:
                print("Foto enviada con éxito.")
            else:
                print(f"Error al enviar foto: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error al enviar foto a Telegram: {e}")

# Función para dibujar cajas en la imagen
def draw_box(frame, box, label, color):
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

# Flask application
app = Flask(__name__)

def generate_frames():
    global detection_start_time
    while True:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            frame = np.array(bytearray(resp.content), dtype=np.uint8)
            frame = cv2.imdecode(frame, -1)

            if frame is None:
                print("Error: No se pudo decodificar la imagen.")
                continue
        except requests.RequestException as e:
            print(f"Error al capturar imagen: {e}")
            time.sleep(2)  # Pausa antes de reintentar
            continue

        results = model.predict(frame, stream=True, verbose=False)
        person_detected = False
        for result in results:
            for box, cls in zip(result.boxes.xyxy, result.boxes.cls):
                if classes[int(cls)] == "persona":
                    person_detected = True
                    if detection_start_time is None:
                        detection_start_time = datetime.now()
                color = tuple(COLORS[int(cls)])
                draw_box(frame, box, label=classes[int(cls)], color=color)

        if person_detected:
            now = datetime.now()
            if detection_start_time and (now - detection_start_time).total_seconds() >= 5:
                timestamp = now.strftime('%Y%m%d_%H%M%S')
                photo_path = f'captura_foto_{timestamp}.jpg'
                cv2.imwrite(photo_path, frame)
                photo_url = upload_photo_to_firebase(photo_path)
                temperature = get_puno_temperature()
                save_detection_to_firebase(photo_url, timestamp, temperature)
                send_photo_to_telegram(photo_path, CHAT_ID, BOT_TOKEN)
                detection_start_time = None
        else:
            detection_start_time = None

        _, jpeg = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n\r\n')

@app.route('/')
def index():
    temperature = get_puno_temperature()
    return render_template('index.html', temperature=temperature)

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    threading.Thread(target=update_temperature_periodically, daemon=True).start()
    app.run(debug=True, host='0.0.0.0', port=5000)
