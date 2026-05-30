import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_class_weight
from tensorflow.keras import layers, models, regularizers

AUTOTUNE = tf.data.AUTOTUNE


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


def build_model(image_size, num_classes):
    # Augment mas fuerte que antes: cierra la brecha val-test (overfitting) y da mas
    # variedad a las clases raras (que el oversampling muestra mas veces).
    data_augmentation = tf.keras.Sequential(
        [
            layers.RandomRotation(0.03),          # ~+-11 grados (placas algo inclinadas)
            layers.RandomTranslation(0.06, 0.06),
            layers.RandomZoom(0.12),
            layers.RandomContrast(0.20),
            layers.RandomBrightness(0.15),
        ],
        name="data_augmentation",
    )

    l2 = regularizers.l2(1e-4)

    model = models.Sequential(
        [
            layers.Input(shape=(image_size, image_size, 1)),
            data_augmentation,
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


def count_images(train_dir):
    total = 0
    for class_dir in Path(train_dir).iterdir():
        if class_dir.is_dir():
            total += sum(1 for _ in class_dir.glob("*"))
    return total


def load_split(path, image_size, batch_size, shuffle):
    return tf.keras.utils.image_dataset_from_directory(
        path,
        labels="inferred",
        label_mode="int",
        color_mode="grayscale",
        image_size=(image_size, image_size),
        batch_size=batch_size,
        shuffle=shuffle,
    )


def decode_image(path, label, image_size):
    raw = tf.io.read_file(path)
    image = tf.image.decode_png(raw, channels=1)
    image = tf.image.resize(image, [image_size, image_size], method="bilinear")
    image = tf.cast(image, tf.float32)  # 0-255; el modelo ya tiene Rescaling(1/255)
    return image, label


def make_balanced_train_ds(train_dir, class_names, image_size, batch_size):
    # Oversampling balanceado: un stream por clase (repetido) y muestreo equitativo.
    # Las letras raras (Q, X, U, W...) se ven igual de seguido que los digitos, cada
    # vez con un augment distinto -> mejor recall en clases raras.
    per_class = []
    for index, name in enumerate(class_names):
        pattern = str(Path(train_dir) / name / "*")
        files = tf.data.Dataset.list_files(pattern, shuffle=True).repeat()
        per_class.append(files.map(lambda p, l=index: (p, l), num_parallel_calls=AUTOTUNE))

    weights = [1.0 / len(class_names)] * len(class_names)
    balanced = tf.data.Dataset.sample_from_datasets(per_class, weights=weights)
    balanced = balanced.map(
        lambda p, l: decode_image(p, l, image_size), num_parallel_calls=AUTOTUNE
    )
    return balanced.batch(batch_size).prefetch(AUTOTUNE)


def optimize_dataset(dataset, shuffle=False):
    dataset = dataset.cache()
    if shuffle:
        dataset = dataset.shuffle(2000)
    return dataset.prefetch(AUTOTUNE)


def labels_from_dataset(dataset):
    labels = []
    for _, batch_labels in dataset:
        labels.extend(batch_labels.numpy().tolist())
    return np.array(labels, dtype=np.int64)


def compute_weights(train_ds, class_names):
    y_train = labels_from_dataset(train_ds)
    class_ids = np.arange(len(class_names))
    weights = compute_class_weight(
        class_weight="balanced",
        classes=class_ids,
        y=y_train,
    )
    return {int(class_id): float(weight) for class_id, weight in zip(class_ids, weights)}


def save_class_names(class_names, output_path):
    output_path.write_text("\n".join(class_names) + "\n", encoding="utf-8")


def evaluate_model(model, test_ds, class_names, output_dir):
    y_true = []
    y_pred = []

    for images, labels in test_ds:
        probabilities = model.predict(images, verbose=0)
        predictions = np.argmax(probabilities, axis=1)
        y_true.extend(labels.numpy().tolist())
        y_pred.extend(predictions.tolist())

    report = classification_report(
        y_true,
        y_pred,
        target_names=class_names,
        digits=4,
        zero_division=0,
    )
    matrix = confusion_matrix(y_true, y_pred)

    report_path = output_dir / "classification_report.txt"
    matrix_path = output_dir / "confusion_matrix.csv"

    report_path.write_text(report, encoding="utf-8")
    np.savetxt(matrix_path, matrix, fmt="%d", delimiter=",")

    print("\nReporte de clasificacion:")
    print(report)
    print(f"Reporte guardado en: {report_path.resolve()}")
    print(f"Matriz de confusion guardada en: {matrix_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="Entrena una CNN OCR para caracteres de placas.")
    parser.add_argument("--dataset", default="Dataset_OCR_Final")
    parser.add_argument("--output-dir", default="Modelos")
    parser.add_argument("--model-name", default="cnn_ocr_uk.keras")
    parser.add_argument("--classes-name", default="classes_uk.txt")
    parser.add_argument("--image-size", type=int, default=64)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument(
        "--no-oversample", action="store_true",
        help="Desactiva el oversampling balanceado y usa class_weight en su lugar.",
    )
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_dir = dataset_dir / "train"
    valid_dir = dataset_dir / "valid"
    test_dir = dataset_dir / "test"

    class_names = get_class_names(train_dir)
    num_classes = len(class_names)
    total_train = count_images(train_dir)

    print("Clases detectadas:")
    print(class_names)
    print(f"Numero de clases: {num_classes}")
    print(f"Imagenes de train: {total_train}")
    print(f"Input: {args.image_size}x{args.image_size}x1  | oversample: {not args.no_oversample}")

    classes_path = output_dir / args.classes_name
    save_class_names(class_names, classes_path)
    print(f"Clases guardadas en: {classes_path.resolve()}")

    valid_ds = optimize_dataset(load_split(valid_dir, args.image_size, args.batch_size, shuffle=False))
    test_ds = optimize_dataset(load_split(test_dir, args.image_size, args.batch_size, shuffle=False))

    class_weight = None
    steps_per_epoch = None

    if args.no_oversample:
        # Ruta clasica: dataset normal + class_weight para el desbalance.
        train_ds_raw = load_split(train_dir, args.image_size, args.batch_size, shuffle=True)
        class_weight = compute_weights(train_ds_raw, class_names)
        train_ds = optimize_dataset(train_ds_raw, shuffle=True)
    else:
        # Oversampling balanceado (no se usa class_weight para no corregir dos veces).
        train_ds = make_balanced_train_ds(train_dir, class_names, args.image_size, args.batch_size)
        steps_per_epoch = max(1, total_train // args.batch_size)

    model = build_model(args.image_size, num_classes)
    model.summary()

    model_path = output_dir / args.model_name
    best_model_path = output_dir / f"best_{args.model_name}"

    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            filepath=best_model_path,
            monitor="val_accuracy",
            mode="max",
            save_best_only=True,
            verbose=1,
        ),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=4,
            min_lr=1e-5,
            verbose=1,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=10,
            restore_best_weights=True,
            verbose=1,
        ),
    ]

    model.fit(
        train_ds,
        validation_data=valid_ds,
        epochs=args.epochs,
        steps_per_epoch=steps_per_epoch,
        class_weight=class_weight,
        callbacks=callbacks,
    )

    model.save(model_path)
    print(f"\nModelo final guardado en: {model_path.resolve()}")
    print(f"Mejor modelo guardado en: {best_model_path.resolve()}")

    print("\nEvaluacion final en test:")
    test_loss, test_accuracy = model.evaluate(test_ds, verbose=1)
    print(f"Test loss: {test_loss:.4f}")
    print(f"Test accuracy: {test_accuracy:.4f}")

    evaluate_model(model, test_ds, class_names, output_dir)


if __name__ == "__main__":
    main()
