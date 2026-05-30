import argparse
import math
import random
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_class_weight
from tensorflow.keras import layers, models, regularizers


IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


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
    # Augment MANUAL con numpy/cv2 (NO capas Keras): evita el while_loop lento de
    # TF 2.10 y deja al GPU hacer solo conv. image = (H, W, 1) float32 en 0-255.
    gray = image[:, :, 0]
    h, w = gray.shape

    if random.random() < 0.70:  # rotacion + escala + traslacion leve
        angle = random.uniform(-7.0, 7.0)
        scale = random.uniform(0.92, 1.10)
        matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, scale)
        matrix[0, 2] += random.uniform(-2.0, 2.0)
        matrix[1, 2] += random.uniform(-2.0, 2.0)
        gray = cv2.warpAffine(gray, matrix, (w, h),
                              flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    if random.random() < 0.50:  # brillo / contraste
        alpha = random.uniform(0.85, 1.15)
        beta = random.uniform(-15.0, 15.0)
        gray = np.clip(gray * alpha + beta, 0, 255)

    if random.random() < 0.20:  # ruido gaussiano
        gray = np.clip(gray + np.random.normal(0, random.uniform(2, 7), gray.shape), 0, 255)

    return gray[:, :, None].astype("float32")


class CharSequence(tf.keras.utils.Sequence):
    # Carga los crops a RAM una vez (rapido por epoch) y aplica augment manual.
    def __init__(self, samples, image_size, batch_size, shuffle, augment, **kwargs):
        super().__init__(**kwargs)
        self.image_size = image_size
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.augment = augment
        self.labels = np.array([label for _, label in samples], dtype=np.int64)

        self.images = np.empty((len(samples), image_size, image_size, 1), dtype=np.uint8)
        for i, (path, _) in enumerate(samples):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            img = cv2.resize(img, (image_size, image_size), interpolation=cv2.INTER_AREA)
            self.images[i, :, :, 0] = img

        self.indexes = np.arange(len(samples))
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
    # SIN capas de augment dentro del modelo (el augment va en el Sequence, manual).
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

            layers.Dense(256, activation="relu", kernel_regularizer=l2),
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


def get_class_names(train_dir):
    return sorted(d.name for d in Path(train_dir).iterdir() if d.is_dir())


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


def compute_weights(labels, num_classes):
    class_ids = np.arange(num_classes)
    weights = compute_class_weight(class_weight="balanced", classes=class_ids, y=labels)
    return {int(c): float(w) for c, w in zip(class_ids, weights)}


def save_class_names(class_names, output_path):
    output_path.write_text("\n".join(class_names) + "\n", encoding="utf-8")


def evaluate_model(model, test_seq, class_names, output_dir):
    y_true = []
    y_pred = []

    for images, labels in test_seq:
        probabilities = model.predict(images, verbose=0)
        y_pred.extend(np.argmax(probabilities, axis=1).tolist())
        y_true.extend(labels.tolist())

    report = classification_report(y_true, y_pred, target_names=class_names,
                                   digits=4, zero_division=0)
    matrix = confusion_matrix(y_true, y_pred)

    (output_dir / "classification_report.txt").write_text(report, encoding="utf-8")
    np.savetxt(output_dir / "confusion_matrix.csv", matrix, fmt="%d", delimiter=",")

    print("\nReporte de clasificacion:")
    print(report)


def main():
    parser = argparse.ArgumentParser(description="Entrena una CNN OCR para caracteres de placas.")
    parser.add_argument("--dataset", default="Dataset_OCR_Final")
    parser.add_argument("--output-dir", default="Modelos")
    parser.add_argument("--model-name", default="cnn_ocr_uk.keras")
    parser.add_argument("--classes-name", default="classes_uk.txt")
    parser.add_argument("--image-size", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--no-class-weight", action="store_true")
    parser.add_argument("--workers", type=int, default=4, help="Hilos para augment/carga de batches.")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    class_names = get_class_names(dataset_dir / "train")
    num_classes = len(class_names)

    print("Clases:", class_names)
    print(f"Numero de clases: {num_classes}  | input {args.image_size}x{args.image_size}x1")

    save_class_names(class_names, output_dir / args.classes_name)

    print("Cargando imagenes a RAM...")
    train_samples = list_samples(dataset_dir / "train", class_names)
    valid_samples = list_samples(dataset_dir / "valid", class_names)
    test_samples = list_samples(dataset_dir / "test", class_names)
    print(f"train={len(train_samples)}  valid={len(valid_samples)}  test={len(test_samples)}")

    train_seq = CharSequence(train_samples, args.image_size, args.batch_size, shuffle=True, augment=True)
    valid_seq = CharSequence(valid_samples, args.image_size, args.batch_size, shuffle=False, augment=False)
    test_seq = CharSequence(test_samples, args.image_size, args.batch_size, shuffle=False, augment=False)

    class_weight = None
    if not args.no_class_weight:
        class_weight = compute_weights(train_seq.labels, num_classes)

    model = build_model(args.image_size, num_classes)
    model.summary()

    model_path = output_dir / args.model_name
    best_model_path = output_dir / f"best_{args.model_name}"

    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(best_model_path, monitor="val_accuracy",
                                           mode="max", save_best_only=True, verbose=1),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                             patience=4, min_lr=1e-5, verbose=1),
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=10,
                                         restore_best_weights=True, verbose=1),
    ]

    model.fit(
        train_seq,
        validation_data=valid_seq,
        epochs=args.epochs,
        class_weight=class_weight,
        callbacks=callbacks,
        workers=args.workers,
        use_multiprocessing=False,
        max_queue_size=16,
    )

    model.save(model_path)
    print(f"\nModelo final: {model_path.resolve()}")
    print(f"Mejor modelo: {best_model_path.resolve()}")

    print("\nEvaluacion en test:")
    test_loss, test_accuracy = model.evaluate(test_seq, verbose=1)
    print(f"Test loss: {test_loss:.4f}  | Test accuracy: {test_accuracy:.4f}")

    evaluate_model(model, test_seq, class_names, output_dir)


if __name__ == "__main__":
    main()
