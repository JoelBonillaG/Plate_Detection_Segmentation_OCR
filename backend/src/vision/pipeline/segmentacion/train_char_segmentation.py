import argparse
import math
import random
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def find_image(images_dir, stem):
    for extension in IMAGE_EXTENSIONS:
        image_path = images_dir / f"{stem}{extension}"
        if image_path.exists():
            return image_path
    return None


def collect_pairs(dataset_dir, split):
    images_dir = dataset_dir / split / "images"
    labels_dir = dataset_dir / split / "labels"
    pairs = []

    if not images_dir.exists() or not labels_dir.exists():
        return pairs

    for label_path in sorted(labels_dir.glob("*.txt")):
        image_path = find_image(images_dir, label_path.stem)
        if image_path is not None:
            pairs.append((image_path, label_path))

    return pairs


def load_gray_image(image_path, height, width):
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"No se pudo leer la imagen: {image_path}")

    image = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
    image = image.astype("float32")
    return np.expand_dims(image, axis=-1)


def parse_boxes(label_path):
    boxes = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) != 5:
            continue
        _, x_center, y_center, box_width, box_height = [float(part) for part in parts]
        boxes.append((x_center, y_center, box_width, box_height))
    return boxes


def build_targets(boxes, height, width, sep_ratio, shrink_y, border_weight):
    # Devuelve target (H, W, 2):
    #   canal 0 = mascara de chars. Cada char se pinta a ANCHO COMPLETO (crops buenos
    #             para el OCR) y solo se TALLA un separador fino entre chars vecinos,
    #             de modo que queden como instancias separables sin perder ancho.
    #   canal 1 = mapa de pesos: sube el costo de equivocarse en ese separador, asi la
    #             red aprende a NO fusionar chars pegados (idea de U-Net, Ronneberger 2015).
    mask = np.zeros((height, width), dtype="float32")
    weight = np.ones((height, width), dtype="float32")
    painted = []

    for (x_center, y_center, box_width, box_height) in boxes:
        half_w = box_width / 2.0
        half_h = box_height * shrink_y / 2.0  # leve recorte vertical: evita el marco

        x1 = int((x_center - half_w) * width)
        x2 = int((x_center + half_w) * width)
        y1 = int((y_center - half_h) * height)
        y2 = int((y_center + half_h) * height)

        x1 = max(0, min(width - 1, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height, y2))

        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 1.0
            painted.append((x1, y1, x2, y2))

    # Talla un separador entre chars vecinos (solo en su solape vertical) y pesa la zona.
    painted.sort(key=lambda b: b[0])
    for i in range(len(painted) - 1):
        ax1, ay1, ax2, ay2 = painted[i]
        bx1, by1, bx2, by2 = painted[i + 1]
        oy1, oy2 = max(ay1, by1), min(ay2, by2)
        if oy2 <= oy1:  # sin solape vertical -> usa el rango combinado
            oy1, oy2 = min(ay1, by1), max(ay2, by2)

        contact = (ax2 + bx1) // 2
        pair_h = min(ay2 - ay1, by2 - by1)
        carve = max(2, int(pair_h * sep_ratio))  # medio ancho del corte (px)

        cx1, cx2 = max(0, contact - carve), min(width, contact + carve)
        if cx2 > cx1 and oy2 > oy1:
            mask[oy1:oy2, cx1:cx2] = 0.0  # gap garantizado entre los dos chars

        if border_weight > 1.0:
            wx1, wx2 = max(0, contact - 2 * carve), min(width, contact + 2 * carve)
            if wx2 > wx1 and oy2 > oy1:
                weight[oy1:oy2, wx1:wx2] = border_weight

    return np.stack([mask, weight], axis=-1)


def random_affine(image, target):
    # Rotacion + escala + traslacion + shear: simula placas inclinadas/escaladas que
    # SI aparecen en inferencia. Aplica la MISMA transformacion a imagen y target.
    h, w = image.shape[:2]
    angle = random.uniform(-8.0, 8.0)
    scale = random.uniform(0.90, 1.12)
    shear = random.uniform(-0.10, 0.10)
    tx = random.uniform(-0.04, 0.04) * w
    ty = random.uniform(-0.06, 0.06) * h

    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale).astype("float32")
    matrix[0, 0] += shear * matrix[1, 0]
    matrix[0, 1] += shear * matrix[1, 1]
    matrix[0, 2] += tx
    matrix[1, 2] += ty

    warped_image = cv2.warpAffine(
        image[:, :, 0], matrix, (w, h),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )
    warped_target = cv2.warpAffine(
        target, matrix, (w, h),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )
    if warped_target.ndim == 2:
        warped_target = warped_target[:, :, None]

    image = warped_image[:, :, None]
    mask = (warped_target[:, :, 0] > 0.5).astype("float32")
    weight = warped_target[:, :, 1]
    weight[weight < 1.0] = 1.0  # zonas rellenadas por el warp = fondo normal
    target = np.stack([mask, weight], axis=-1)
    return image, target


def augment_pair(image, target):
    if random.random() < 0.70:
        image, target = random_affine(image, target)

    if random.random() < 0.40:
        alpha = random.uniform(0.75, 1.25)
        beta = random.uniform(-18, 18)
        image = np.clip(image * alpha + beta, 0, 255)

    if random.random() < 0.30:
        noise = np.random.normal(0, random.uniform(2, 8), image.shape)
        image = np.clip(image + noise, 0, 255)

    if random.random() < 0.25:
        ksize = random.choice([3, 5])
        image_2d = cv2.GaussianBlur(image[:, :, 0], (ksize, ksize), 0)
        image = np.expand_dims(image_2d, axis=-1)

    return image.astype("float32"), target.astype("float32")


class CharMaskSequence(tf.keras.utils.Sequence):
    # Lee labels en formato txt (clase x y w h) y construye mascaras para la U-Net.
    # NO usa el modelo/algoritmo YOLO: solo aprovecha ese formato de archivo de labels.
    def __init__(self, pairs, height, width, batch_size, sep_ratio, shrink_y,
                 border_weight, shuffle=True, augment=False, **kwargs):
        super().__init__(**kwargs)
        self.pairs = list(pairs)
        self.height = height
        self.width = width
        self.batch_size = batch_size
        self.sep_ratio = sep_ratio
        self.shrink_y = shrink_y
        self.border_weight = border_weight
        self.shuffle = shuffle
        self.augment = augment
        self.indexes = np.arange(len(self.pairs))
        self.on_epoch_end()

    def __len__(self):
        return math.ceil(len(self.pairs) / self.batch_size)

    def on_epoch_end(self):
        if self.shuffle:
            np.random.shuffle(self.indexes)

    def __getitem__(self, batch_index):
        batch_indexes = self.indexes[
            batch_index * self.batch_size:(batch_index + 1) * self.batch_size
        ]

        images = []
        targets = []

        for pair_index in batch_indexes:
            image_path, label_path = self.pairs[pair_index]
            image = load_gray_image(image_path, self.height, self.width)
            boxes = parse_boxes(label_path)
            target = build_targets(
                boxes, self.height, self.width,
                self.sep_ratio, self.shrink_y, self.border_weight,
            )

            if self.augment:
                image, target = augment_pair(image, target)

            images.append(image)
            targets.append(target)

        return np.stack(images, axis=0), np.stack(targets, axis=0)


def conv_block(x, filters):
    x = layers.Conv2D(filters, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    x = layers.Conv2D(filters, 3, padding="same", activation="relu")(x)
    x = layers.BatchNormalization()(x)
    return x


def build_unet(height, width):
    inputs = layers.Input(shape=(height, width, 1))
    x = layers.Rescaling(1.0 / 255.0)(inputs)

    c1 = conv_block(x, 32)
    p1 = layers.MaxPooling2D()(c1)

    c2 = conv_block(p1, 64)
    p2 = layers.MaxPooling2D()(c2)

    c3 = conv_block(p2, 128)
    p3 = layers.MaxPooling2D()(c3)

    bridge = conv_block(p3, 256)
    bridge = layers.Dropout(0.30)(bridge)

    u3 = layers.UpSampling2D()(bridge)
    u3 = layers.Concatenate()([u3, c3])
    c4 = conv_block(u3, 128)

    u2 = layers.UpSampling2D()(c4)
    u2 = layers.Concatenate()([u2, c2])
    c5 = conv_block(u2, 64)

    u1 = layers.UpSampling2D()(c5)
    u1 = layers.Concatenate()([u1, c1])
    c6 = conv_block(u1, 32)

    outputs = layers.Conv2D(1, 1, activation="sigmoid", name="char_mask")(c6)
    return models.Model(inputs, outputs, name="char_segmentation_unet")


@tf.keras.utils.register_keras_serializable()
def dice_coefficient(y_true, y_pred, smooth=1.0):
    # y_true puede traer 2 canales (mascara + peso); usa solo el canal 0.
    y_true = tf.cast(y_true[..., 0:1], tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)
    intersection = tf.reduce_sum(y_true * y_pred)
    denominator = tf.reduce_sum(y_true) + tf.reduce_sum(y_pred)
    return (2.0 * intersection + smooth) / (denominator + smooth)


@tf.keras.utils.register_keras_serializable()
def weighted_bce_dice_loss(y_true, y_pred):
    mask = tf.cast(y_true[..., 0:1], tf.float32)
    weight = tf.cast(y_true[..., 1:2], tf.float32)
    y_pred = tf.cast(y_pred, tf.float32)

    bce = tf.keras.backend.binary_crossentropy(mask, y_pred)
    weighted_bce = tf.reduce_sum(weight * bce) / (tf.reduce_sum(weight) + 1.0)
    dice_loss = 1.0 - dice_coefficient(mask, y_pred)
    return weighted_bce + dice_loss


@tf.keras.utils.register_keras_serializable()
class MaskedBinaryIoU(tf.keras.metrics.BinaryIoU):
    def update_state(self, y_true, y_pred, sample_weight=None):
        return super().update_state(y_true[..., 0:1], y_pred, sample_weight)


def main():
    parser = argparse.ArgumentParser(
        description="Entrena una CNN tipo U-Net para segmentar caracteres en placas."
    )
    parser.add_argument(
        "--dataset",
        default="Datasets/lpr character segmentation.v3i.yolov8",
        help="Dataset con labels en formato txt (clase x y w h). NO se usa el modelo YOLO.",
    )
    parser.add_argument("--output-dir", default="Models")
    parser.add_argument("--model-name", default="char_segmentation_unet.keras")
    parser.add_argument("--height", type=int, default=96)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument(
        "--sep-ratio", type=float, default=0.08,
        help="Medio ancho del separador tallado entre chars (fraccion de la altura del char).",
    )
    parser.add_argument(
        "--shrink-y", type=float, default=0.95,
        help="Factor de alto de la mascara (evita tocar el marco de la placa).",
    )
    parser.add_argument(
        "--border-weight", type=float, default=8.0,
        help="Peso del costo en el gap entre chars. 1.0 = desactiva el mapa de pesos.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_pairs = collect_pairs(dataset_dir, "train")
    valid_pairs = collect_pairs(dataset_dir, "valid")

    print(f"Train pares imagen/label: {len(train_pairs)}")
    print(f"Valid pares imagen/label: {len(valid_pairs)}")
    print(f"Tamano de entrada: {args.width}x{args.height}x1")
    print(f"sep_ratio={args.sep_ratio}  shrink_y={args.shrink_y}  border_weight={args.border_weight}")

    if not train_pairs:
        raise ValueError("No se encontraron pares de entrenamiento.")
    if not valid_pairs:
        raise ValueError("No se encontraron pares de validacion.")

    train_seq = CharMaskSequence(
        train_pairs,
        height=args.height,
        width=args.width,
        batch_size=args.batch_size,
        sep_ratio=args.sep_ratio,
        shrink_y=args.shrink_y,
        border_weight=args.border_weight,
        shuffle=True,
        augment=True,
    )
    valid_seq = CharMaskSequence(
        valid_pairs,
        height=args.height,
        width=args.width,
        batch_size=args.batch_size,
        sep_ratio=args.sep_ratio,
        shrink_y=args.shrink_y,
        border_weight=args.border_weight,
        shuffle=False,
        augment=False,
    )

    model = build_unet(args.height, args.width)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=weighted_bce_dice_loss,
        metrics=[dice_coefficient, MaskedBinaryIoU(target_class_ids=[1], threshold=0.5)],
    )
    model.summary()

    model_path = output_dir / args.model_name
    best_model_path = output_dir / f"best_{args.model_name}"

    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            best_model_path,
            monitor="val_dice_coefficient",
            mode="max",
            save_best_only=True,
            verbose=1,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=10,
            min_lr=1e-5,
            verbose=1,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=20,
            restore_best_weights=True,
            verbose=1,
        ),
    ]

    model.fit(
        train_seq,
        validation_data=valid_seq,
        epochs=args.epochs,
        callbacks=callbacks,
    )

    model.save(model_path)
    print(f"Modelo final guardado en: {model_path.resolve()}")
    print(f"Mejor modelo guardado en: {best_model_path.resolve()}")


if __name__ == "__main__":
    main()
