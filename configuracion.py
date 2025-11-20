# -*- coding: utf-8 -*-
"""
Módulo de configuración central.
Se ejecuta desde descargar_configuracion.py.
"""

import sys, types, urllib.request, io, zipfile
from thonny import get_workbench
from tkinter import messagebox

# -------------------------------------------------------------------
# URL donde obtener módulos bajo demanda
# -------------------------------------------------------------------
BASE_MOD_URL = "https://raw.githubusercontent.com/FI-UMH/Thonny-Modulos/main/"


# ===================================================================
#     FUNCIONES DE CONFIGURACIÓN INTEGRADAS (cabecera, consola…)
# ===================================================================

def _insertar_cabecera():
    from thonny.editors import Editor
    CAB = """'''
DNI        : 
NOMBRE     : 
GRADO      : 
EJERCICIO  : 
'''
"""
    _orig = Editor.__init__

    def hook(self, *a, **k):
        _orig(self, *a, **k)
        if self.get_filename() is None:
            try:
                self.get_text_widget().insert("1.0", CAB)
            except:
                self.set_text(CAB)

    Editor.__init__ = hook


def _activar_vistas():
    wb = get_workbench()
    wb.after(1000, lambda: wb.show_view("VariablesView", True))
    wb.after(1000, lambda: wb.show_view("ShellView", True))


def _guardar_antes_ejecutar():
    from tkinter import messagebox
    wb = get_workbench()

    def necesita_guardar():
        ed = wb.get_editor_notebook().get_current_editor()
        if not ed:
            return False
        fn = ed.get_filename()

        if fn is None:
            messagebox.showinfo("Guardar", "Debes guardar el archivo.")
            wb.get_menu("file").invoke_command("save_as")
            return True
        if ed.is_modified():
            messagebox.showinfo("Guardar", "Guarda antes de ejecutar.")
            wb.get_menu("file").invoke_command("save")
            return True
        return False

    def intercept(*_):
        if necesita_guardar():
            return "break"

    wb.bind("<<RunScript>>", intercept, True)
    wb.bind("<<RunCurrentScript>>", intercept, True)
    wb.bind("<<DebugRun>>", intercept, True)
    wb.bind("<<DebugCurrentScript>>", intercept, True)


def _linea_menu():
    wb = get_workbench()

    def add():
        menu = wb.get_menu("tools")
        if menu:
            menu.add_separator()
        else:
            wb.after(500, add)

    wb.after(1000, add)


# ===================================================================
#             DESCARGA Y EJECUCIÓN DINÁMICA DE MÓDULOS
# ===================================================================

def _descargar_modulo(nombre):
    url = BASE_MOD_URL + nombre
    req = urllib.request.Request(url, headers={"User-Agent": "ThonnyDynamicLoader"})
    data = urllib.request.urlopen(req, timeout=20).read()
    code = data.decode("utf-8")

    mod = types.ModuleType("mod_dynamic")
    exec(code, mod.__dict__)
    return mod


def _ejecutar_modulo(nombre, *args):
    mod = _descargar_modulo(nombre)
    try:
        if hasattr(mod, "run"):
            mod.run(*args)
        elif hasattr(mod, nombre.replace(".py", "")):
            getattr(mod, nombre.replace(".py", ""))(*args)
    finally:
        if "mod_dynamic" in sys.modules:
            del sys.modules["mod_dynamic"]


# ===================================================================
#                         CONFIGURAR EL ENTORNO
# ===================================================================

def configurar(DATOS_LOADED):
    wb = get_workbench()

    # 1. Configuración integrada
    _insertar_cabecera()
    _activar_vistas()
    _guardar_antes_ejecutar()
    _linea_menu()

    # 2. Crear menús de herramientas
    def crear_menus():
        menu = wb.get_menu("tools")
        if not menu:
            wb.after(500, crear_menus)
            return

        # Menú: DESCARGAR FICHEROS
        def _menu_desc_fich():
            _ejecutar_modulo("descargar_ficheros.py")

        menu.add_command(label="📥 Descargar ficheros", command=_menu_desc_fich)

        # Menú: CORREGIR PROGRAMA
        def _menu_corregir():
            _ejecutar_modulo("corregir_programa.py", DATOS_LOADED)

        menu.add_command(label="✅ Corregir programa", command=_menu_corregir)

    wb.after(1200, crear_menus)
