from tkinter import *
from PIL import Image, ImageTk
import cv2
from ultralytics import YOLO
import numpy as np
import requests
from datetime import datetime
import firebase_admin 
from firebase_admin import credentials, storage, db
import os

import firebase_admin
from firebase_admin import credentials, storage, db



# Inicializar Firebase
cred = credentials.Certificate("D:\\asu\\rycf-6e380-firebase-adminsdk-bsiuh-f8a8052dad.json")
firebase_admin.initialize_app(cred, {
    'storageBucket': 'rycf-6e380.appspot.com',  # Reemplaza con el nombre de tu bucket de almacenamiento
    'databaseURL': 'https://rycf-6e380-default-rtdb.firebaseio.com/'  # Reemplaza con la URL de tu base de datos
})

# Puedes continuar con tus operaciones de Firebase aquí


# Configuración YOLO y clases
model = YOLO("yolov8n.pt")
classesFile = "coco.names"
with open(classesFile, 'rt') as f:
    classes = f.read().rstrip('\n').split('\n')
    COLORS = np.random.uniform(0, 255, size=(len(classes), 3))

# Parámetros de conexión
url = 'http://192.168.137.117/640x480.jpg'
cap = cv2.VideoCapture(url)

# Parámetros de Telegram
CHAT_ID = '6452057967'
BOT_TOKEN = '7240445682:AAFxrSGBk1uhT37_KNC8w28TZGMW8kxZqf8'

# Variables para temporizador
detection_start_time = None

def upload_photo_to_firebase(photo_path):
    """Subir foto a Firebase Storage."""
    if not os.path.exists(photo_path):
        print(f"Error: No se encontró el archivo {photo_path}")
        return None

    try:
        bucket = storage.bucket()
        blob = bucket.blob(f'fotos/{os.path.basename(photo_path)}')
        blob.upload_from_filename(photo_path)
        print(f"Foto subida a Firebase: {photo_path}")
        
        # Obtener URL pública
        blob.make_public()
        return blob.public_url

    except Exception as e:
        print(f"Error al subir la foto a Firebase: {e}")
        return None

def save_photo_data_to_firebase(photo_url, timestamp):
    """Guardar URL de la foto y la fecha en la base de datos."""
    if photo_url:
        try:
            ref = db.reference('detecciones')
            ref.push({
                'url_foto': photo_url,
                'fecha_hora': timestamp
            })
            print("Datos guardados en la base de datos de Firebase.")
        except Exception as e:
            print(f"Error al guardar datos en la base de datos: {e}")
    else:
        print("Error: No se pudo guardar la URL de la foto en Firebase.")

def send_photo_to_telegram(photo_path, chat_id, bot_token):
    """Enviar foto a Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    if not os.path.exists(photo_path):
        print(f"Error: No se encontró el archivo {photo_path}")
        return
    
    try:
        with open(photo_path, 'rb') as photo:
            payload = {'chat_id': chat_id}
            files = {'photo': photo}
            response = requests.post(url, data=payload, files=files)
            print(f"Respuesta del servidor: {response.text}")
            if response.status_code == 200:
                print("Foto enviada con éxito.")
            else:
                print(f"Error al enviar foto: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error al enviar foto a Telegram: {e}")

def draw_box(frame, box, label, color):
    """Dibuja una caja con una etiqueta en la imagen usando OpenCV."""
    x1, y1, x2, y2 = map(int, box)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    
    label_size, base_line = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    y1 = max(y1, label_size[1])
    cv2.rectangle(frame, (x1, y1 - label_size[1]), (x1 + label_size[0], y1 + base_line), color, cv2.FILLED)
    cv2.putText(frame, label, (x1, y1), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

def on_closing():
    """Cerrar la aplicación y liberar recursos."""
    root.quit()
    cap.release()
    root.destroy()

def callback():
    """Función principal de detección y envío de fotos."""
    global detection_start_time
    
    cap.open(url)
    ret, frame = cap.read()
    
    if ret:
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
                
                # Dibujar la caja y la etiqueta usando OpenCV
                draw_box(frame, r, label=classes[int(c)], color=color)
        
        # Convertir imagen a formato tkinter
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(img)
        tkimage = ImageTk.PhotoImage(img)
        label.configure(image=tkimage)
        label.image = tkimage
        
        # Verificar si la persona ha sido detectada durante más de 5 segundos
        if person_detected:
            now = datetime.now()
            if detection_start_time and (now - detection_start_time).total_seconds() > 5:
                # Crear un nombre de archivo único utilizando la fecha y hora actual
                timestamp = now.strftime('%Y%m%d_%H%M%S')
                photo_path = f'captura_foto_{timestamp}.jpg'
                
                # Guardar la foto con el nuevo nombre único
                cv2.imwrite(photo_path, frame)
                
                # Subir foto a Firebase
                photo_url = upload_photo_to_firebase(photo_path)
                
                # Guardar URL y hora en la base de datos
                save_photo_data_to_firebase(photo_url, timestamp)

                # Enviar foto a Telegram
                send_photo_to_telegram(photo_path, CHAT_ID, BOT_TOKEN)
                
                detection_start_time = None
        
        else:
            detection_start_time = None
        
        # Volver a llamar a callback para procesar el siguiente frame
        root.after(1, callback)
    
    else:
        on_closing()


# Configuración de la interfaz gráfica
root = Tk()
root.protocol("WM_DELETE_WINDOW", on_closing)
root.title("Vision Artificial")

label = Label(root)
label.grid(row=1, padx=20, pady=20)

root.after(1, callback)
root.mainloop()
