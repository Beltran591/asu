from tkinter import *
from PIL import Image, ImageTk
import cv2
from ultralytics import YOLO
import numpy as np
import requests
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, storage, db
import os
import random  # Usado para simular el estado del PIR

try:
    from machine import Pin  # Para manejar el GPIO en ESP32
except ImportError:
    print("No se ha detectado un entorno compatible con ESP32. Usando simulación de PIR.")

# Inicialización de Firebase
import os
import base64
import json
from firebase_admin import credentials, initialize_app, storage, db

# Inicialización de Firebase con credenciales desde variable de entorno
firebase_credentials = os.environ.get("FIREBASE_CREDENTIALS")
if firebase_credentials:
    cred_dict = json.loads(base64.b64decode(firebase_credentials).decode('utf-8'))
    cred = credentials.Certificate(cred_dict)
    initialize_app(cred, {
        'storageBucket': 'laura-24a17.appspot.com',
        'databaseURL': 'https://laura-24a17-default-rtdb.firebaseio.com'
    })
else:
    print("Error: Credenciales de Firebase no encontradas en variables de entorno.")


# Cargar el modelo YOLO
model = YOLO("yolov8n.pt")
classesFile = "coco.names"
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')
    COLORS = np.random.uniform(0, 255, size=(len(classes), 3))

# Captura de video
url = 'http://192.168.137.117/640x480.jpg'
cap = cv2.VideoCapture(url)

# Configuración de Telegram
CHAT_ID = '6452057967'
BOT_TOKEN = '7240445682:AAFxrSGBk1uhT37_KNC8w28TZGMW8kxZqf8'

detection_start_time = None
last_movement_time = datetime.now()
photos_data = []

# Configuración del pin del sensor PIR
try:
    PIR_PIN = Pin(13, Pin.IN)  # Configurar el pin GPIO 13 como entrada
    def detect_motion():
        return PIR_PIN.value()
except NameError:
    print("Usando simulación de sensor PIR.")
    def detect_motion():
        return random.choice([0, 1])  # Simula movimiento aleatorio

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

def on_closing():
    root.quit()
    cap.release()
    root.destroy()

def update_dashboard():
    for widget in dashboard_frame.winfo_children():
        widget.destroy()
    for photo_data in photos_data:
        img_label = Label(dashboard_frame)
        img = Image.open(photo_data['url_foto'])
        img.thumbnail((100, 100))
        tk_image = ImageTk.PhotoImage(img)
        img_label.configure(image=tk_image)
        img_label.image = tk_image
        img_label.grid(row=len(photos_data), column=0, padx=5, pady=5)
        info_label = Label(dashboard_frame, text=photo_data['fecha_hora'])
        info_label.grid(row=len(photos_data) - 1, column=1, padx=5, pady=5)

def callback():
    global detection_start_time, last_movement_time
    cap.open(url)
    ret, frame = cap.read()
    if ret:
        movement_detected = detect_motion()
        if movement_detected:
            last_movement_time = datetime.now()
            # Enviar alerta de movimiento detectado a Firebase y Telegram
            ref = db.reference('movimientos')
            ref.push({
                'movimiento': 'Movimiento detectado',
                'fecha_hora': last_movement_time.strftime('%Y-%m-%d %H:%M:%S')
            })
            print("Movimiento detectado guardado en Firebase.")
            send_alert_to_telegram("Movimiento detectado", CHAT_ID, BOT_TOKEN)
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
                    print("¡Persona detectada!")
                color = tuple(COLORS[int(c)])
                draw_box(frame, r, label=classes[int(c)], color=color)
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img)
        tkimage = ImageTk.PhotoImage(img)
        label.configure(image=tkimage)
        label.image = tkimage
        if person_detected:
            now = datetime.now()
            if detection_start_time and (now - detection_start_time).total_seconds() > 5:
                timestamp = now.strftime('%Y%m%d_%H%M%S')
                photo_path = f'captura_foto_{timestamp}.jpg'
                cv2.imwrite(photo_path, frame)
                photo_url = upload_photo_to_firebase(photo_path)
                save_photo_data_to_firebase(photo_url, timestamp)
                photos_data.append({'url_foto': photo_path, 'fecha_hora': timestamp})
                update_dashboard()
                send_photo_to_telegram(photo_path, CHAT_ID, BOT_TOKEN)
                detection_start_time = None
        else:
            detection_start_time = None
        if datetime.now() - last_movement_time > timedelta(seconds=10):
            ref = db.reference('alertas')
            ref.push({
                'alerta': 'No se detecta movimiento',
                'fecha_hora': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            send_alert_to_telegram("No se detecta movimiento en los últimos 10 segundos", CHAT_ID, BOT_TOKEN)
            print("Alerta de ausencia de movimiento enviada a Firebase.")
        root.after(1, callback)
    else:
        on_closing()

root = Tk()
root.protocol("WM_DELETE_WINDOW", on_closing)
root.title("Vision Artificial")

label = Label(root)
label.grid(row=1, padx=20, pady=20)

dashboard_frame = Frame(root)
dashboard_frame.grid(row=2, padx=20, pady=20)

root.after(1, callback)
root.mainloop()

