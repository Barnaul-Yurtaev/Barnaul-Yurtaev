import sys
from pathlib import Path
import easyocr
import numpy as np
from PIL import Image
import img2pdf
import os
import re
import pandas as pd
from statistics import mode

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QFileDialog,
    QRadioButton, QVBoxLayout, QHBoxLayout, QMessageBox, QProgressBar,
    QMenuBar, QStackedWidget, QDialog, QDialogButtonBox, QFormLayout
)
from PySide6.QtCore import Qt, QObject, Signal, QThread

os.environ["FLAGS_use_mkldnn"] = "0"

from paddleocr import PaddleOCR


ocr = PaddleOCR(
    lang="ru",
    enable_mkldnn=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False
)



reader = easyocr.Reader(['ru'], gpu=False)

CONFIDENTIAL_COORDS = {
    "ОГЭ": (2050, 1500),
    "ЕГЭ": (2100, 1800)
}

subject_codes = {"рус": "01",
                 "мат": "02",
                 "физ": "03",
                 "хим": "04",
                 "био": "06",
                 "ист": "07",
                 "гео": "08",
                 "анг": "09",
                 "общ": "12",
                 "лит": "18",
                 "инф": "25"
                }
subject_codes2 = {
    0: "неизвестный",
    1: "рус",
    2: "мат",
    3: "физ",
    4: "хим",
    6: "био",
    7: "ист",
    8: "гео",
    9: "анг",
    12: "общ",
    18: "лит",
    5: "инф",
    22: "мат_б"
}
# ------------------- Вспомогательные функции -------------------
def load_image_for_ocr(image_input):
    """
    Загружает изображение (путь, PIL.Image или numpy-массив),
    гарантированно приводит к RGB/uint8 и проверяет на пустоту.
    """
    if isinstance(image_input, str):
        try:
            img = Image.open(image_input)
        except Exception as e:
            raise ValueError(f"Не удалось открыть файл: {image_input}") from e
    elif isinstance(image_input, np.ndarray):
        img = Image.fromarray(image_input)
    elif isinstance(image_input, Image.Image):
        img = image_input
    else:
        raise TypeError("image должен быть путём, PIL.Image или numpy-массивом")

    if img.size == (0, 0):
        raise ValueError("Изображение пустое (0x0)")

    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')

    img_array = np.array(img)
    if img_array.dtype != np.uint8:
        img_array = img_array.astype(np.uint8)

    return img_array

def into_one_PDF(image_paths: list, output_path: str) -> None:
    """Собирает список изображений в один PDF."""
    with open(output_path, "wb") as f:
        f.write(img2pdf.convert([Path(i) for i in image_paths]))

# ------------------- Worker для фоновой обработки -------------------
class Worker(QObject):
    progressChanged = Signal(int)       # 0..100
    statusMessage = Signal(str)         # сообщение пользователю
    finished = Signal()                 # работа завершена
    errorOccurred = Signal(str)         # сообщение об ошибке

    def __init__(self, source_folder, output_folder, oge_ege, conf_image_path, model):
        super().__init__()
        self.source_folder = source_folder
        self.output_folder = output_folder
        self.oge_ege = oge_ege
        self.conf_image_path = conf_image_path
        self.model = model

        # Локальные хранилища (аналог глобальных переменных)
        self.result = {}      # {Номер КИМ: [список полных путей]}
        self.variants = {}    # {Номер КИМ: [список вариантов]}
        self.subjects = {}    # {Номер КИМ: предмет}
        self.wrong_numbers = [] # [{"file": название файла, "numbers_id": номер КИМ, "variant": вариант}]


    def reading_and_writing(self, img, method="Номер КИМ", model="Easy"):
        """Распознавание области (использует self.result, self.variants, self.subjects)"""
        map_oge_ege = {
            "Номер КИМ": {
                "ОГЭ": [760, 900, 100, 1000],
                "ЕГЭ": [760, 900, 150, 1000]
            },
            "Предмет 1 страница": {
                "ОГЭ": [750, 900, 1150, 1400],
                "ЕГЭ": [800, 1000, 1150, 1600]
            },
            "Предмет 2 страница": {
                "ОГЭ": [400, 550, 1200, 1500],
                "ЕГЭ": [430, 560, 950, 1400]
            },
            "Текст предмета 1 страница": {
                "ОГЭ": [750, 900, 1350, 1700],
                "ЕГЭ": [800, 1000, 1500, 1800]
            },
            "Текст предмета 2 страница": {
                "ОГЭ": [400, 550, 1500, 1950],
                "ЕГЭ": [430, 550, 1300, 1650]
            }
        }

        img_array = load_image_for_ocr(img)
        coords = map_oge_ege[method][self.oge_ege]
        cropped = img_array[coords[0]:coords[1], coords[2]:coords[3]]
        if model == "Easy":
            output = ''.join(reader.readtext(cropped, detail=0, paragraph=False, decoder="beamsearch", beamWidth=6))
        else:
            results = list(ocr.predict(cropped))
            output = ' '.join(sorted(results[0]["rec_texts"], key=len))
        print(output)

        if output.strip() == '':
            print(f'Пустой результат распознавания в файле: {img if isinstance(img, str) else "image"}')
            if method == "Номер КИМ":
                if self.result:
                    numbers_id = list(self.result.keys())[-1]
                    variant = self.variants[numbers_id][-1]
                else:
                    raise ValueError("Не удалось распознать номер КИМ на первом файле")
            else:
                subject_id = ""
                subject_letters = ""
        else:
            numbers = re.findall(r'\d', output)
            letters = re.findall(r'[А-Яа-яЁё]', output)
            if method == "Номер КИМ":
                if len(numbers) >= 7:
                    numbers_id = ''.join(numbers[-6:])
                    variant = numbers[-7]
                elif len(numbers) == 6:
                    numbers_id = ''.join(numbers[-6:])
                    variant = '0'
                else:
                    if self.result:
                        numbers_id = list(self.result.keys())[-1]
                        variant = self.variants[numbers_id][-1]
                    else:
                        raise ValueError(f"Не удалось определить номер КИМ: {output}")
            else:
                subject_id = numbers
                subject_letters = letters

        if method == "Номер КИМ":
            return numbers_id, variant
        else:
            return subject_id, subject_letters

    def process(self):
        """Основной метод обработки, вызывается в отдельном потоке"""

        real_numbers = r"C:\Users\79831\Desktop\Python_projects\Подарок папе\print-blanks.xlsm"
        real_numbers_file = pd.read_excel(real_numbers, sheet_name = "bas", usecols = [1,2])

        # Создание выходной папки
        os.makedirs(self.output_folder, exist_ok=True)
        # Создание папки с ошибочно определенными номерами КИМ
        os.makedirs(os.path.join(self.output_folder, "wrong_kim_numbers"), exist_ok=True)

        try:
            # Сбор всех файлов
            files_to_process = []
            for root, dirs, files in os.walk(self.source_folder):
                for file in sorted(files):
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        files_to_process.append(os.path.join(root, file).replace('\\', '/'))

            total_files = len(files_to_process)
            if total_files == 0:
                self.errorOccurred.emit("В выбранной папке нет изображений.")
                self.finished.emit()
                return

            # Обработка каждого файла
            for i, file_path in enumerate(files_to_process):
                percent = int((i + 1) * 100 / total_files)
                self.progressChanged.emit(percent)
                self.statusMessage.emit(f"Обрабатывается {os.path.basename(file_path)}...")

                try:
                    numbers_id, variant = self.reading_and_writing(file_path, method="Номер КИМ", model=self.model)
                    if int(numbers_id) in list(real_numbers_file.kim) and int(variant) != real_numbers_file[real_numbers_file.kim == int(numbers_id)]["var"].iloc[0]:
                        variant = real_numbers_file[real_numbers_file.kim == int(numbers_id)]["var"].iloc[0]

                    if numbers_id in self.result:
                        self.result[numbers_id].append(file_path)
                        self.variants[numbers_id].append(variant)

                        # Если это вторая страница и предмет ещё не определён
                        if len(self.result[numbers_id]) == 2 and self.subjects.get(numbers_id, "") == "":
                            subject_id, _  = self.reading_and_writing(file_path,  method = "Предмет 2 страница", model=self.model)
                            subject_id = "".join(subject_id)
                            self.subjects[numbers_id] = subject_id if len(subject_id) == 2 else ("0" + subject_id)
                        # Если после двух страниц текст не определился - используем буквы
                        if self.subjects.get(numbers_id, "") == "":
                            _, subject_letters = self.reading_and_writing(file_path, method = "Текст предмета 2 страница", model=self.model)
                            subject_letters = "".join(subject_letters)
                            subject_letters_set = set(subject_letters.lower())
                            overlap = {key: len(set(key) & subject_letters_set) for key in subject_codes}
                            # если совпадение со всеми буквами предметов нулевое
                            if not any(overlap.values()):
                                subject_id = ""
                            else:
                              subject_id = subject_codes[max(overlap, key=overlap.get)]
                            self.subjects[numbers_id] = subject_id

                    else:
                        # Вставка конфиденциальной информации на первой странице
                        main_img = Image.open(file_path)
                        insert_img = Image.open(self.conf_image_path)
                        coords = CONFIDENTIAL_COORDS[self.oge_ege]
                        main_img.paste(insert_img, coords)
                        main_img.save(file_path)
                        insert_img.close()
                        main_img.close()

                        self.result[numbers_id] = [file_path]
                        self.variants[numbers_id] = [variant]

                        # Распознаём предмет на первой странице
                        subject_id, _ = self.reading_and_writing(file_path, method = "Предмет 1 страница")
                        subject_id = "".join(subject_id)
                        self.subjects[numbers_id] = subject_id if len(subject_id) == 2 else ("0" + subject_id)

                        # Закомментировано до востребования - определение кода предмета по буквам вместо цифр
                        # if self.subjects.get(numbers_id, "") == "":
                        #     _, subject_letters = reading_and_writing(file_path, method = "Текст предмета 2 страница")
                        #     subject_letters = "".join(subject_letters)
                        #     subject_letters_set = set(subject_letters.lower())
                        #     overlap = {key: len(set(key) & subject_letters_set) for key in subject_codes}
                        # # если совпадение со всеми буквами предметов нулевое
                        # if not any(overlap.values()):
                        #     subject_id = ""
                        # else:
                        #   subject_id = subject_codes[max(overlap, key=overlap.get)]
                        #     self.subjects[numbers_id] = subject_id
                    if not numbers_id == "" and not int(numbers_id) in list(real_numbers_file.kim):
                        self.wrong_numbers.append({"file": file, "numbers_id": int(numbers_id), "variant": int(variant)})
                        img = Image.open(file_path)
                        img.save(os.path.join(self.output_folder, "wrong_kim_numbers", file))
                except Exception as e:
                    self.errorOccurred.emit(f"Ошибка в файле {file_path}: {e}")
                    continue

            # Запись xlsx файла с неверными КИМ
            wrong_numbers_data = pd.DataFrame(self.wrong_numbers)
            wrong_numbers_data.to_excel(f"{self.output_folder}/wrong_kim_numbers/wrong_kim_numbers.xlsx")

            # Сборка PDF для каждого номера КИМ
            for num_id, images in self.result.items():
                pdf_path = os.path.join(self.output_folder, f'{num_id}.pdf')
                try:
                    into_one_PDF(images, pdf_path)
                    self.statusMessage.emit(f'Создан PDF: {pdf_path} ({len(images)} стр.)')
                except Exception as e:
                    self.errorOccurred.emit(f'Ошибка при создании PDF {num_id}: {e}')

            # Подготовка данных для Excel
            for key, arg in self.variants.items():
                if arg:
                    self.variants[key] = mode(arg)
                else:
                    self.variants[key] = ""

            df_var = pd.DataFrame.from_dict(self.variants, orient="index").reset_index()
            df_var.columns = ['Номер КИМ', 'Номер варианта']

            df_sub = pd.DataFrame.from_dict(self.subjects, orient="index").reset_index()
            df_sub.columns = ['Номер КИМ', 'Номер предмета']

            df = pd.merge(df_var, df_sub, on='Номер КИМ', how='left')
            df['Номер КИМ'] = pd.to_numeric(df['Номер КИМ'], errors='coerce')
            df['Номер предмета'] = pd.to_numeric(df['Номер предмета'], errors='coerce')
            df['Номер варианта'] = pd.to_numeric(df['Номер варианта'], errors='coerce')


            excel_path = os.path.join(self.output_folder, "результат.xlsx")
            df.to_excel(excel_path, index=False)
            df_paths = pd.DataFrame.from_dict({"Номер КИМ": self.result.keys(), "Листы работы": self.result.values()})
            df_paths["Номер КИМ"] = pd.to_numeric(df_paths['Номер КИМ'], errors='coerce')
            

            df = df.merge(df_paths, on="Номер КИМ")
            
            for i in pd.unique(df['Номер предмета']):
                folder_path = os.path.join(self.output_folder, f'{subject_codes2[i]}')
                papers = [item for subarray in pd.array(df[df['Номер предмета'] == i]["Листы работы"]) for item in subarray[1 if self.oge_ege == "ОГЭ" else 2:]]
                if papers:
                    try:
                        os.makedirs(folder_path)
                        for j in papers:
                            img = Image.open(j)
                            img.save(os.path.join(folder_path, j.split("/")[-1]))
                        self.statusMessage.emit(f'Создана папка: {folder_path} ({len(papers)} листов)')
                    except:
                        continue
            self.statusMessage.emit("Готово. Файлы сохранены.")

        except Exception as e:
            self.errorOccurred.emit(f"Критическая ошибка: {e}")
        finally:
            self.finished.emit()

# ------------------- Основное окно приложения -------------------
class FileProcessor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Обработка файлов")
        self.resize(600, 250)

        self.worker_thread = None
        self.worker = None
        self.model_name = "Easy"

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
        dialog = SettingsDialog(self)
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

        conf_img = "conf [cRzcdS].bmp"  # путь к изображению с конфиденциальной информацией

        # Блокируем кнопку и показываем прогресс-бар
        self.process_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText("Начинаем обработку...")
        self.status_label.show()

        # Создаём Worker и поток
        self.worker_thread = QThread()
        self.worker = Worker(source, output, oge_ege, conf_img, self.model_name)
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

    def on_processing_finished(self):
        """Слот вызывается после завершения работы Worker"""
        self.progress_bar.hide()
        self.status_label.setText("Обработка завершена")
        self.process_button.setEnabled(True)

    def show_error(self, msg):
        """Отображение ошибок из потока"""
        QMessageBox.warning(self, "Ошибка", msg)

# ------------------- Диалог настроек -------------------
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки приложения")
        self.resize(300, 200)

        self.database_path = QLineEdit()
        self.database_path.setPlaceholderText("Введите путь к новой базе...")
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

# ------------------- Запуск приложения -------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FileProcessor()
    window.show()
    sys.exit(app.exec())