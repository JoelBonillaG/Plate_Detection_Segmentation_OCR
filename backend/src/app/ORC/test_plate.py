import argparse
import os
import shutil
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf


DEFAULT_CLASSES = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def load_classes(classes_path):
    if not os.path.exists(classes_path):
        print(f"ADVERTENCIA: no existe {classes_path}. Se usara orden estandar 0-9 A-Z.")
        return DEFAULT_CLASSES

    with open(classes_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f.readlines() if line.strip()]


def prepare_crop(gray_crop, target_h, target_w):
    """
    Preprocesamiento compatible con tu entrenamiento:
    - escala de grises
    - carácter negro sobre fondo claro
    - resize dinámico al tamaño de entrada del modelo
    - NO divide para 255 porque el modelo ya tiene Rescaling(1./255)
    """

    # Recorte fino alrededor del carácter oscuro
    arr = np.array(gray_crop)

    mask = arr < 140

    if mask.any():
        ys, xs = np.where(mask)

        x1 = max(0, xs.min() - 3)
        y1 = max(0, ys.min() - 3)
        x2 = min(arr.shape[1], xs.max() + 4)
        y2 = min(arr.shape[0], ys.max() + 4)

        gray_crop = gray_crop[y1:y2, x1:x2]

    h, w = gray_crop.shape[:2]
    scale = min(target_w / max(1, w), target_h / max(1, h)) * 0.88
    new_w = max(1, min(target_w, int(w * scale)))
    new_h = max(1, min(target_h, int(h * scale)))

    resized_char = cv2.resize(gray_crop, (new_w, new_h), interpolation=cv2.INTER_AREA)

    light_pixels = gray_crop[gray_crop > 120]
    bg = int(np.median(light_pixels)) if light_pixels.size else 245
    bg = int(np.clip(bg, 210, 255))

    resized = np.full((target_h, target_w), bg, dtype=np.uint8)
    x = (target_w - new_w) // 2
    y = (target_h - new_h) // 2
    resized[y:y + new_h, x:x + new_w] = resized_char

    # IMPORTANTE:
    # No normalizar aquí.
    # El modelo ya tiene layers.Rescaling(1./255)
    resized = resized.astype("float32")

    return resized


def segment_characters(image_path, debug_dir="debug_chars"):
    img = cv2.imread(image_path)

    if img is None:
        raise ValueError(f"No se pudo leer la imagen: {image_path}")

    if os.path.exists(debug_dir):
        shutil.rmtree(debug_dir)
    os.makedirs(debug_dir, exist_ok=True)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    height, width = gray.shape

    # Recortar la parte superior para evitar "ECUADOR" y logos pequeños
    # Ajusta este valor si tu imagen cambia.
    roi_y_start = int(height * 0.32)
    roi = gray[roi_y_start:height, :]

    # Suavizado leve
    blur = cv2.GaussianBlur(roi, (3, 3), 0)

    # Letras negras sobre fondo claro => threshold inverse
    _, th = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    # Cerrar pequeños huecos
    kernel = np.ones((3, 3), np.uint8)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        area = w * h

        # Filtros para quedarnos con caracteres grandes
        if h < roi.shape[0] * 0.35:
            continue

        if w < width * 0.025:
            continue

        if area < 200:
            continue

        # Ignorar objetos demasiado anchos o raros
        if w > width * 0.20:
            continue

        boxes.append((x, y, w, h))

    # Ordenar de izquierda a derecha
    boxes = sorted(boxes, key=lambda b: b[0])

    crops = []

    debug_img = img.copy()

    for i, (x, y, w, h) in enumerate(boxes):
        # Padding alrededor del carácter
        pad = 6

        x1 = max(x - pad, 0)
        y1 = max(y - pad, 0)
        x2 = min(x + w + pad, roi.shape[1])
        y2 = min(y + h + pad, roi.shape[0])

        crop = roi[y1:y2, x1:x2]
        crops.append(crop)

        # Guardar crops para revisar visualmente
        cv2.imwrite(os.path.join(debug_dir, f"char_{i}.png"), crop)

        # Dibujar cajas en imagen original
        cv2.rectangle(
            debug_img,
            (x1, y1 + roi_y_start),
            (x2, y2 + roi_y_start),
            (0, 255, 0),
            2
        )

    cv2.imwrite(os.path.join(debug_dir, "segmentation_debug.png"), debug_img)
    cv2.imwrite(os.path.join(debug_dir, "threshold.png"), th)

    return crops, boxes


def decode_with_rules(prob_list, classes, num_letters):
    """Decodifica usando el formato de placa Ecuador: las primeras `num_letters`
    posiciones son LETRAS (A-Z) y el resto son DIGITOS (0-9). Restringe el argmax
    a las clases validas por posicion -> elimina confusiones cruzadas (O/0, I/1, Z/2)."""
    letter_ids = [i for i, c in enumerate(classes) if c.isalpha()]
    digit_ids = [i for i, c in enumerate(classes) if c.isdigit()]

    decoded = []
    for position, probs in enumerate(prob_list):
        allowed = letter_ids if position < num_letters else digit_ids
        best = max(allowed, key=lambda i: probs[i])
        decoded.append(classes[best])
    return "".join(decoded)


def predict_plate(image_path, model_path, classes_path, num_letters=3):
    model = tf.keras.models.load_model(model_path, compile=False)
    classes = load_classes(classes_path)

    input_shape = model.input_shape

    target_h = input_shape[1]
    target_w = input_shape[2]

    if len(input_shape) == 4:
        channels = input_shape[3]
    else:
        channels = 1

    print(f"Modelo cargado: {model_path}")
    print(f"Input esperado por el modelo: {input_shape}")
    print(f"Cada crop se preparara como: {target_w}x{target_h}x{channels}")

    crops, boxes = segment_characters(image_path)

    result = ""
    prob_list = []

    print(f"Caracteres segmentados: {len(crops)}")

    for i, crop in enumerate(crops):
        processed = prepare_crop(crop, target_h, target_w)

        if processed is None:
            continue

        cv2.imwrite(
            os.path.join("debug_chars", f"processed_{i}_{target_w}x{target_h}.png"),
            processed.astype(np.uint8)
        )

        if channels == 1:
            processed = np.expand_dims(processed, axis=-1)
        elif channels == 3:
            processed = cv2.cvtColor(processed.astype(np.uint8), cv2.COLOR_GRAY2RGB)
            processed = processed.astype("float32")

        processed = np.expand_dims(processed, axis=0)

        pred = model.predict(processed, verbose=0)[0]
        prob_list.append(pred)

        top_ids = np.argsort(pred)[-3:][::-1]
        class_id = int(top_ids[0])
        confidence = float(pred[class_id])

        predicted_char = classes[class_id]

        result += predicted_char

        top_text = ", ".join(
            f"{classes[int(idx)]}={float(pred[int(idx)]):.4f}"
            for idx in top_ids
        )
        print(f"Char {i}: {predicted_char}  confianza={confidence:.4f}  top3=[{top_text}]")

    ruled = decode_with_rules(prob_list, classes, num_letters) if prob_list else ""

    print("\nResultado crudo (argmax):")
    print(result)
    print(f"\nResultado con reglas posicionales ({num_letters} letras + digitos):")
    print(ruled)
    if ruled and ruled != result:
        print("(las reglas corrigieron al menos un caracter)")

    print("\nRevisa la carpeta 'debug_chars' para ver:")
    print("- Los caracteres recortados")
    print("- La imagen con cajas")
    print("- La imagen binarizada")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    _here = Path(__file__).parent
    parser.add_argument("--image", default=str(_here / "placa.png"))
    parser.add_argument("--model", default=str(_here / "Modelos" / "best_cnn_ocr.keras"))
    parser.add_argument("--classes", default=str(_here / "Modelos" / "classes.txt"))
    parser.add_argument("--num-letters", type=int, default=3, help="Letras iniciales (Ecuador: 3 letras + digitos).")

    args = parser.parse_args()

    predict_plate(args.image, args.model, args.classes, num_letters=args.num_letters)
