# -*- coding: utf-8 -*-
"""
Plugin completo configuracion.py — versión final
"""

import sys
import os
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
)
import tkinter.font as tkfont
import requests

# ======================================================================
#                   VARIABLES GLOBALES Y EXPRESIONES REGEX
# ======================================================================

ALUMNO_DNI = ""
ZIP_URL = "https://github.com/FI-UMH/Thonny-Ficheros/archive/refs/heads/main.zip"

_PAREN_RE = re.compile(r"\([^()]*\)")
_HDR_DNI_RE = re.compile(r"^\s*#\s*DNI\s*=\s*(.+)", re.MULTILINE | re.IGNORECASE)
_HDR_EJER_RE = re.compile(r"^\s*#\s*EJERCICIO\s*=\s*(.+)", re.MULTILINE | re.IGNORECASE)

EXCLUDE = {"alumno.py", "stdin.txt", "stdout.txt"}


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
        
    m_ejer = _HDR_EJER_RE.search(src)
    if m_ejer:
        ejercicio = m_ejer.group(1).strip()

    return dni, ejercicio


# ======================================================================
#               VENTANA GRANDE CON SCROLL (ERRORES)
# ======================================================================

def _mostrar_error_scroll(titulo, mensaje):
    ventana = Toplevel()
    ventana.title(titulo)
    ventana.geometry("820x520")

    txt = Text(ventana, wrap="none", font=("Consolas", 10))
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

            # Ejecutar programa del alumno
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

            # Ficheros finales
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
#                SUBIR EJERCICIO (EN SEGUNDO PLANO)
# ======================================================================

def _subir_ejercicios(ejercicio, dni, src_code):
    """Sube el ejercicio en background de forma silenciosa."""
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

        requests.post(url_fi, data=data, timeout=10)
        requests.post(url_pomares, data=data, timeout=10)

    except Exception:
        pass


# ======================================================================
#                    CORREGIR EJERCICIO (PRINCIPAL)
# ======================================================================


def corregir_ejercicio_programa(codigo_alumno: str, ejercicio: str, lista_tests: list):
    """
    Corrige ejercicios tipo programa (pXXX).
    Mantiene el estilo de mensajes de 'corregir_ejercicio_funcion', mostrando:
    - Contexto inicial (stdin + ficheros)
    - Resultado obtenido (stdout + ficheros finales)
    - Resultado correcto (stdout + ficheros finales)
    """

    import tempfile
    import importlib.util
    import io
    import os
    import sys
    from contextlib import redirect_stdout

    aciertos = 0
    errores = []

    # 1. Guardar el código del alumno en un archivo temporal
    with tempfile.TemporaryDirectory() as tmpdir:
        ruta_mod = os.path.join(tmpdir, "alumno.py")
        with open(ruta_mod, "w", encoding="utf-8") as f:
            f.write(codigo_alumno)

        # 2. Ejecutar cada test del JSON
        for idx, test in enumerate(lista_tests, start=1):

            stdin_val = test.get("stdin", "")
            files_ini = test.get("filesIni", {})
            stdout_exp = test.get("stdout", "")
            files_exp  = test.get("filesEnd", {})

            # 3. Ejecutar programa completo en un directorio aislado
            with tempfile.TemporaryDirectory() as work:
                cwd_old = os.getcwd()
                os.chdir(work)
                try:
                    # Crear ficheros iniciales
                    for nombre, contenido in files_ini.items():
                        with open(nombre, "w", encoding="utf-8") as f:
                            f.write(contenido)

                    # Preparar entradas del usuario
                    salida = io.StringIO()
                    old_stdin = sys.stdin
                    sys.stdin = io.StringIO(stdin_val)

                    try:
                        # Ejecutar script entero
                        with redirect_stdout(salida):
                            spec = importlib.util.spec_from_file_location("alumno", ruta_mod)
                            mod = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(mod)
                    except Exception as e:
                        errores.append(f"Error ejecutando test {idx}:\n{e}")
                        sys.stdin = old_stdin
                        continue
                    finally:
                        sys.stdin = old_stdin

                    stdout_obt = salida.getvalue()

                    # Cargar ficheros finales
                    files_end = {}
                    for nombre in os.listdir(work):
                        if os.path.isfile(nombre):
                            with open(nombre, "r", encoding="utf-8", errors="replace") as f:
                                files_end[nombre] = f.read()

                finally:
                    os.chdir(cwd_old)

            # 4. Comprobar diferencias
            diferencias = []

            if stdout_obt != stdout_exp:
                diferencias.append("- La salida por pantalla no coincide.")

            if files_end != files_exp:
                diferencias.append("- Los ficheros finales no coinciden.")

            if diferencias:
                # Construcción del mensaje estilo corregir función
                files_ini_text = "\n".join(f"{k} → {v}" for k, v in files_ini.items())
                files_end_text = "\n".join(f"{k} → {v}" for k, v in files_end.items())
                files_exp_text = "\n".join(f"{k} → {v}" for k, v in files_exp.items())

                msg = (
                    "El ejercicio NO supera el test:\n\n"
                    "▶ CONTEXTO INICIAL\n"
                    "─────── Teclado ───────\n"
                    f"{stdin_val}"
                    "─────── Ficheros ───────\n"
                    f"{files_ini_text}\n\n"

                    "▶ RESULTADO OBTENIDO\n"
                    "─────── Pantalla ───────\n"
                    f"{stdout_obt}"
                    "─────── Ficheros ───────\n"
                    f"{files_end_text}\n\n"

                    "▶ RESULTADO CORRECTO\n"
                    "─────── Pantalla ───────\n"
                    f"{stdout_exp}"
                    "─────── Ficheros ───────\n"
                    f"{files_exp_text}"
                ).replace("\n\n", "\n")

                errores.append(msg)

            else:
                aciertos += 1

    # 5. Mostrar resultado final
    if errores:
        texto = f"✔ Tests superados: {aciertos}/{len(lista_tests)}\n\n" + "\n\n".join(errores)
        _mostrar_error_scroll("Resultado de la corrección", texto)
    else:
        messagebox.showerror(f"🎉 ¡Todos los tests ({aciertos}) superados correctamente!")



def corregir_ejercicio_funcion(codigo_alumno: str, ejercicio: str, lista_tests: list):
    """
    Corrige ejercicios fXXX basados en funciones utilizando el JSON generado por generar_json.py.
    Cada test incluye:
      funcName, args, stdin, filesIni, return, stdout, filesEnd.
    """

    import tempfile
    import importlib.util
    import io
    import os
    from contextlib import redirect_stdout
    from unittest.mock import patch

    errores = []
    aciertos = 0

    # 1) Guardar el código del alumno en un módulo temporal
    with tempfile.TemporaryDirectory() as tmpdir:
        ruta_mod = os.path.join(tmpdir, "alumno.py")
        with open(ruta_mod, "w", encoding="utf-8") as f:
            f.write(codigo_alumno)

        # Importar módulo alumno
        spec = importlib.util.spec_from_file_location("alumno_mod", ruta_mod)
        alumno_mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(alumno_mod)
        except Exception as e:
            messagebox.showerror(f"❌ Error importando el módulo del alumno:\n{e}")
            return

        # 2) Ejecutar todos los tests generados
        for idx, test in enumerate(lista_tests, 1):

            funcName = test["funcName"]
            args     = test["args"]
            stdin_val = test["stdin"]
            filesIni  = test["filesIni"]
            ret_exp   = test["return"]
            stdout_exp = test["stdout"]
            filesEnd_exp = test["filesEnd"]

            # Validar que el alumno ha definido la función
            if not hasattr(alumno_mod, funcName):
                errores.append(f"La función '{funcName}' no está definida por el alumno.")
                continue

            func_alumno = getattr(alumno_mod, funcName)

            # 3) Ejecución aislada para este test
            with tempfile.TemporaryDirectory() as work:
                cwd_old = os.getcwd()
                os.chdir(work)
                try:
                    # Ficheros iniciales
                    for nom, contenido in filesIni.items():
                        with open(nom, "w", encoding="utf-8") as f:
                            f.write(contenido)

                    # Preparar stdin / stdout
                    stdin_io = io.StringIO(stdin_val)
                    stdout_io = io.StringIO()

                    def fake_input(prompt=""):
                        return stdin_io.readline().rstrip("\n")

                    # Ejecutar la función del alumno
                    try:
                        with redirect_stdout(stdout_io), patch("builtins.input", fake_input):
                            ret_obt = func_alumno(*args)
                    except Exception as e:
                        errores.append(f"Test {idx}:\n❌ Error ejecutando la función:\n{e}")
                        os.chdir(cwd_old)
                        continue

                    stdout_obt = stdout_io.getvalue()

                    # Ficheros finales obtenidos
                    filesEnd_obt = {}
                    for nom in os.listdir(work):
                        if os.path.isfile(nom):
                            with open(nom, "r", encoding="utf-8", errors="replace") as f:
                                filesEnd_obt[nom] = f.read()

                finally:
                    os.chdir(cwd_old)

            # 4) Comprobaciones
            diferencias = []

            if ret_obt != ret_exp:
                diferencias.append("- Return incorrecto: esperado={ret_exp!r}, obtenido={ret_obt!r}")

            if stdout_obt != stdout_exp:
                diferencias.append("- La salida por pantalla no coincide.")

            if filesEnd_obt != filesEnd_exp:
                diferencias.append("- Los ficheros finales no coinciden.")

            # 5) Si hay errores → generar mensaje estilo corregir programa
            if diferencias:

                args_text = ", ".join(repr(a) for a in args)

                files_ini_text = "\n".join(
                    f"{nom} → {cont}"
                    for nom, cont in filesIni.items()
                )

                files_end_text = "\n".join(
                    f"{nom} → {cont}"
                    for nom, cont in filesEnd_obt.items()
                )

                files_exp_text = "\n".join(
                    f"{nom} → {cont}"
                    for nom, cont in filesEnd_exp.items()
                )

                msg = (
                    f"La función NO supera el test.\n\n"
                    f"FUNCION: {funcName}\n"
                    f"ARGUMENTOS: {args_text}\n\n"

                    "▶ CONTEXTO INICIAL\n"
                    "─────── Teclado ───────\n"
                    f"{stdin_val}"
                    "─────── Ficheros ───────\n"
                    f"{files_ini_text}\n\n"

                    "▶ RESULTADO OBTENIDO\n"
                    "─────── return ───────\n"
                    f"{ret_obt!r}\n"
                    "─────── Pantalla ───────\n"
                    f"{stdout_obt}"
                    "─────── Ficheros ───────\n"
                    f"{files_end_text}\n\n"

                    "▶ RESULTADO CORRECTO\n"
                    "─────── return ───────\n"
                    f"{ret_exp!r}\n"
                    "─────── Pantalla ───────\n"
                    f"{stdout_exp}"
                    "─────── Ficheros ───────\n"
                    f"{files_exp_text}"
                ).replace("\n\n", "\n")

                errores.append(msg)

            else:
                aciertos += 1

    # 6) Mostrar resultado final
    if errores:
        texto = f"✔ Tests superados: {aciertos}/{len(lista_tests)}\n\n" + "\n\n".join(errores)
        _mostrar_error_scroll("Resultado de la corrección", texto)
    else:
        messagebox.showerror(f"🎉 ¡Todos los tests ({aciertos}) superados correctamente!")


def _cargar_tests_json(DATOS_LOADED):
    """
    Carga los tests desde el objeto DATOS_LOADED.
    El parámetro DATOS_LOADED debe ser:
        - un dict ya cargado desde tests.json
        - o un objeto con atributo 'tests' (según implementación anterior)

    Devuelve:
        dict con todas las claves de ejercicios y sus tests.
    """

    if DATOS_LOADED is None:
        messagebox.showerror("Error", "No se han cargado los datos de tests.")
        return {}

    # Caso 1: es un diccionario (lo más habitual)
    if isinstance(DATOS_LOADED, dict):
        return DATOS_LOADED

    # Caso 2: es un objeto con atributo .tests
    if hasattr(DATOS_LOADED, "tests"):
        try:
            return DATOS_LOADED.tests
        except Exception as e:
            messagebox.showerror("Error cargando tests", str(e))
            return {}

    messagebox.showerror(
        "Error",
        "Formato no válido para DATOS_LOADED. "
        "Debe ser un diccionario o contener atributo 'tests'."
    )
    return {}



def corregir_ejercicio(DATOS_LOADED):
    codigo = _get_editor_text()        # Código del alumno
    dni, ejercicio = _extraer_datos_cabecera(codigo)

    if not ejercicio:
        messagebox.showerror("No se encontró el código del ejercicio en la cabecera.")
        return

    # Cargar tests.json
    tests_dict = _cargar_tests_json(DATOS_LOADED)
    if ejercicio not in tests_dict:
        messagebox.showerror(f"No hay tests para el ejercicio {ejercicio}.")
        return

    lista_tests = tests_dict[ejercicio]

    # Detectar si es programa o función
    if ejercicio.startswith("p"):
        corregir_ejercicio_programa(codigo, ejercicio, lista_tests)
    elif ejercicio.startswith("f"):
        corregir_ejercicio_funcion(codigo, ejercicio, lista_tests)
    else:
        messagebox.showerror("El ejercicio debe empezar por 'p' o 'f'.")


# ======================================================================
#       CONFIGURACIÓN INICIAL (CABECERA, VISTAS, GUARDADO...)
# ======================================================================

def _config_cabecera():
    """Inserta cabecera con DNI + EJERCICIO en editores nuevos."""
    from thonny.editors import Editor
    
    # IMPORTANTE: Ya NO se define la cabecera aquí,
    # ya que capturaría el valor inicial de ALUMNO_DNI ("").
    
    _original_init = Editor.__init__

    def _hook(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        
        if self.get_filename() is None:
            # 💡 SOLUCIÓN: Generamos la cabecera *dentro* del hook
            # para que lea el valor actual de la global ALUMNO_DNI.
            global ALUMNO_DNI  # (opcional, pero buena práctica si se modificara aquí)
            cabecera = f"# DNI = {ALUMNO_DNI}\n# EJERCICIO = \n\n"
            
            try:
                widget = self.get_text_widget()
                widget.insert("1.0", cabecera)
            except Exception:
                self.set_text(cabecera)

    Editor.__init__ = _hook

    # Primera pestaña ya abierta
    def inicial():
        wb = get_workbench()
        ed = wb.get_editor_notebook().get_current_editor()
        
        # 💡 SOLUCIÓN: Generamos la cabecera *dentro* de inicial()
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

    # Configuraciones base
    _config_cabecera()
    _config_vistas()
    _config_guardar_antes()

    # Menús
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
            label="✅ Corregir ejercicio",
            command=lambda: corregir_ejercicio(DATOS_LOADED),
        )

    wb.after(1200, crear_menus)
