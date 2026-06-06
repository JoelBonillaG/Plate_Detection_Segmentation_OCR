import math
import random
import shutil
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import StratifiedKFold
from sklearn.utils.class_weight import compute_class_weight
from tensorflow.keras import layers, models, regularizers

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = PROJECT_ROOT / "datasets" / "processed" / "ocr_characters_final"
OUTPUT_DIR = PROJECT_ROOT / "models" / "ocr" / "Modelos"

# Configuracion de entrenamiento. Para cambiar el experimento, edita aqui.
MODEL_NAME = "cnn_ocr.keras"
CLASSES_NAME = "classes.txt"
IMAGE_SIZE = 64
BATCH_SIZE = 64
EPOCHS = 60
FOLDS = 3
WORKERS = 4


class SparseFocalLoss(tf.keras.losses.Loss):
    def __init__(self, gamma=2.0, **kwargs):
        super().__init__(**kwargs)
        self.gamma = gamma

    def call(self, y_true, y_pred):
        ce = tf.keras.losses.sparse_categorical_crossentropy(y_true, y_pred)
        pt = tf.exp(-ce)
        return tf.reduce_mean((1.0 - pt) ** self.gamma * ce)

    def get_config(self):
        config = super().get_config()
        config.update({"gamma": self.gamma})
        return config


def augment_char(image):
    gray = image[:, :, 0]
    h, w = gray.shape

    if random.random() < 0.70:
        angle = random.uniform(-7.0, 7.0)
        scale = random.uniform(0.92, 1.10)
        matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale)
        matrix[0, 2] += random.uniform(-2.0, 2.0)
        matrix[1, 2] += random.uniform(-2.0, 2.0)
        gray = cv2.warpAffine(gray, matrix, (w, h),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    if random.random() < 0.50:
        alpha = random.uniform(0.85, 1.15)
        beta = random.uniform(-15.0, 15.0)
        gray = np.clip(gray * alpha + beta, 0, 255)

    if random.random() < 0.20:
        gray = np.clip(gray + np.random.normal(0, random.uniform(2, 7), gray.shape), 0, 255)

    return gray[:, :, None].astype("float32")


class CharSequence(tf.keras.utils.Sequence):
    # Recibe arrays numpy ya cargados en RAM — sin I/O por epoch.
    def __init__(self, images, labels, batch_size, shuffle, augment, **kwargs):
        super().__init__(**kwargs)
        self.images    = images
        self.labels    = labels
        self.batch_size = batch_size
        self.shuffle   = shuffle
        self.augment   = augment
        self.indexes   = np.arange(len(images))
        self.on_epoch_end()

    def __len__(self):
        return math.ceil(len(self.images) / self.batch_size)

    def on_epoch_end(self):
        if self.shuffle:
            np.random.shuffle(self.indexes)

    def __getitem__(self, batch_index):
        idx = self.indexes[batch_index * self.batch_size:(batch_index + 1) * self.batch_size]
        images = self.images[idx].astype("float32")
        if self.augment:
            for i in range(images.shape[0]):
                images[i] = augment_char(images[i])
        return images, self.labels[idx]


def build_model(image_size, num_classes):
    l2 = regularizers.l2(1e-4)

    model = models.Sequential(
        [
            layers.Input(shape=(image_size, image_size, 1)),
            layers.Rescaling(1.0 / 255.0),

            layers.Conv2D(32, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.Conv2D(32, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.MaxPooling2D(),
            layers.Dropout(0.20),

            layers.Conv2D(64, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.Conv2D(64, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.MaxPooling2D(),
            layers.Dropout(0.30),

            layers.Conv2D(128, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.Conv2D(128, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.MaxPooling2D(),
            layers.Dropout(0.35),

            layers.Conv2D(256, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.GlobalAveragePooling2D(),

            # Dense reducido: 256 features × 16 activas (dropout 0.5) × 36 clases = 147,456
            # K-Fold k=3 sobre 103k datos: 3 × 68,907 = 206,721 > 147,456
            layers.Dense(32, activation="relu", kernel_regularizer=l2),
            layers.BatchNormalization(),
            layers.Dropout(0.50),
            layers.Dense(num_classes, activation="softmax", kernel_regularizer=l2),
        ],
        name="cnn_ocr_plate_chars",
    )

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=SparseFocalLoss(gamma=2.0),
        metrics=["accuracy"],
    )

    return model


def get_class_names(split_dir):
    return sorted(d.name for d in Path(split_dir).iterdir() if d.is_dir())


def list_samples(split_dir, class_names):
    samples = []
    for index, name in enumerate(class_names):
        class_dir = Path(split_dir) / name
        if not class_dir.exists():
            continue
        for path in sorted(class_dir.iterdir()):
            if path.suffix.lower() in IMAGE_EXTS:
                samples.append((path, index))
    return samples


def load_to_arrays(samples, image_size):
    n = len(samples)
    images = np.empty((n, image_size, image_size, 1), dtype=np.uint8)
    labels = np.empty(n, dtype=np.int64)
    for i, (path, label) in enumerate(samples):
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            images[i, :, :, 0] = cv2.resize(img, (image_size, image_size),
                                             interpolation=cv2.INTER_AREA)
        labels[i] = label
    return images, labels


def save_class_names(class_names, output_path):
    output_path.write_text("\n".join(class_names) + "\n", encoding="utf-8")


def evaluate_model(model, test_seq, class_names, output_dir):
    y_true, y_pred = [], []
    for images, labels in test_seq:
        probs = model.predict(images, verbose=0)
        y_pred.extend(np.argmax(probs, axis=1).tolist())
        y_true.extend(labels.tolist())

    report = classification_report(y_true, y_pred, target_names=class_names,
                                   digits=4, zero_division=0)
    matrix = confusion_matrix(y_true, y_pred)

    (output_dir / "classification_report.txt").write_text(report, encoding="utf-8")
    np.savetxt(output_dir / "confusion_matrix.csv", matrix, fmt="%d", delimiter=",")

    print("\nReporte de clasificacion:")
    print(report)


def main():
    dataset_dir = DATASET_DIR
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    class_names = get_class_names(dataset_dir / "train")
    num_classes = len(class_names)
    print(f"Clases: {class_names}")
    print(f"Num clases: {num_classes} | input {IMAGE_SIZE}x{IMAGE_SIZE}x1")
    print(f"Arquitectura: GAP(256) -> Dense(32, dropout=0.5) -> Dense({num_classes})")
    print(f"Datos requeridos teorico: 256 x 16 x {num_classes} = {256*16*num_classes:,}")

    save_class_names(class_names, output_dir / CLASSES_NAME)

    # Combinar train + valid para K-Fold. Test queda completamente aparte.
    print("\nCargando train+valid a RAM...")
    tv_samples = (list_samples(dataset_dir / "train", class_names) +
                  list_samples(dataset_dir / "valid", class_names))
    test_samples = list_samples(dataset_dir / "test", class_names)

    tv_images, tv_labels = load_to_arrays(tv_samples, IMAGE_SIZE)
    test_images, test_labels = load_to_arrays(test_samples, IMAGE_SIZE)

    print(f"train+valid: {len(tv_samples)}  test: {len(test_samples)}")
    print(f"K-Fold k={FOLDS}: train por fold ~{len(tv_samples)*(FOLDS-1)//FOLDS:,}")
    print(f"Total efectivo: {FOLDS} x {len(tv_samples)*(FOLDS-1)//FOLDS:,} = "
          f"{FOLDS * (len(tv_samples)*(FOLDS-1)//FOLDS):,} > "
          f"{256*16*num_classes:,} (requerido) ✓")

    test_seq = CharSequence(test_images, test_labels, BATCH_SIZE,
                            shuffle=False, augment=False)

    skf = StratifiedKFold(n_splits=FOLDS, shuffle=True, random_state=42)
    best_val_acc = 0.0
    best_model_path = output_dir / f"best_{MODEL_NAME}"

    for fold, (train_idx, val_idx) in enumerate(skf.split(tv_images, tv_labels), start=1):
        print(f"\n{'='*50}")
        print(f"FOLD {fold}/{FOLDS}  "
              f"train={len(train_idx):,}  val={len(val_idx):,}")
        print('='*50)

        train_seq = CharSequence(tv_images[train_idx], tv_labels[train_idx],
                                 BATCH_SIZE, shuffle=True, augment=True)
        val_seq   = CharSequence(tv_images[val_idx],   tv_labels[val_idx],
                                 BATCH_SIZE, shuffle=False, augment=False)

        class_weight = {
            int(c): float(w) for c, w in zip(
                np.arange(num_classes),
                compute_class_weight("balanced", classes=np.arange(num_classes),
                                     y=tv_labels[train_idx]),
            )
        }

        model = build_model(IMAGE_SIZE, num_classes)
        if fold == 1:
            model.summary()

        fold_path = output_dir / f"fold{fold}_{MODEL_NAME}"

        callbacks = [
            tf.keras.callbacks.ModelCheckpoint(fold_path, monitor="val_accuracy",
                                               mode="max", save_best_only=True, verbose=1),
            tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                                 patience=4, min_lr=1e-5, verbose=1),
            tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=10,
                                             restore_best_weights=True, verbose=1),
        ]

        history = model.fit(
            train_seq,
            validation_data=val_seq,
            epochs=EPOCHS,
            class_weight=class_weight,
            callbacks=callbacks,
            workers=WORKERS,
            use_multiprocessing=False,
            max_queue_size=16,
        )

        fold_best = max(history.history["val_accuracy"])
        print(f"Fold {fold} mejor val_accuracy: {fold_best:.4f}")

        if fold_best > best_val_acc:
            best_val_acc = fold_best
            shutil.copy(fold_path, best_model_path)
            print(f"  -> Nuevo mejor modelo global (fold {fold}): {fold_best:.4f}")

    print(f"\nMejor val_accuracy global: {best_val_acc:.4f}")
    print(f"Mejor modelo guardado en: {best_model_path.resolve()}")

    print("\nEvaluacion final en test (mejor modelo):")
    best_model = tf.keras.models.load_model(
        best_model_path,
        custom_objects={"SparseFocalLoss": SparseFocalLoss},
    )
    test_loss, test_acc = best_model.evaluate(test_seq, verbose=1)
    print(f"Test loss: {test_loss:.4f}  | Test accuracy: {test_acc:.4f}")

    evaluate_model(best_model, test_seq, class_names, output_dir)


if __name__ == "__main__":
    main()
