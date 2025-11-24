# -*- coding: utf-8 -*-
"""
Módulo: corregir_programa.py
Versión sin SMB. Incluye:
 - Ejecución de tests desde DATOS_LOADED
 - Subida SSH
 - Subida DIGI WebDAV
 - Sin load_plugin()
"""

import sys, os, json, re, subprocess, tempfile, traceback, time
from tkinter import messagebox, Toplevel, Text, Scrollbar
from collections import Counter
import requests
import paramiko
import socket, uuid


# ======================================================================
#                     UTILIDADES THONNY
# ======================================================================

def _get_editor_text():
    """Lee el código del editor actual de Thonny."""
    try:
        from thonny import get_workbench
        wb = get_workbench()
        editor = wb.get_editor_notebook().get_current_editor()
        if not editor:
            return None
        try:
            return editor.get_text_widget().get("1.0", "end-1c")
        except:
            return editor.get_text()
    except:
        return None


# ======================================================================
#                     SUPPORT FUNCTIONS
# ======================================================================

_PAREN_RE = re.compile(r"\([^()]*\)")

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
        except:
            continue
    return b.decode("utf-8", errors="replace")


_HDR_RE = re.compile(
    r"^\s*(['\"]{3})(?P<body>.*?)(\1)", re.DOTALL
)

def _extraer_datos_cabecera(src: str):
    """
    Extrae DNI y EJERCICIO de la cabecera simplificada.
    Formato esperado:
    # DNI = 12345678X
    # EJERCICIO = p001
    """
    dni = ejercicio = None

    # Buscar líneas tipo "# DNI = xxxx"
    m_dni = re.search(r"^\s*#\s*DNI\s*=\s*(.+)", src, re.MULTILINE | re.IGNORECASE)
    if m_dni:
        dni = m_dni.group(1).strip()

    # Buscar líneas tipo "# EJERCICIO = p001"
    m_ejer = re.search(r"^\s*#\s*EJERCICIO\s*=\s*(.+)", src, re.MULTILINE | re.IGNORECASE)
    if m_ejer:
        ejercicio = m_ejer.group(1).strip()

    return dni, ejercicio



def mostrar_error_scroll(titulo, mensaje):
    """Ventana para mostrar errores largos."""
    ventana = Toplevel()
    ventana.title(titulo)
    ventana.geometry("700x500")

    txt = Text(ventana, wrap="none")
    txt.pack(fill="both", expand=True)

    scroll_y = Scrollbar(ventana, orient="vertical", command=txt.yview)
    scroll_y.pack(side="right", fill="y")
    txt.configure(yscrollcommand=scroll_y.set)

    scroll_x = Scrollbar(ventana, orient="horizontal", command=txt.xview)
    scroll_x.pack(side="bottom", fill="x")
    txt.configure(xscrollcommand=scroll_x.set)

    txt.insert("1.0", mensaje)
    txt.config(state="disabled")


# ======================================================================
#                     PREPROCESAR CÓDIGO
# ======================================================================

def _preprocesar_codigo(src: str) -> str:
    """Reescribe input() por inputt() e inserta inputt()."""
    src_mod = re.sub(r"input\s*\(", "inputt(", src)
    cabecera = (
        "def inputt(cadena=\"\"):\n"
        "    x = input(cadena)\n"
        "    print(x)\n"
        "    return x\n\n"
    )
    return cabecera + src_mod


# ======================================================================
#                     EJECUTAR TESTS
# ======================================================================

EXCLUDE = {"alumno.py", "stdin.txt", "stdout.txt"}

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


# ======================================================================
#                         SUBIR EJERCICIOS
# ======================================================================

def _subir_ejercicios(ejercicio, dni, src_code):
    # --- Hostname ---
    hostname = socket.gethostname()
    # --- IP local fiable ---
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip_local = s.getsockname()[0]
        s.close()
    except:
        ip_local = None
    # --- MAC principal ---
    mac_raw = uuid.getnode()
    mac = ":".join(f"{(mac_raw >> shift) & 0xff:02x}" for shift in range(40, -1, -8))


    url_fi = "https://script.google.com/macros/s/AKfycby3wCtvhy2sqLmp9TAl5aEQ4zHTceMAxwA_4M2HCjFJQpvxWmstEoRa5NohH0Re2eQa/exec"
    url_pomares = "https://script.google.com/macros/s/AKfycbzngWPpSA7pq92WFWQnNdpOEtKWcOUPvgNs_bSwM3TcIsnNBoIwPyM9M183TPXNa7eGOg/exec"

    data = {
        "key": "Thonny#fi",  
        "ordenador": hostname,
        "ip": ip_local,
        "mac":mac,
        "dni": dni,
        "ejercicio": ejercicio,
        "fuente": src_code
    }

    url_fi = "https://script.google.com/macros/s/AKfycby3wCtvhy2sqLmp9TAl5aEQ4zHTceMAxwA_4M2HCjFJQpvxWmstEoRa5NohH0Re2eQa/exec"
    url_pomares = "https://script.google.com/macros/s/AKfycbxwDPaWyBATk_xRuxnGLEtPhpULa3WJHVidj7_7ttYhdYwmiVVI1wJxwkUDrQespcku-A/exec"

    respuesta_fi = requests.post(url_fi, data=data)
    respuesta_pomares = requests.post(url_pomares, data=data)

    return respuesta_pomares.text
''' 
    url_base = "https://digistorage.es:443/dav/DIGIstorage/THONNY_EJERCICIOS_ENTREGADOS"
    usuario = "pepe@gmail.com"
    password = "430882"

    fecha = time.strftime("%Y-%m-%d_%H-%M-%S")
    fname = f"{dni}_{ejercicio}_{fecha}.txt"
    url = f"{url_base}/{fname}"

    r = requests.put(
        url,
        data=src_code.encode("utf-8"),
        auth=(usuario, password),
        verify=True
    )

    if r.status_code not in (200, 201, 204):
        raise RuntimeError(f"Error DIGI: {r.status_code}: {r.text}")
'''

# ======================================================================
#                            FUNCIÓN PRINCIPAL
# ======================================================================

def run(DATOS_LOADED):
    src = _get_editor_text()
    if not src:
        messagebox.showerror("Corregir programa", "No pude leer el código del editor.")
        return

    dni, ejercicio = _extraer_datos_cabecera(src)
    if not all([dni, ejercicio]):
        messagebox.showerror(
            "Corregir programa",
            "No se pudieron extraer DNI y EJERCICIO de la cabecera."
        )
        return

    # Buscar tests.json en los datos cargados
    key = None
    for k in DATOS_LOADED:
        if k.lower() == "tests.json":
            key = k
            break

    if not key:
        messagebox.showerror("Corregir programa", "No encontré tests.json en memoria.")
        return

    try:
        tests_all = json.loads(_decode_bytes(DATOS_LOADED[key]))
    except Exception as e:
        messagebox.showerror("Corregir programa", f"Error leyendo tests.json:\n{e}")
        return

    if ejercicio not in tests_all:
        messagebox.showerror("Corregir programa", f"No hay tests para el ejercicio {ejercicio}.")
        return

    tests = tests_all[ejercicio]

    # ------------------------------------------------------------------
    #                       EJECUCIÓN DE TESTS
    # ------------------------------------------------------------------
    for i, t in enumerate(tests, start=1):
        r = _run_single_test(src, t)

        if r["error"]:
            messagebox.showerror("Error", f"Error en test #{i}:\n{r['error']}")
            return

        if not r["ok_stdout"] or not r["ok_files"]:
            msg = (
                f"El ejercicio NO supera el test #{i}\n\n"
                "▶ RESULTADO OBTENIDO:\n"
                f"{r['stdout_alumno']}\n\n"
                "▶ RESULTADO ESPERADO:\n"
                f"{t.get('stdout','')}\n"
            )
            mostrar_error_scroll("Corregir programa", msg)
            return

    messagebox.showinfo("Corregir programa", "✅ Todos los tests superados.")

    # ------------------------------------------------------------------
    #                          SUBIDA EJERCICIOS
    # ------------------------------------------------------------------
    try:
        respuesta = _subir_ejercicios(ejercicio, dni, src)
        messagebox.showinfo("Entrega ejercicios", respuesta)
    except Exception as e:
        messagebox.showerror("Error en la entrega de ejercicios", str(e))
        return
