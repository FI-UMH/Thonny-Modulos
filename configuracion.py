# -*- coding: utf-8 -*-
"""
configuracion.py — Módulo central ejecutado por descargar_configuracion.py

Incluye de forma integrada TODAS las configuraciones de:
 - 01_cabecera_programa.py
 - 02_ver_variables_consola.py
 - 03_guardar_antes_ejecutar_corregir.py
 - 05_menu_herramientas_linea.py

Además crea los menús:
 - 📥 Descargar ficheros
 - ✅ Corregir programa

Y permite cargar módulos dinámicamente desde FI-UMH/Thonny-Modulos
"""

import sys, types, urllib.request
from thonny import get_workbench
from tkinter import messagebox


# =====================================================================
# URL donde se obtienen los módulos dinámicos
# =====================================================================

BASE_MOD_URL = "https://raw.githubusercontent.com/FI-UMH/Thonny-Modulos/main/"


# =====================================================================
#                 01 — CABECERA AUTOMÁTICA AL CREAR ARCHIVOS
# =====================================================================

def _config_cabecera():
    from thonny.editors import Editor

    CABECERA = """'''
DNI        : 
NOMBRE     : 
GRADO      : 
EJERCICIO  : 
'''
"""

    _original_init = Editor.__init__

    def _hook(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)

        if self.get_filename() is None:
            try:
                widget = self.get_text_widget()
                widget.insert("1.0", CABECERA)
            except:
                self.set_text(CABECERA)

    Editor.__init__ = _hook

    # Refuerzo para el primer editor
    def inicial():
        wb = get_workbench()
        ed = wb.get_editor_notebook().get_current_editor()
        if ed and ed.get_filename() is None:
            try:
                w = ed.get_text_widget()
                w.delete("1.0", "end")
                w.insert("1.0", CABECERA)
            except:
                ed.set_text(CABECERA)

    wb = get_workbench()
    wb.after(500, inicial)

    # Mostrar instrucciones (como original)
    INSTRUCCIONES = (
        "INSTRUCCIONES DEL EJERCICIO\n\n"
        "1. Rellena la cabecera con tus datos.\n"
        "2. Guarda el archivo antes de ejecutar o corregir.\n"
        "3. No elimines la cabecera.\n"
        "4. Escribe el programa debajo de la cabecera.\n"
    )
    wb.after(800, lambda: messagebox.showinfo("Instrucciones", INSTRUCCIONES, parent=wb))


# =====================================================================
#           02 — ACTIVAR VISTA DE VARIABLES Y CONSOLA AUTOMÁTICAMENTE
# =====================================================================

def _config_vistas():
    wb = get_workbench()

    def activar():
        try:
            wb.show_view("VariablesView", True)
            wb.show_view("ShellView", True)
        except Exception:
            pass

    wb.after(1000, activar)


# =====================================================================
#          03 — OBLIGAR A GUARDAR ANTES DE EJECUTAR O DEPURAR
# =====================================================================

def _config_guardar_antes():
    from thonny import get_workbench
    from tkinter import messagebox

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

    # Interceptar ejecuciones y depuración
    wb.bind("<<RunScript>>", intercept, True)
    wb.bind("<<RunCurrentScript>>", intercept, True)
    wb.bind("<<DebugRun>>", intercept, True)
    wb.bind("<<DebugCurrentScript>>", intercept, True)


# =====================================================================
#              DESCARGA Y EJECUCIÓN DINÁMICA DE MÓDULOS
# =====================================================================

def _descargar_modulo(nombre):
    """Descarga y ejecuta un módulo python desde FI-UMH/Thonny-Modulos."""
    url = BASE_MOD_URL + nombre
    req = urllib.request.Request(url, headers={"User-Agent": "ThonnyDynamicLoader"})
    data = urllib.request.urlopen(req, timeout=20).read()

    code = data.decode("utf-8")
    mod = types.ModuleType("mod_dynamic")
    exec(code, mod.__dict__)
    return mod


def _ejecutar_modulo(nombre, *args):
    """Ejecuta módulo y lo elimina de memoria al terminar."""
    mod = _descargar_modulo(nombre)

    try:
        # Módulos estructurados con run()
        if hasattr(mod, "run"):
            mod.run(*args)
        else:
            # Alternativa: función del mismo nombre
            fn = nombre.replace(".py", "")
            if hasattr(mod, fn):
                getattr(mod, fn)(*args)
    finally:
        if "mod_dynamic" in sys.modules:
            del sys.modules["mod_dynamic"]


# =====================================================================
#                       FUNCIÓN PRINCIPAL DE CONFIGURACIÓN
# =====================================================================

def configurar(DATOS_LOADED):
    wb = get_workbench()

    # 1. Aplicar las configuraciones en un orden específico
    _config_cabecera()
    _config_vistas()
    _config_guardar_antes()
    _config_linea_menu()

    # 2. Menús
    def crear_menus():
        menu = wb.get_menu("tools")
        if not menu:
            wb.after(500, crear_menus)
            return
            
        # Añadir línea separadora justo ANTES de los menús propios
        menu.add_separator()
        
        # 📥 Descargar ficheros
        def accion_descargar_ficheros():
            _ejecutar_modulo("descargar_ficheros.py")

        menu.add_command(
            label="📥 Descargar ficheros",
            command=accion_descargar_ficheros
        )

        # ✅ Corregir programa
        def accion_corregir_programa():
            _ejecutar_modulo("corregir_programa.py", DATOS_LOADED)

        menu.add_command(
            label="✅ Corregir programa",
            command=accion_corregir_programa
        )

    wb.after(1200, crear_menus)
