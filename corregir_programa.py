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
    Extrae dni, nombre, grado, ejercicio a partir del bloque inicial triple-comillas.
    """
    dni = nombre = grado = ejercicio = None
    m = _HDR_RE.search(src or "")
    if not m:
        return dni, nombre, grado, ejercicio

    body = m.group("body")

    def grab(pat):
        mm = re.search(pat, body, re.IGNORECASE)
        return mm.group(1).strip() if mm else None

    dni = grab(r"DNI\s*:\s*(.+)")
    nombre = grab(r"NOMBRE\s*:\s*(.+)")
    grado = grab(r"GRADO\s*:\s*(.+)")
    ejercicio = grab(r"EJERCICIO\s*:\s*(.+)")

    return dni, nombre, grado, ejercicio


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
#                         SUBIDA SSH
# ======================================================================

def _subir_ssh(ejercicio, dni, src_code):
    SSH_HOST = 'labatc.umh.es'
    SSH_PORT = 8801
    SSH_USER = 'alumno'
    SSH_KEY = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACCkE9WXLdXwYISozrCjeRnijUsZpBjTa9X9bltc14FX1QAAAJg14Fy4NeBc
uAAAAAtzc2gtZWQyNTUxOQAAACCkE9WXLdXwYISozrCjeRnijUsZpBjTa9X9bltc14FX1Q
AAAEDIoS5Dm5C1r3ITdmGL3n2lZHBoZ9RK/5M9Y+W6bxfK2aQT1Zct1fBghKjOsKN5GeKN
SxmkGNNr1f1uW1zXgVfVAAAAFWFsdW1ub0BkZWJpYW4tYW5kcm9pZA==
-----END OPENSSH PRIVATE KEY-----"""

    import io
    key_stream = io.StringIO(SSH_KEY)
    pkey = paramiko.Ed25519Key.from_private_key(key_stream)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, pkey=pkey)
    except Exception as e:
        raise RuntimeError(f"SSH error: {e}")

    sftp = ssh.open_sftp()
    try:
        home = f"/home/{SSH_USER}"
        d = f"{home}/entregas"
        try:
            sftp.listdir(d)
        except IOError:
            sftp.mkdir(d)

        fecha = time.strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"{dni}_{ejercicio}_{fecha}.txt"
        rpath = f"{d}/{fname}"

        content = (
            f"EJERCICIO: {ejercicio}\nDNI: {dni}\nTIMESTAMP: {fecha}\n\nCODIGO:\n{src_code}\n"
        ).encode("utf-8")

        with sftp.open(rpath, "wb") as f:
            f.write(content)
            f.flush()

        return rpath

    finally:
        try: sftp.close()
        except: pass
        try: ssh.close()
        except: pass


# ======================================================================
#                         SUBIDA DIGI WEBDAV
# ======================================================================

def _subir_digi(ejercicio, dni, src_code):
    url_base = "https://digistorage.es:443/dav/DIGIstorage/THONNY_EJERCICIOS_ENTREGADOS"
    usuario = "pomares.alejandro@gmail.com"
    password = "Tacirupeca99"

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


# ======================================================================
#                            FUNCIÓN PRINCIPAL
# ======================================================================

def run(DATOS_LOADED):
    src = _get_editor_text()
    if not src:
        messagebox.showerror("Corregir programa", "No pude leer el código del editor.")
        return

    dni, nombre, grado, ejercicio = _extraer_datos_cabecera(src)
    if not all([dni, nombre, grado, ejercicio]):
        messagebox.showerror(
            "Corregir programa",
            "No se pudieron extraer DNI, NOMBRE, GRADO y EJERCICIO de la cabecera."
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
    #                          SUBIDA SSH
    # ------------------------------------------------------------------
    try:
        remote_path = _subir_ssh(ejercicio, dni, src)
        messagebox.showinfo("Entrega SSH", f"Subido correctamente a:\n{remote_path}")
    except Exception as e:
        messagebox.showerror("SSH", str(e))
        return

    # ------------------------------------------------------------------
    #                          SUBIDA DIGI
    # ------------------------------------------------------------------
    try:
        _subir_digi(ejercicio, dni, src)
        messagebox.showinfo("DIGI", "Subido correctamente a DIGI WebDAV.")
    except Exception as e:
        messagebox.showerror("DIGI", str(e))
