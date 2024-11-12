from flask import Flask, render_template, Response
import cv2
from ultralytics import YOLO
import numpy as np
import requests
import firebase_admin
from firebase_admin import credentials, storage, db
import os
import random
from datetime import datetime
import json
import base64

# Inicialización de Firebase usando credenciales en base64 desde una variable de entorno
firebase_credentials_b64 = os.getenv('FIREBASE_CREDENTIALS')
if firebase_credentials_b64:
    # Decodifica las credenciales y carga el certificado desde la cadena base64
    firebase_credentials = json.loads(base64.b64decode(firebase_credentials_b64))
    cred = credentials.Certificate(firebase_credentials)
    firebase_admin.initialize_app(cred, {
        'storageBucket': 'laura-24a17.appspot.com',
        'databaseURL': 'https://laura-24a17-default-rtdb.firebaseio.com'
    })
    print("Firebase inicializado correctamente.")
else:
    print("Error: Credenciales de Firebase no encontradas en las variables de entorno.")

# Cargar el modelo YOLO
model = YOLO("yolov8n.pt")
classesFile = "coco.names"
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')
    COLORS = np.random.uniform(0, 255, size=(len(classes), 3))

# Configuración de la URL de la ESP32-CAM
url = 'http://192.168.137.117/640x480.jpg'  # IP de tu ESP32-CAM (asegúrate de que sea accesible desde la nube)

# Configuración de Telegram
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')  # ID del chat de Telegram desde variable de entorno
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # Token del bot de Telegram desde variable de entorno

detection_start_time = None
last_movement_time = datetime.now()

# Simulación de sensor PIR
def detect_motion():
    return random.choice([0, 1])  # Simula movimiento aleatorio

# Función para subir fotos a Firebase
def upload_photo_to_firebase(photo_path):
    if not os.path.exists(photo_path):
        print(f"Error: No se encontró el archivo {photo_path}")
        return None
    try:
        bucket = storage.bucket()
        blob = bucket.blob(f'fotos/{os.path.basename(photo_path)}')
        blob.upload_from_filename(photo_path)
        print(f"Foto subida a Firebase: {photo_path}")
        blob.make_public()
        return blob.public_url
    except Exception as e:
        print(f"Error al subir la foto a Firebase: {e}")
        return None

def save_photo_data_to_firebase(photo_url, timestamp):
    if photo_url:
        try:
            ref = db.reference('detecciones')
            ref.push({
                'url_foto': photo_url,
                'fecha_hora': timestamp
            })
            print("Datos guardados en Firebase.")
        except Exception as e:
            print(f"Error al guardar en Firebase: {e}")

def send_photo_to_telegram(photo_path, chat_id, bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    if not os.path.exists(photo_path):
        print(f"Error: No se encontró el archivo {photo_path}")
        return
    try:
        with open(photo_path, 'rb') as photo:
            payload = {'chat_id': chat_id}
            files = {'photo': photo}
            response = requests.post(url, data=payload, files=files)
            if response.status_code == 200:
                print("Foto enviada con éxito.")
            else:
                print(f"Error al enviar foto: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error al enviar foto a Telegram: {e}")

def send_alert_to_telegram(alert_message, chat_id, bot_token):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': alert_message}
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("Mensaje de alerta enviado a Telegram.")
        else:
            print(f"Error al enviar mensaje a Telegram: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

def draw_box(frame, box, label, color):
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    label_size, base_line = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    y1 = max(y1, label_size[1])
    cv2.rectangle(frame, (x1, y1 - label_size[1]), (x1 + label_size[0], y1 + base_line), color, cv2.FILLED)
    cv2.putText(frame, label, (x1, y1), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

# Flask application
app = Flask(__name__)

def generate_frames():
    global detection_start_time, last_movement_time
    while True:
        # Captura una imagen desde el ESP32-CAM
        try:
            # Obtiene la imagen de la cámara ESP32-CAM
            resp = requests.get(url)
            if resp.status_code != 200:
                print("Error al conectar con la cámara.")
                break
            # Convierte la imagen en un formato legible por OpenCV
            frame = np.array(bytearray(resp.content), dtype=np.uint8)
            frame = cv2.imdecode(frame, -1)
        except Exception as e:
            print(f"Error al capturar imagen: {e}")
            break

        # Simulación del sensor PIR
        movement_detected = detect_motion()
        if movement_detected:
            last_movement_time = datetime.now()
            ref = db.reference('movimientos')
            ref.push({
                'movimiento': 'Movimiento detectado',
                'fecha_hora': last_movement_time.strftime('%Y-%m-%d %H:%M:%S')
            })
            send_alert_to_telegram("Movimiento detectado", CHAT_ID, BOT_TOKEN)

        # Detección de objetos
        results = model.predict(frame, stream=True, verbose=False)
        person_detected = False
        for result in results:
            boxes = result.boxes
            for box in boxes:
                r = box.xyxy[0]
                c = box.cls
                if classes[int(c)] == "persona":
                    person_detected = True
                    if detection_start_time is None:
                        detection_start_time = datetime.now()
                color = tuple(COLORS[int(c)])
                draw_box(frame, r, label=classes[int(c)], color=color)

        # Almacenar y enviar notificaciones si se detecta una persona
        if person_detected:
            now = datetime.now()
            if detection_start_time and (now - detection_start_time).total_seconds() > 5:
                timestamp = now.strftime('%Y%m%d_%H%M%S')
                photo_path = f'/tmp/captura_foto_{timestamp}.jpg'
                cv2.imwrite(photo_path, frame)
                photo_url = upload_photo_to_firebase(photo_path)
                save_photo_data_to_firebase(photo_url, timestamp)
                send_photo_to_telegram(photo_path, CHAT_ID, BOT_TOKEN)
                detection_start_time = None
        else:
            detection_start_time = None

        # Codifica el fotograma en JPEG para enviarlo al navegador
        _, jpeg = cv2.imencode('.jpg', frame)
        frame_jpeg = jpeg.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_jpeg + b'\r\n\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))  # Usa el puerto 5000 o el puerto proporcionado por Render
    app.run(debug=True, host='0.0.0.0', port=port)

