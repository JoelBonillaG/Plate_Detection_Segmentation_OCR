import argparse
import math
import random
import statistics
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

_HERE = Path(__file__).parent
_ORC = _HERE.parent / "ORC" / "Datasets_Crudos"
# Cada dataset declara: si se FILTRA por calidad, su TOPE de placas y en que SPLITS
# aporta. Decision clave: lo foraneo (UK/Brasil) va SOLO a train -> ensena geometria
# y angulos; valid queda SOLO con Ecuador -> el checkpoint (val_dice) se elige por el
# desempeno en el dominio OBJETIVO, no por placas extranjeras.
DATASETS = [
    # base "lpr" = India (KA=Karnataka). Char-bbox limpios -> sin filtro. Aporta valid (proxy).
    {"name": "india_base", "path": _HERE / "Datasets" / "lpr character segmentation.v3i.yolov8",
     "filter": False, "max": 0, "splits": ("train", "valid")},
    # Ecuador REAL (dominio destino). Recortes generados por crop_ecuador_plates.py desde el
    # dataset de carro-entero (22 placas unicas con chars, ya a escala de recorte). filter=False:
    # son reales y a proposito INCLINADAS -> el filtro de calidad las rechazaria por salto_altura.
    {"name": "ecuador_real", "path": _HERE / "Datasets" / "ecuador_real_crops",
     "filter": False, "max": 0,    "splits": ("train",)},
    {"name": "brasil",  "path": _ORC / "plate-ocr.v4i.yolov8",
     "filter": True,  "max": 0,    "splits": ("train", "test")},   # buen match -> sin tope
    {"name": "uk",      "path": _ORC / "en.v4i.yolov8",
     "filter": True,  "max": 3000, "splits": ("train", "test")},   # ruidoso -> filtrar + capar
]
OUTPUT_DIR = _HERE / "Models"


def find_image(images_dir, stem):
    for extension in IMAGE_EXTENSIONS:
        image_path = images_dir / f"{stem}{extension}"
        if image_path.exists():
            return image_path
    return None


def plate_quality(boxes, min_chars, max_adj_ratio, max_row_spread):
    """(ok, motivo). Acepta placas de 1 fila con chars de altura coherente,
    permitiendo cambio GRADUAL por perspectiva (placa de lado); rechaza saltos de
    altura abruptos (subtexto/vanity UK) y placas multi-fila."""
    if len(boxes) < min_chars:
        return False, "pocos_chars"
    bx = sorted(boxes, key=lambda b: b[0])             # izq -> der
    hs = [b[3] for b in bx]
    if min(hs) <= 0:
        return False, "caja_invalida"
    # 1) salto de altura entre chars VECINOS -> subtexto/vanity, NO perspectiva
    #    (la perspectiva cambia la altura GRADUAL, vecinos quedan parecidos).
    for a, b in zip(hs, hs[1:]):
        if max(a, b) / min(a, b) > max_adj_ratio:
            return False, "salto_altura"
    # 2) multi-fila -> y_center muy disperso vs altura tipica (permite tilt de 1 fila).
    ys = [b[1] for b in bx]
    if (max(ys) - min(ys)) > max_row_spread * statistics.median(hs):
        return False, "multi_fila"
    return True, "ok"


def collect_pairs(datasets, split, min_chars=4, max_adj_ratio=1.6,
                  max_row_spread=1.5, seed=42):
    """Recolecta pares (imagen, label) de cada dataset SOLO en los splits que declara.
    Aplica filtro de calidad y tope de volumen por dataset (muestreo reproducible)."""
    pairs = []
    for d in datasets:
        if split not in d["splits"]:
            continue
        dataset_dir = Path(d["path"])
        images_dir = dataset_dir / split / "images"
        labels_dir = dataset_dir / split / "labels"
        if not images_dir.exists() or not labels_dir.exists():
            continue

        kept, rejected = [], 0
        for label_path in sorted(labels_dir.glob("*.txt")):
            image_path = find_image(images_dir, label_path.stem)
            if image_path is None:
                continue
            if d["filter"]:
                ok, _ = plate_quality(parse_boxes(label_path),
                                      min_chars, max_adj_ratio, max_row_spread)
                if not ok:
                    rejected += 1
                    continue
            kept.append((image_path, label_path))

        cap_note = ""
        cap = d.get("max", 0)
        if cap and len(kept) > cap:
            kept = random.Random(seed).sample(kept, cap)
            cap_note = f" -> capado a {cap}"

        pairs.extend(kept)
        filt_note = f" (filtro descarto {rejected})" if d["filter"] else ""
        print(f"  [{split}] {d['name']}: {len(kept)} pares{filt_note}{cap_note}")

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


def random_perspective(image, target, max_warp):
    # Perspectiva (HOMOGRAFIA): simula la placa vista DE LADO o desde arriba/abajo,
    # donde los lados dejan de ser paralelos y forman un TRAPECIO. La afin NO puede
    # hacer esto (conserva el paralelismo) -> esta es la UNICA augmentacion que
    # reproduce la distorsion real de una captura oblicua, que es justo el caso que
    # rompia la segmentacion. Aplica la MISMA transformacion a imagen y target.
    h, w = image.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])          # TL, TR, BR, BL
    # jitter INDEPENDIENTE por esquina -> cubre inclinacion lateral, vertical y mixta.
    jitter = np.float32([
        [random.uniform(-max_warp, max_warp) * w, random.uniform(-max_warp, max_warp) * h]
        for _ in range(4)
    ])
    matrix = cv2.getPerspectiveTransform(src, src + jitter)

    warped_image = cv2.warpPerspective(
        image[:, :, 0], matrix, (w, h),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
    )
    warped_target = cv2.warpPerspective(
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


def augment_pair(image, target, persp_prob=0.5, persp_warp=0.12):
    # Perspectiva PRIMERO: es la distorsion dominante (punto de vista oblicuo). La
    # afin va despues para anadir rotacion/shear residual sobre la placa ya inclinada.
    if random.random() < persp_prob:
        image, target = random_perspective(image, target, persp_warp)

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
                 border_weight, shuffle=True, augment=False,
                 persp_prob=0.5, persp_warp=0.12, **kwargs):
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
        self.persp_prob = persp_prob
        self.persp_warp = persp_warp
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
                image, target = augment_pair(
                    image, target, self.persp_prob, self.persp_warp)

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


def evaluate_on_test(args, q):
    """Carga el mejor modelo y reporta dice/IoU sobre el split 'test' (UK+Brasil,
    NUNCA entrenado). Es un test de GENERALIZACION en dominio foraneo; para la verdad
    de Ecuador usa evaluate_segmentation.py sobre capturas reales (Test_Placas)."""
    model_path = (Path(args.eval_model) if args.eval_model
                  else Path(args.output_dir) / f"best_{args.model_name}")
    if not model_path.exists():
        raise SystemExit(f"No existe el modelo: {model_path}\nEntrena primero (sin --eval-only).")

    print("Recolectando split de test:")
    test_pairs = collect_pairs(DATASETS, "test", **q)
    if not test_pairs:
        raise SystemExit("No se encontraron pares en el split 'test'.")
    print(f"Test total: {len(test_pairs)}")

    model = tf.keras.models.load_model(model_path, compile=False)
    h, w = int(model.input_shape[1]), int(model.input_shape[2])
    test_seq = CharMaskSequence(
        test_pairs, height=h, width=w, batch_size=args.batch_size,
        sep_ratio=args.sep_ratio, shrink_y=args.shrink_y,
        border_weight=args.border_weight, shuffle=False, augment=False,
    )
    model.compile(
        loss=weighted_bce_dice_loss,
        metrics=[dice_coefficient, MaskedBinaryIoU(target_class_ids=[1], threshold=0.5)],
    )
    print(f"Modelo: {model_path.name}  | input {w}x{h}")
    results = model.evaluate(test_seq, verbose=1, return_dict=True)
    print("\n== TEST (generalizacion, nunca entrenado) ==")
    for k, v in results.items():
        print(f"  {k}: {float(v):.4f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir",    default=str(OUTPUT_DIR))
    parser.add_argument("--model-name",    default="char_segmentation_unet.keras")
    parser.add_argument("--height",        type=int,   default=96)
    parser.add_argument("--width",         type=int,   default=256)
    parser.add_argument("--batch-size",    type=int,   default=16)
    parser.add_argument("--epochs",        type=int,   default=50)
    parser.add_argument("--sep-ratio",     type=float, default=0.08)
    parser.add_argument("--shrink-y",      type=float, default=0.95)
    parser.add_argument("--border-weight", type=float, default=8.0)
    # augmentacion de PERSPECTIVA (placa vista de lado)
    parser.add_argument("--persp-prob", type=float, default=0.5,
                        help="Prob. de warp de perspectiva. 0 = desactiva.")
    parser.add_argument("--persp-warp", type=float, default=0.12,
                        help="Magnitud max del jitter de esquinas (fraccion del lado).")
    # filtro de calidad + topes de volumen de datos foraneos
    parser.add_argument("--min-chars", type=int, default=4)
    parser.add_argument("--max-adj-ratio", type=float, default=1.6,
                        help="Ratio max de altura entre chars vecinos (vanity UK).")
    parser.add_argument("--max-row-spread", type=float, default=1.5,
                        help="Dispersion max de y_center vs altura mediana (multi-fila).")
    parser.add_argument("--max-uk", type=int, default=3000, help="Tope placas UK (0=todas).")
    parser.add_argument("--max-br", type=int, default=0, help="Tope placas Brasil (0=todas).")
    parser.add_argument("--seed", type=int, default=42)
    # prefetch: hilos que preparan batches (aug pesada) mientras la GPU entrena.
    # En Windows usamos HILOS (use_multiprocessing=False): cv2/numpy sueltan el GIL,
    # y multiprocessing con keras.Sequence en Win suele colgarse.
    parser.add_argument("--workers", type=int, default=4,
                        help="Hilos de prefetch de datos (0/1 = sin prefetch).")
    # solo testear (no entrena)
    parser.add_argument("--eval-only", action="store_true",
                        help="No entrena: carga el mejor modelo y evalua dice/IoU en el split test.")
    parser.add_argument("--eval-model", default="",
                        help="Ruta del modelo a evaluar (default: best_<model-name> en output-dir).")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # topes por dataset desde la CLI
    for d in DATASETS:
        if d["name"] == "uk":
            d["max"] = args.max_uk
        elif d["name"] == "brasil":
            d["max"] = args.max_br

    q = dict(min_chars=args.min_chars, max_adj_ratio=args.max_adj_ratio,
             max_row_spread=args.max_row_spread, seed=args.seed)

    if args.eval_only:
        evaluate_on_test(args, q)
        return

    print("Recolectando pares imagen/label:")
    train_pairs = collect_pairs(DATASETS, "train", **q)
    valid_pairs = collect_pairs(DATASETS, "valid", **q)

    print(f"Train total: {len(train_pairs)}")
    print(f"Valid total: {len(valid_pairs)}")

    # Justificacion formula docente adaptada a U-Net (fully convolutional, sin Dense)
    # Bridge = bottleneck: 256x96 / (2^3) = 32x12 = 384 posiciones x 256 filtros
    bridge_positions = (args.width // 8) * (args.height // 8)
    bridge_active    = int(256 * (1 - 0.30))
    required_pixels  = bridge_positions * bridge_active * 1
    pixels_per_image = args.width * args.height
    min_images       = -(-required_pixels // pixels_per_image)  # ceil division
    print(f"\nJustificacion formula (U-Net, fully convolutional):")
    print(f"  Input: {args.width}x{args.height} = {pixels_per_image:,} px/imagen")
    print(f"  Bridge: {args.width//8}x{args.height//8} = {bridge_positions} posiciones "
          f"x 256 filtros x Dropout(0.30) = {bridge_active} activos")
    print(f"  Requerido: {bridge_positions} x {bridge_active} x 1 = {required_pixels:,} pixeles")
    print(f"  Min imagenes: ceil({required_pixels:,} / {pixels_per_image:,}) = {min_images}")
    print(f"  Tenemos: {len(train_pairs):,} >> {min_images} OK (sin necesidad de K-Fold)")
    print(f"Tamano de entrada: {args.width}x{args.height}x1")
    print(f"sep_ratio={args.sep_ratio}  shrink_y={args.shrink_y}  border_weight={args.border_weight}")
    print(f"persp_prob={args.persp_prob}  persp_warp={args.persp_warp}")

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
        persp_prob=args.persp_prob,
        persp_warp=args.persp_warp,
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
        workers=max(1, args.workers),
        use_multiprocessing=False,   # Windows: hilos, no procesos
        max_queue_size=16,
    )

    model.save(model_path)
    print(f"Modelo final guardado en: {model_path.resolve()}")
    print(f"Mejor modelo guardado en: {best_model_path.resolve()}")


if __name__ == "__main__":
    main()
