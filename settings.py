from PySide6.QtWidgets import (
    QLabel, QLineEdit, QPushButton, QFileDialog,
    QRadioButton,
    QDialog, QDialogButtonBox, QFormLayout
)

class SettingsDialog(QDialog):
    def __init__(self, parent=None, db_name=""):
        super().__init__(parent)
        self.setWindowTitle("Настройки приложения")
        self.resize(600, 200)

        self.database_path = QLineEdit()
        self.database_path.setPlaceholderText("Введите путь к новой базе...")
        self.database_path.setText(db_name)
        browse_button = QPushButton("Выбрать")
        browse_button.clicked.connect(self.select_db)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        

        layout = QFormLayout(self)
        layout.addRow("База номеров:", self.database_path)
        

        layout.addWidget(browse_button)
        layout.addWidget(QLabel("Укажите модель для обработки:"))
        self.Easy_button = QRadioButton("Easy OCR")
        self.Paddle_button = QRadioButton("PaddlePaddle OCR")
        self.Easy_button.setChecked(True)
        layout.addWidget(self.Easy_button)
        layout.addWidget(self.Paddle_button)


        layout.addWidget(button_box)

        

    def select_db(self):
        db_name, _ = QFileDialog.getOpenFileName(self, "Выберите файл базы")
        if db_name:
            self.database_path.setText(db_name)