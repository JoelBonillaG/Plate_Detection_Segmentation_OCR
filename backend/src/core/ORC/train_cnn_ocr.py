import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_class_weight
from tensorflow.keras import layers, models

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
    data_augmentation = tf.keras.Sequential(
        [
            layers.RandomRotation(0.015),
            layers.RandomTranslation(0.04, 0.04),
            layers.RandomZoom(0.08),
            layers.RandomContrast(0.12),
            layers.RandomBrightness(0.10),
        ],
        name="data_augmentation",
    )

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
            layers.Dropout(0.15),

            layers.Conv2D(64, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.Conv2D(64, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.MaxPooling2D(),
            layers.Dropout(0.20),

            layers.Conv2D(128, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.Conv2D(128, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.MaxPooling2D(),
            layers.Dropout(0.25),

            layers.Conv2D(256, 3, padding="same", activation="relu"),
            layers.BatchNormalization(),
            layers.GlobalAveragePooling2D(),

            layers.Dense(256, activation="relu"),
            layers.BatchNormalization(),
            layers.Dropout(0.40),
            layers.Dense(num_classes, activation="softmax"),
        ],
        name="cnn_ocr_plate_chars",
    )

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss=SparseFocalLoss(gamma=2.0),
        metrics=["accuracy"],
    )

    return model


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


def optimize_dataset(dataset, shuffle=False):
    autotune = tf.data.AUTOTUNE
    dataset = dataset.cache()
    if shuffle:
        dataset = dataset.shuffle(2000)
    return dataset.prefetch(autotune)


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
    parser.add_argument("--image-size", type=int, default=48)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--no-class-weight", action="store_true")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_dir = dataset_dir / "train"
    valid_dir = dataset_dir / "valid"
    test_dir = dataset_dir / "test"

    train_ds_raw = load_split(train_dir, args.image_size, args.batch_size, shuffle=True)
    valid_ds_raw = load_split(valid_dir, args.image_size, args.batch_size, shuffle=False)
    test_ds_raw = load_split(test_dir, args.image_size, args.batch_size, shuffle=False)

    class_names = train_ds_raw.class_names
    num_classes = len(class_names)

    print("Clases detectadas:")
    print(class_names)
    print(f"Numero de clases: {num_classes}")

    classes_path = output_dir / args.classes_name
    save_class_names(class_names, classes_path)
    print(f"Clases guardadas en: {classes_path.resolve()}")

    class_weight = None
    if not args.no_class_weight:
        class_weight = compute_weights(train_ds_raw, class_names)
        print("\nClass weights:")
        for class_id, weight in class_weight.items():
            print(f"{class_names[class_id]}: {weight:.4f}")

    train_ds = optimize_dataset(train_ds_raw, shuffle=True)
    valid_ds = optimize_dataset(valid_ds_raw)
    test_ds = optimize_dataset(test_ds_raw)

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
            patience=9,
            restore_best_weights=True,
            verbose=1,
        ),
    ]

    history = model.fit(
        train_ds,
        validation_data=valid_ds,
        epochs=args.epochs,
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
