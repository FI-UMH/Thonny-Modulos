# -*- coding: utf-8 -*-
"""
configuracion/corregir.py — Plugin para Thonny

Incluye:
 - Ventana inicial para pedir DNI + instrucciones
 - Cabecera automática al crear archivos (con DNI rellenado)
 - Activar vistas de Variables y Consola
 - Obligación de guardar antes de ejecutar/depurar
 - Menús:
      • 📥 Descargar ficheros
      • ✅ Corregir programa

Y dentro del propio archivo:
 - BLOQUE: Descargar ficheros
 - BLOQUE: Corregir programa
"""

import sys
import os
import json
import re
import subprocess
import tempfile
import traceback
import io
import zipfile
import urllib.request
import socket
import uuid
from collections import Counter

from thonny import get_workbench
from tkinter import (
    messagebox,
    filedialog,
    Toplevel,
    Text,
    Scrollbar,
    Label,
    Entry,
    Button,
    Frame,
)
import tkinter.font as tkfont
import requests


# ======================================================================
#                    VARIABLES GLOBALES
# ======================================================================

ALUMNO_DNI = ""  # Se rellena en la ventana inicial
ZIP_URL = "https://github.com/FI-UMH/Thonny-Ficheros/archive/refs/heads/main.zip"

_PAREN_RE = re.compile(r"\([^()]*\)")
_HDR_DNI_RE = re.compile(r"^\s*#\s*DNI\s*=\s*(.+)", re.MULTILINE | re.IGNORECASE)
_HDR_EJER_RE = re.compile(r"^\s*#\s*EJERCICIO\s*=\s*(.+)", re.MULTILINE | re.IGNORECASE)
EXCLUDE = {"alumno.py", "stdin.txt", "stdout.txt"}


# ======================================================================
#                    UTILIDADES THONNY COMUNES
# ======================================================================

def _get_editor_text():
    """Devuelve el texto del editor actual de Thonny o None."""
    try:
        wb = get_workbench()
        editor = wb.get_editor_notebook().get_current_editor()
        if not editor:
            return None
        try:
            return editor.get_text_widget().get("1.0", "end-1c")
        except Exception:
            return editor.get_text()
    except Exception:
        return None


# ======================================================================
#          VENTANA INICIAL — PEDIR DNI + INSTRUCCIONES
# ======================================================================

def pedir_dni_e_instrucciones():
    """Muestra una ventana inicial con instrucciones y campo para DNI."""
    wb = get_workbench()
    top = Toplevel(wb)
    top.title("Inicio del ejercicio")
    top.geometry("700x360")
    top.resizable(False, False)
    top.transient(wb)
    top.grab_set()

    frame = Frame(top)
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    instrucciones = (
        "INSTRUCCIONES DEL EJERCICIO\n\n"
        "1. Introduce tu DNI en el cuadro inferior.\n"
        "2. Pulsa 'Aceptar'. Ese DNI se escribirá automáticamente en la cabecera.\n"
        "3. No borres la cabecera del archivo.\n"
        "4. Escribe tu programa debajo de la cabecera.\n"
        "5. Guarda el archivo antes de ejecutar o corregir.\n"
    )

    lbl = Label(frame, text=instrucciones, justify="left", anchor="w", font=("Arial", 11))
    lbl.pack(fill="x", pady=(0, 20))

    # Fila con texto + Entry en la misma línea
    fila = Frame(frame)
    fila.pack(fill="x", pady=(0, 20))

    lbl_dni = Label(fila, text="DNI del alumno:", font=("Arial", 11))
    lbl_dni.pack(side="left")

    entry_dni = Entry(fila, width=18, font=("Arial", 12))
    entry_dni.pack(side="left", padx=10)

    def aceptar(event=None):
        dni = entry_dni.get().strip()
        if not dni:
            messagebox.showerror(
                "DNI obligatorio",
                "Debes introducir tu DNI para continuar.",
                parent=top,
            )
            return

        global ALUMNO_DNI
        ALUMNO_DNI = dni
        top.destroy()

    btn_ok = Button(frame, text="Aceptar", command=aceptar, width=12, font=("Arial", 11))
    btn_ok.pack(pady=10)

    def al_cerrar():
        if not ALUMNO_DNI:
            messagebox.showerror(
                "DNI obligatorio",
                "Debes introducir tu DNI para continuar.",
                parent=top,
            )
        else:
            top.destroy()

    top.protocol("WM_DELETE_WINDOW", al_cerrar)
    entry_dni.focus_set()
    top.bind("<Return>", aceptar)

    wb.wait_window(top)


# ======================================================================
#                 BLOQUE 1 — DESCARGAR FICHEROS
# ======================================================================

def descargar_ficheros():
    """Descarga el ZIP de ejercicios y lo extrae en una carpeta elegida."""
    carpeta = filedialog.askdirectory(title="Selecciona carpeta destino")
    if not carpeta:
        return

    try:
        req = urllib.request.Request(
            ZIP_URL,
            headers={"User-Agent": "ThonnyFileLoader"},
        )
        data = urllib.request.urlopen(req, timeout=20).read()

        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue

                # Quitar el primer directorio del ZIP
                out = name.split("/", 1)[1]
                dest_path = os.path.join(carpeta, out)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(z.read(name))

        messagebox.showinfo("Descargar ficheros", "Ficheros descargados correctamente.")
    except Exception as e:
        messagebox.showerror("Error al descargar ficheros", str(e))


# ======================================================================
#                 BLOQUE 2 — CORREGIR PROGRAMA
# ======================================================================

def _paren_counter(s: str) -> Counter:
    """Normaliza salidas usando tokens entre paréntesis."""
    if s is None:
        s = ""
    raw = _PAREN_RE.findall(s)
    norm = []
    for tok in raw:
        inner = tok[1:-1]
        inner_no_spaces = re.sub(r"\s+", "", inner)
        norm.append("(" + inner_no_spaces + ")")
    return Counter(norm)


def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return b.decode(enc)
        except Exception:
            continue
    return b.decode("utf-8", errors="replace")


def _extraer_datos_cabecera(src: str):
    """
    Extrae DNI y EJERCICIO de la cabecera:

    # DNI = 12345678X
    # EJERCICIO = p001
    """
    dni = None
    ejercicio = None

    m_dni = _HDR_DNI_RE.search(src)
    if m_dni:
        dni = m_dni.group(1).strip()

    m_ejer = _HDR_EJER_RE.search(src)
    if m_ejer:
        ejercicio = m_ejer.group(1).strip()

    return dni, ejercicio


def mostrar_error_scroll(titulo, mensaje):
    """Ventana con scroll para mostrar mensajes largos, con títulos en negrita."""
    ventana = Toplevel()
    ventana.title(titulo)
    ventana.geometry("800x500")

    txt = Text(ventana, wrap="none")
    txt.pack(fill="both", expand=True)

    scroll_y = Scrollbar(ventana, orient="vertical", command=txt.yview)
    scroll_y.pack(side="right", fill="y")
    txt.configure(yscrollcommand=scroll_y.set)

    scroll_x = Scrollbar(ventana, orient="horizontal", command=txt.xview)
    scroll_x.pack(side="bottom", fill="x")
    txt.configure(xscrollcommand=scroll_x.set)

    txt.insert("1.0", mensaje)

    # Fuente en negrita para los títulos
    base_font = tkfont.Font(font=txt["font"])
    bold_font = base_font.copy()
    bold_font.configure(weight="bold")

    txt.tag_configure("titulo", font=bold_font)

    titulos = (
        "CONTEXTO INICIAL",
        "RESULTADO OBTENIDO",
        "RESULTADO CORRECTO",
    )

    for palabra in titulos:
        start = "1.0"
        while True:
            pos = txt.search(palabra, start, stopindex="end")
            if not pos:
                break
            end = f"{pos}+{len(palabra)}c"
            txt.tag_add("titulo", pos, end)
            start = end

    txt.config(state="disabled")


def _preprocesar_codigo(src: str) -> str:
    """Reescribe input() por inputt() e inserta la definición de inputt()."""
    src_mod = re.sub(r"input\s*\(", "inputt(", src)
    cabecera = (
        "def inputt(cadena=\"\"):\n"
        "    x = input(cadena)\n"
        "    print(x)\n"
        "    return x\n\n"
    )
    return cabecera + src_mod


def _run_single_test(src_code: str, test: dict) -> dict:
    """Ejecuta un test en un directorio temporal."""
    res = {
        "ok_stdout": False,
        "ok_files": False,
        "stdout_alumno": "",
        "files_end": {},
        "error": None,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="corr_") as td:
            alumno_py = os.path.join(td, "alumno.py")

            src_mod = _preprocesar_codigo(src_code)
            with open(alumno_py, "w", encoding="utf-8") as f:
                f.write(src_mod)

            stdin_content = test.get("stdin", "")

            # ficheros iniciales
            for fn, content in (test.get("filesIni") or {}).items():
                fn_path = os.path.join(td, fn)
                os.makedirs(os.path.dirname(fn_path) or td, exist_ok=True)
                with open(fn_path, "w", encoding="utf-8") as f:
                    f.write(content)

            completed = subprocess.run(
                [sys.executable, alumno_py],
                cwd=td,
                input=stdin_content.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            stdout = _decode_bytes(completed.stdout)
            res["stdout_alumno"] = stdout

            # ficheros finales
            files_now = {}
            for name in os.listdir(td):
                p = os.path.join(td, name)
                if os.path.isdir(p) or name in EXCLUDE:
                    continue
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    files_now[name] = f.read()
            res["files_end"] = files_now

            exp_stdout = test.get("stdout", "")
            exp_files = test.get("filesEnd") or {}

            res["ok_stdout"] = (_paren_counter(stdout) == _paren_counter(exp_stdout))
            res["ok_files"] = (files_now == exp_files)

    except subprocess.TimeoutExpired:
        res["error"] = "Tiempo excedido."
    except Exception as e:
        res["error"] = f"Error en test: {e}\n{traceback.format_exc()}"

    return res


def _subir_ejercicios(ejercicio, dni, src_code):
    """Sube el ejercicio a los scripts de Google Apps."""
    hostname = socket.gethostname()

    # IP local
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
    except Exception:
        ip_local = None

    # MAC principal
    mac_raw = uuid.getnode()
    mac = ":".join(f"{(mac_raw >> shift) & 0xff:02x}" for shift in range(40, -1, -8))

    url_fi = (
        "https://script.google.com/macros/s/"
        "AKfycby3wCtvhy2sqLmp9TAl5aEQ4zHTceMAxwA_4M2HCjFJQpvxWmstEoRa5NohH0Re2eQa/exec"
    )
    url_pomares = (
        "https://script.google.com/macros/s/"
        "AKfycbxwDPaWyBATk_xRuxnGLEtPhpULa3WJHVidj7_7ttYhdYwmiVVI1wJxwkUDrQespcku-A/exec"
    )

    data = {
        "key": "Thonny#fi",
        "ordenador": hostname,
        "ip": ip_local,
        "mac": mac,
        "dni": dni,
        "ejercicio": ejercicio,
        "fuente": src_code,
    }

    # No importa demasiado la respuesta de FI; se devuelve la de Pomares
    requests.post(url_fi, data=data)
    respuesta_pomares = requests.post(url_pomares, data=data)

    return respuesta_pomares.text

def corregir_programa(DATOS_LOADED):
    """Lee el código del editor, ejecuta los tests y sube el ejercicio."""
    src = _get_editor_text()
    if not src:
        messagebox.showerror("Corregir Programa", "No pude leer el código del editor.")
        return

    dni, ejercicio = _extraer_datos_cabecera(src)
    if not dni or not ejercicio:
        messagebox.showerror(
            "Corregir Programa",
            "No se pudieron extraer DNI y EJERCICIO de la cabecera.",
        )
        return

    # Buscar tests.json en DATOS_LOADED
    key = None
    for k in DATOS_LOADED:
        if k.lower() in ("tests.json", "test.json"):
            key = k
            break

    if not key:
        messagebox.showerror("Corregir Programa", "No encontré tests.json en memoria.")
        return

    try:
        all_tests = json.loads(_decode_bytes(DATOS_LOADED[key]))
    except Exception as e:
        messagebox.showerror("Corregir Programa", f"Error leyendo {key}:\n{e}")
        return

    if ejercicio not in all_tests:
        messagebox.showerror(
            "Corregir Programa",
            f"No hay tests para el ejercicio {ejercicio}.",
        )
        return

    tests = all_tests[ejercicio]

    # Ejecutar tests uno a uno
    for idx, test in enumerate(tests, start=1):
        result = _run_single_test(src, test)

        if result["error"]:
            messagebox.showerror("Error", f"⚠️ Error en test #{idx}:\n{result['error']}")
            return

        if not result["ok_stdout"] or not result["ok_files"]:
            files_ini_text = "".join(
                f"'{fn}':\n{content}\n"
                for fn, content in (test.get("filesIni") or {}).items()
            )
            files_end_text = "".join(
                f"'{fn}':\n{content}\n"
                for fn, content in (result.get("files_end") or {}).items()
            )
            files_exp_text = "".join(
                f"'{fn}':\n{content}\n"
                for fn, content in (test.get("filesEnd") or {}).items()
            )

            msg = (
                "El ejercicio no supera el test\n \n"
                "▶ CONTEXTO INICIAL\n"
                "─────── Teclado ───────\n"
                f"{test.get('stdin', '')}\n"
                "─────── Ficheros ───────\n"
                f"{files_ini_text}\n"
                "▶ RESULTADO OBTENIDO\n"
                "─────── Pantalla ───────\n"
                f"{result['stdout_alumno']}\n"
                "─────── Ficheros ───────\n"
                f"{files_end_text}\n"
                "▶ RESULTADO CORRECTO\n"
                "─────── Pantalla ───────\n"
                f"{test.get('stdout', '')}\n"
                "─────── Ficheros ───────\n"
                f"{files_exp_text}"
            ).replace("\n\n", "\n")

            mostrar_error_scroll("Corregir Programa", msg)
            return

    # Si llega aquí, TODOS los tests han sido superados
    wb = get_workbench()

    # 1) Ventana de espera sin botón Aceptar, con fuente más grande
    espera = Toplevel(wb)
    espera.title("Corregir Programa")
    espera.geometry("420x180")
    espera.resizable(False, False)
    espera.transient(wb)

    frame = Frame(espera)
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    lbl1 = Label(frame, text="✅ Todos los tests superados.", font=("Arial", 13, "bold"))
    lbl1.pack(pady=(0, 10))

    lbl2 = Label(frame, text="Espere un momento...", font=("Arial", 12))
    lbl2.pack()

    espera.update_idletasks()
    try:
        espera.grab_set()
    except Exception:
        pass

    # 2) Subida del ejercicio
    try:
        respuesta = _subir_ejercicios(ejercicio, dni, src)
    except Exception as e:
        espera.destroy()
        messagebox.showerror("Error en la entrega de ejercicios", str(e))
        return

    # Cerrar ventana de espera
    espera.destroy()

    # 3) Nueva ventana con resumen de ejercicios entregados
    final = Toplevel(wb)
    final.title("Entrega ejercicios")
    final.geometry("650x400")
    final.resizable(True, True)  # se puede redimensionar
    final.transient(wb)

    frame2 = Frame(final)
    frame2.pack(fill="both", expand=True, padx=10, pady=10)

    # Texto con scroll y ajuste por palabras
    texto = f"Ejercicios entregados.\n\n{respuesta}"

    text_widget = Text(frame2, wrap="word")
    text_widget.pack(side="left", fill="both", expand=True)

    scroll_y = Scrollbar(frame2, orient="vertical", command=text_widget.yview)
    scroll_y.pack(side="right", fill="y")
    text_widget.configure(yscrollcommand=scroll_y.set)

    text_widget.insert("1.0", texto)
    text_widget.config(state="disabled")  # solo lectura

    # Botón OK para cerrar
    btn_ok = Button(final, text="OK", width=10, command=final.destroy)
    btn_ok.pack(pady=(5, 10))

    final.update_idletasks()
    try:
        final.grab_set()
    except Exception:
        pass




# ======================================================================
#         BLOQUE 3 — CONFIGURACIÓN DE THONNY (CABECERA, VISTAS, ...)
# ======================================================================

def _config_cabecera():
    """Inserta cabecera con DNI en todos los editores nuevos."""
    from thonny.editors import Editor

    cabecera = f"# DNI = {ALUMNO_DNI}\n# EJERCICIO = \n\n"
    _original_init = Editor.__init__

    def _hook(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        if self.get_filename() is None:
            try:
                widget = self.get_text_widget()
                widget.insert("1.0", cabecera)
            except Exception:
                self.set_text(cabecera)

    Editor.__init__ = _hook

    # Refuerzo para el primer editor ya abierto
    def inicial():
        wb = get_workbench()
        ed = wb.get_editor_notebook().get_current_editor()
        if ed and ed.get_filename() is None:
            try:
                w = ed.get_text_widget()
                w.delete("1.0", "end")
                w.insert("1.0", cabecera)
            except Exception:
                ed.set_text(cabecera)

    wb = get_workbench()
    wb.after(500, inicial)


def _config_vistas():
    wb = get_workbench()

    def activar():
        try:
            wb.show_view("VariablesView", True)
            wb.show_view("ShellView", True)
        except Exception:
            pass

    wb.after(1000, activar)


def _config_guardar_antes():
    wb = get_workbench()

    def necesita_guardar():
        ed = wb.get_editor_notebook().get_current_editor()
        if ed is None:
            return False

        filename = ed.get_filename()

        if filename is None:
            messagebox.showinfo("Guardar archivo", "Debes guardar el archivo antes de continuar.")
            wb.get_menu("file").invoke_command("save_as")
            return True

        if ed.is_modified():
            messagebox.showinfo("Guardar archivo", "Guarda el archivo antes de continuar.")
            wb.get_menu("file").invoke_command("save")
            return True

        return False

    def intercept(event=None):
        if necesita_guardar():
            return "break"

    wb.bind("<<RunScript>>", intercept, True)
    wb.bind("<<RunCurrentScript>>", intercept, True)
    wb.bind("<<DebugRun>>", intercept, True)
    wb.bind("<<DebugCurrentScript>>", intercept, True)


# ======================================================================
#                 FUNCIÓN PRINCIPAL DE CONFIGURACIÓN
# ======================================================================

def configurar(DATOS_LOADED):
    """
    Punto de entrada del plugin.
    Se espera que descargar_configuracion.py llame a configurar(DATOS_LOADED).
    """
    wb = get_workbench()

    # 1) Pedir DNI (bloqueante)
    pedir_dni_e_instrucciones()

    # 2) Configuración base (ya con ALUMNO_DNI)
    _config_cabecera()
    _config_vistas()
    _config_guardar_antes()

    # 3) Menús de herramientas
    def crear_menus():
        menu = wb.get_menu("tools")
        if not menu:
            wb.after(500, crear_menus)
            return

        menu.add_separator()

        menu.add_command(
            label="📥 Descargar ficheros",
            command=descargar_ficheros,
        )

        menu.add_command(
            label="✅ Corregir programa",
            command=lambda: corregir_programa(DATOS_LOADED),
        )

    wb.after(1200, crear_menus)
