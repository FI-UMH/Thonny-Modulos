# -*- coding: utf-8 -*-
"""
Plugin completo configuracion.py — versión sin requests
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
import urllib.parse
import socket
import uuid
import threading
from collections import Counter

from thonny import get_workbench
from tkinter import (
    messagebox,
    filedialog,
    Toplevel,
    Text,
    Scrollbar,
    Label,
    Button,
    Frame,
)
import tkinter.font as tkfont

# ======================================================================
#                   VARIABLES GLOBALES Y EXPRESIONES REGEX
# ======================================================================

ALUMNO_DNI = ""
ZIP_URL = "https://github.com/FI-UMH/Thonny-Ficheros/archive/refs/heads/main.zip"

_PAREN_RE = re.compile(r"\([^()]*\)")
_HDR_DNI_RE = re.compile(r"^\s*#\s*DNI\s*=\s*(.*)$", re.MULTILINE | re.IGNORECASE)
_HDR_EJER_RE = re.compile(r"^\s*#\s*EJERCICIO\s*=\s*(.*)$", re.MULTILINE | re.IGNORECASE)

EXCLUDE = {"alumno.py", "stdin.txt", "stdout.txt"}

# ======================================================================
#                     FUNCIÓN POST SIN REQUESTS
# ======================================================================

def _send_post(url, data):
    """Envía un POST estándar usando solo urllib.request."""
    try:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        with urllib.request.urlopen(req, timeout=10) as f:
            return f.read().decode("utf-8", errors="replace")
    except Exception:
        return None

# ======================================================================
#                          UTILIDADES COMUNES
# ======================================================================

def _get_editor_text():
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
#                BLOQUE 1 — DESCARGAR FICHEROS
# ======================================================================

def descargar_ficheros():
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

                out = name.split("/", 1)[1]
                dest_path = os.path.join(carpeta, out)

                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, "wb") as f:
                    f.write(z.read(name))

        messagebox.showinfo("Descargar ficheros",
                            "Ficheros descargados correctamente.")
    except Exception as e:
        messagebox.showerror("Error al descargar ficheros", str(e))

# ======================================================================
#            BLOQUE 2 — UTILIDADES DE CORRECCIÓN
# ======================================================================

def _paren_counter(s: str) -> Counter:
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
    global ALUMNO_DNI
    dni = None
    ejercicio = None

    m_dni = _HDR_DNI_RE.search(src)
    if m_dni:
        dni = m_dni.group(1).strip().upper()
        ALUMNO_DNI = dni
    else:
        dni = ""
    m_ejer = _HDR_EJER_RE.search(src)
    if m_ejer:
        ejercicio = m_ejer.group(1).strip()
    else:
        ejercicio = ""
    return dni, ejercicio

# ======================================================================
#               VENTANA GRANDE CON SCROLL (ERRORES)
# ======================================================================

def mostrar_error_scroll(titulo, mensaje):
    ventana = Toplevel()
    ventana.title(titulo)
    ventana.geometry("820x520")

    txt = Text(ventana, wrap="none", font=("Consolas", 14))
    txt.pack(fill="both", expand=True)

    scroll_y = Scrollbar(ventana, orient="vertical", command=txt.yview)
    scroll_y.pack(side="right", fill="y")
    txt.configure(yscrollcommand=scroll_y.set)

    scroll_x = Scrollbar(ventana, orient="horizontal", command=txt.xview)
    scroll_x.pack(side="bottom", fill="x")
    txt.configure(xscrollcommand=scroll_x.set)

    txt.insert("1.0", mensaje)

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

# ======================================================================
#                EJECUCIÓN DE TESTS
# ======================================================================

def _preprocesar_codigo(src: str) -> str:
    src_mod = re.sub(r"input\s*\(", "inputt(", src)
    cabecera = (
        "def inputt(cadena=\"\"):\n"
        "    x = input(cadena)\n"
        "    print(x)\n"
        "    return x\n\n"
    )
    return cabecera + src_mod

def _run_single_test(src_code: str, test: dict) -> dict:
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

            # Ficheros iniciales
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

# ======================================================================
#                SUBIR EJERCICIO SIN REQUESTS
# ======================================================================

def _subir_ejercicios(ejercicio, dni, src_code):
    """Sube el ejercicio en background usando urllib (sin requests)."""
    try:
        hostname = socket.gethostname()

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_local = s.getsockname()[0]
            s.close()
        except Exception:
            ip_local = None

        mac_raw = uuid.getnode()
        mac = ":".join(f"{(mac_raw >> shift) & 0xff:02x}"
                       for shift in range(40, -1, -8))

        url_fi = (
            "https://script.google.com/macros/s/"
            "AKfycby3wCtvhy2sqLmp9TAl5aEQ4zHTceMAxwA_4M2HCjFJQpvxWmstEoRa5NohH0Re2eQa/exec"
        )
        url_pomares = (
            "https://script.google.com/macros/s/"
            "AKfycbw1CMfaQcJuP1cLBmt5eHryrmb83Tb0oIrWu_XHfRQpYt8kWY_g6TpsQx92QwhB_SjyYg/exec"
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

        _send_post(url_fi, data)
        _send_post(url_pomares, data)

    except Exception:
        pass

# ======================================================================
#                    CORREGIR PROGRAMA (PRINCIPAL)
# ======================================================================

def corregir_programa(DATOS_LOADED):
    src = _get_editor_text()
    if not src:
        messagebox.showerror("Corregir Programa", "No pude leer el código del editor.")
        return

    dni, ejercicio = _extraer_datos_cabecera(src)
    if not dni or not ejercicio:
        messagebox.showerror("Corregir Programa",
            ( "No se pudieron extraer DNI y EJERCICIO de la cabecera.\n\n"
            "Ejemplo de cabecera:\n"
            "    # DNI = 12345678E\n"
            "    # EJERCICIO = p001\n"
            "    ...\n    codigo fuente" )
        )
        return

    key = None
    for k in DATOS_LOADED:
        if k.lower() in ("tests.json", "test.json"):
            key = k
            break

    if not key:
        messagebox.showerror("Corregir Programa", "No encontré tests.json.")
        return

    try:
        all_tests = json.loads(_decode_bytes(DATOS_LOADED[key]))
    except Exception as e:
        messagebox.showerror("Corregir Programa", f"Error leyendo tests:\n{e}")
        return

    if ejercicio not in all_tests:
        messagebox.showerror(
            "Corregir Programa",
            f"No hay tests para el ejercicio {ejercicio}.",
        )
        return

    tests = all_tests[ejercicio]

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

    def ventana_ok():
        wb = get_workbench()
        top = Toplevel(wb)
        top.title("Corregir Programa")
        top.geometry("420x200")
        top.resizable(False, False)
        top.transient(wb)

        try:
            top.grab_set()
        except Exception:
            pass

        fuente = ("Arial", 13)

        frame = Frame(top)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        Label(frame, text="✅ Todos los tests superados.",
              font=("Arial", 14, "bold")).pack(pady=(0, 10))

        Label(
            frame,
            text= "Ejercicio CORRECTO",
            font=fuente,
            justify="center",
        ).pack(pady=(0, 20))

        def cerrar():
            top.destroy()

        Button(frame, text="Aceptar", width=12, font=fuente,
               command=cerrar).pack()

    ventana_ok()

    threading.Thread(
        target=_subir_ejercicios,
        args=(ejercicio, dni, src),
        daemon=True
    ).start()

# ======================================================================
#       CONFIGURACIÓN INICIAL (CABECERA, VISTAS, GUARDADO...)
# ======================================================================

def _config_cabecera():
    from thonny.editors import Editor
    
    _original_init = Editor.__init__

    def _hook(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        
        if self.get_filename() is None:
            global ALUMNO_DNI
            cabecera = f"# DNI = {ALUMNO_DNI}\n# EJERCICIO = \n\n"
            
            try:
                widget = self.get_text_widget()
                widget.insert("1.0", cabecera)
            except Exception:
                self.set_text(cabecera)

    Editor.__init__ = _hook

    def inicial():
        wb = get_workbench()
        ed = wb.get_editor_notebook().get_current_editor()
        
        global ALUMNO_DNI
        cabecera = f"# DNI = {ALUMNO_DNI}\n# EJERCICIO = \n\n"
        
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
            messagebox.showinfo(
                "Guardar archivo",
                "Debes guardar el archivo antes de continuar."
            )
            wb.get_menu("file").invoke_command("save_as")
            return True

        if ed.is_modified():
            messagebox.showinfo(
                "Guardar archivo",
                "Guarda el archivo antes de continuar."
            )
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
#                        PUNTO DE ENTRADA
# ======================================================================

def configurar(DATOS_LOADED):
    wb = get_workbench()

    _config_cabecera()
    _config_vistas()
    _config_guardar_antes()

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
