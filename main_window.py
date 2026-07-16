from settings import SettingsDialog
from process import Worker
from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QFileDialog,
    QRadioButton, QVBoxLayout, QHBoxLayout, QMessageBox, QProgressBar,
    QMenuBar, QDialog,
)
from PySide6.QtCore import QThread
from pathlib import Path

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Обработка файлов")
        self.resize(700, 210)

        self.worker_thread = None
        self.worker = None
        self.model_name = "Easy"
        self.db_path = r"C:\Users\user\Desktop\OCR Project\print-blanks.xlsm"

        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout()
        self.menu_bar = QMenuBar()

        # Меню "Настройки"
        settings_menu = self.menu_bar.addMenu("&Настройки")
        settings_action = settings_menu.addAction("Параметры...")
        settings_action.triggered.connect(self.open_settings_dialog)
        self.main_layout.addWidget(self.menu_bar)

        # Выбор папки с исходными сканами
        path_input_layout = QHBoxLayout()
        self.dir_input_path = QLineEdit()
        self.dir_input_path.setPlaceholderText("Введите путь к папке...")
        browse_input_btn = QPushButton("Выбрать")
        browse_input_btn.clicked.connect(self.select_input_folder)
        path_input_layout.addWidget(QLabel("Папка со сканами:"))
        path_input_layout.addWidget(self.dir_input_path)
        path_input_layout.addWidget(browse_input_btn)

        # Выбор папки для сохранения и имя выходной папки
        path_output_layout = QHBoxLayout()
        self.dir_output_path = QLineEdit()
        self.dir_output_path.setPlaceholderText("Введите путь к папке...")
        self.dir_output_name = QLineEdit()
        self.dir_output_name.setPlaceholderText("Введите имя папки...")
        browse_output_btn = QPushButton("Выбрать")
        browse_output_btn.clicked.connect(self.select_output_folder)
        path_output_layout.addWidget(QLabel("Папка для сохранения:"))
        path_output_layout.addWidget(self.dir_output_path)
        path_output_layout.addWidget(browse_output_btn)
        path_output_layout.addWidget(self.dir_output_name)

        self.main_layout.addLayout(path_input_layout)
        self.main_layout.addLayout(path_output_layout)

        # Выбор типа экзамена
        options_layout = QVBoxLayout()
        options_layout.addWidget(QLabel("Выберите экзамен:"))
        self.OGE_button = QRadioButton("ОГЭ")
        self.EGE_button = QRadioButton("ЕГЭ")
        self.OGE_button.setChecked(True)
        options_layout.addWidget(self.OGE_button)
        options_layout.addWidget(self.EGE_button)
        self.main_layout.addLayout(options_layout)

        # Кнопка запуска обработки
        self.process_button = QPushButton("Обработать")
        self.process_button.clicked.connect(self.start_processing)
        self.main_layout.addWidget(self.process_button)

        # Прогресс-бар и статус (изначально скрыты)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.status_label = QLabel()
        self.status_label.hide()
        self.main_layout.addWidget(self.progress_bar)
        self.main_layout.addWidget(self.status_label)
        

        self.setLayout(self.main_layout)

    def open_settings_dialog(self):
        """Открывает диалог настроек"""
        dialog = SettingsDialog(self, db_name=self.db_path, model_name=self.model_name)
        if dialog.exec() == QDialog.Accepted:
            # Пока сохраняем путь к базе (можно использовать в будущем)
            self.db_path = dialog.database_path.text()
            self.model_name = "Paddle" if dialog.Paddle_button.isChecked() else "Easy"


    def select_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку со сканами")
        if folder:
            self.dir_input_path.setText(folder)

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if folder:
            self.dir_output_path.setText(folder)

    def start_processing(self):
        """Запускает обработку в отдельном потоке"""
        # Проверка заполнения полей
        if not self.dir_input_path.text().strip():
            QMessageBox.warning(self, "Ошибка", "Укажите папку со сканами")
            return
        if not self.dir_output_path.text().strip():
            QMessageBox.warning(self, "Ошибка", "Укажите папку для сохранения")
            return
        if not self.dir_output_name.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите имя папки")
            return

        source = Path(self.dir_input_path.text().strip())
        output = Path(self.dir_output_path.text().strip()) / self.dir_output_name.text().strip()
        oge_ege = "ОГЭ" if self.OGE_button.isChecked() else "ЕГЭ"

        conf_img = "conf [cRzcdS].bmp"  # путь к изображению с плашкой

        # Блокируем кнопку и показываем прогресс-бар
        self.process_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("Начинаем обработку...")
        self.status_label.show()

        # Создаём Worker и поток
        self.worker_thread = QThread()
        self.worker = Worker(source, output, oge_ege, conf_img, self.model_name, self.db_path)
        self.worker.moveToThread(self.worker_thread)

        # Подключаем сигналы
        self.worker.progressChanged.connect(self.progress_bar.setValue)
        self.worker.statusMessage.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_processing_finished)
        self.worker.errorOccurred.connect(self.show_error)
        

        self.worker_thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def on_processing_finished(self, count):
        """Слот вызывается после завершения работы Worker"""
        self.progress_bar.hide()
        self.status_label.setText(f"Обработка завершена. Обработано {count} работ.")
        self.process_button.setEnabled(True)

    def show_error(self, msg):
        """Отображение ошибок из потока"""
        QMessageBox.warning(self, "Ошибка", msg)
